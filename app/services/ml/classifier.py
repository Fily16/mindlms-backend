"""
Servicio de clasificación de riesgo de salud mental.
- Modelo principal: RoBERTa fine-tuned (cuando está entrenado)
- Fallback: Score basado en marcadores lingüísticos + Random Forest
- Siempre: Detección de fragmentos de alto riesgo
"""

import os
import numpy as np
from typing import Dict
from loguru import logger

from app.core.config import settings
from app.schemas.analysis import RiskLevel
from app.services.nlp.text_processor import TextProcessor

# Intentar importar modelos ML
try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
    import torch
    TRANSFORMERS_AVAILABLE = True
except ImportError:
    TRANSFORMERS_AVAILABLE = False
    logger.warning("Transformers no disponible. Usando clasificador basado en reglas.")

try:
    import joblib
    JOBLIB_AVAILABLE = True
except ImportError:
    JOBLIB_AVAILABLE = False


class RiskClassifier:
    """Clasificador de nivel de riesgo basado en texto."""

    _instance = None
    _model = None
    _tokenizer = None
    _rf_model = None  # Random Forest baseline
    _tfidf = None     # TF-IDF vectorizer (para Random Forest)
    _mode = "rules"   # "transformer", "random_forest", "rules"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def load_model(self):
        """Carga el mejor modelo disponible."""
        if self._model is not None or self._mode != "rules":
            return

        model_path = settings.MODEL_PATH

        # 1. Intentar cargar RoBERTa fine-tuned.
        # Origen: un repo del Hugging Face Hub si ROBERTA_MODEL_ID está
        # definido (producción: evita los 476 MB del modelo en git), o la
        # carpeta local ml/data/models/roberta-finetuned (desarrollo).
        hub_model_id = getattr(settings, "ROBERTA_MODEL_ID", "") or ""
        transformer_path = os.path.join(model_path, "roberta-finetuned")
        transformer_src = hub_model_id or transformer_path
        if TRANSFORMERS_AVAILABLE and (hub_model_id or os.path.exists(transformer_path)):
            try:
                self._tokenizer = AutoTokenizer.from_pretrained(transformer_src)
                self._model = AutoModelForSequenceClassification.from_pretrained(transformer_src)
                self._model.eval()
                self._mode = "transformer"
                logger.info(f"Modelo RoBERTa cargado desde {transformer_src}")
                return
            except Exception as e:
                logger.error(f"Error cargando RoBERTa: {e}")

        # 2. Intentar cargar Random Forest + TF-IDF vectorizer
        rf_path = os.path.join(model_path, "random_forest.pkl")
        tfidf_path = os.path.join(model_path, "tfidf_vectorizer.pkl")
        if JOBLIB_AVAILABLE and os.path.exists(rf_path) and os.path.exists(tfidf_path):
            try:
                self._rf_model = joblib.load(rf_path)
                self._tfidf = joblib.load(tfidf_path)
                self._mode = "random_forest"
                logger.info(f"Modelo Random Forest + TF-IDF cargado desde {rf_path}")
                return
            except Exception as e:
                logger.error(f"Error cargando Random Forest: {e}")

        # 3. Fallback: clasificador basado en reglas lingüísticas
        self._mode = "rules"
        logger.info("Usando clasificador basado en reglas lingüísticas (sin modelo ML entrenado)")

    async def predict(self, text: str) -> Dict:
        """Predice el nivel de riesgo de un texto."""
        await self.load_model()

        processor = TextProcessor()
        markers = processor.extract_linguistic_markers(text)
        flagged = processor.detect_high_risk_fragments(text)

        if self._mode == "transformer":
            result = self._predict_transformer(text)
        elif self._mode == "random_forest":
            result = self._predict_random_forest(text, markers)
        else:
            result = self._predict_rules(markers, flagged)

        # Siempre agregar fragmentos de alto riesgo
        result["flagged_fragments"] = flagged
        # El backend concreto que hizo la predicción (para trazabilidad)
        result["model_backend"] = self._mode

        # Si hay fragmentos de alto riesgo, elevar el nivel mínimo a medio
        if flagged and result["risk_level"] == RiskLevel.LOW:
            result["risk_level"] = RiskLevel.MEDIUM
            result["risk_score"] = max(result["risk_score"], settings.RISK_THRESHOLD_MEDIUM)

        return result

    def _predict_transformer(self, text: str) -> Dict:
        """Inferencia con modelo RoBERTa fine-tuned."""
        inputs = self._tokenizer(
            text,
            return_tensors="pt",
            truncation=True,
            max_length=settings.MAX_TEXT_LENGTH,
            padding=True,
        )
        with torch.no_grad():
            outputs = self._model(**inputs)
            probs = torch.softmax(outputs.logits, dim=-1).numpy()[0]

        # Asumiendo 3 clases: [bajo, medio, alto]
        risk_score = float(probs[1] * 0.5 + probs[2] * 1.0)
        confidence = float(max(probs))
        predicted_class = int(np.argmax(probs))
        levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]

        return {
            "risk_level": levels[predicted_class],
            "risk_score": round(risk_score, 4),
            "confidence": round(confidence, 4),
        }

    def _predict_random_forest(self, text: str, markers) -> Dict:
        """Inferencia con Random Forest usando TF-IDF + marcadores lingüísticos."""
        from scipy.sparse import hstack

        processor = TextProcessor()
        flagged = processor.detect_high_risk_fragments(text)

        # TF-IDF features (mismo vectorizador que se usó en entrenamiento)
        tfidf_features = self._tfidf.transform([text])

        # Marcadores lingüísticos (mismos 7 que en train_baseline.py)
        linguistic_features = np.array([[
            markers.first_person_pronouns,
            markers.negations,
            markers.negative_emotions,
            markers.past_tense,
            markers.isolation_references,
            len(flagged),
            len(text.split()),
        ]])

        # Combinar igual que en entrenamiento
        combined = hstack([tfidf_features, linguistic_features]).tocsr()

        probs = self._rf_model.predict_proba(combined)[0]
        predicted_class = int(np.argmax(probs))
        risk_score = float(probs[1] * 0.5 + probs[2] * 1.0) if len(probs) > 2 else float(probs[1])
        levels = [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]

        return {
            "risk_level": levels[min(predicted_class, 2)],
            "risk_score": round(risk_score, 4),
            "confidence": round(float(max(probs)), 4),
        }

    def _predict_rules(self, markers, flagged: list) -> Dict:
        """
        Clasificador basado en reglas lingüísticas.
        Se usa cuando no hay modelo ML entrenado.
        Pesos basados en evidencia: Zhang et al. (2024), Trifu et al. (2024).
        """
        processor = TextProcessor()
        composite = processor.compute_composite_risk_score(markers, flagged)

        risk_level = self._score_to_level(composite)

        return {
            "risk_level": risk_level,
            "risk_score": round(composite, 4),
            "confidence": round(0.65, 4),  # Confianza más baja para reglas
        }

    def _score_to_level(self, score: float) -> RiskLevel:
        """Convierte score numérico a nivel de riesgo."""
        if score >= settings.RISK_THRESHOLD_HIGH:
            return RiskLevel.HIGH
        elif score >= settings.RISK_THRESHOLD_MEDIUM:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW
