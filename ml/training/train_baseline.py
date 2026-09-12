"""
Script de entrenamiento de modelos baseline (Random Forest, XGBoost).
Usa TF-IDF + marcadores lingüísticos como features.
Uso: python -m ml.training.train_baseline --data_path ml/data/processed/train.csv
"""

import argparse
import os
import json
import numpy as np
import pandas as pd
from datetime import datetime
from loguru import logger

import joblib
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.model_selection import StratifiedKFold, GridSearchCV
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
    roc_auc_score,
)
from imblearn.over_sampling import SMOTE
from imblearn.pipeline import Pipeline as ImbPipeline

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from app.services.nlp.text_processor import TextProcessor


def extract_linguistic_features(texts: list) -> np.ndarray:
    """Extrae features de marcadores lingüísticos para cada texto."""
    processor = TextProcessor()
    features = []
    for text in texts:
        cleaned = processor.clean_text(str(text))
        markers = processor.extract_linguistic_markers(cleaned)
        flagged = processor.detect_high_risk_fragments(cleaned)
        features.append([
            markers.first_person_pronouns,
            markers.negations,
            markers.negative_emotions,
            markers.past_tense,
            markers.isolation_references,
            len(flagged),  # Número de fragmentos de alto riesgo
            len(cleaned.split()),  # Longitud del texto
        ])
    return np.array(features)


def main():
    parser = argparse.ArgumentParser(description="Entrenamiento de modelos baseline")
    parser.add_argument("--data_path", type=str, required=True)
    parser.add_argument("--output_dir", type=str, default="ml/data/models")
    parser.add_argument("--kfold", type=int, default=5)
    args = parser.parse_args()

    # Cargar datos
    df = pd.read_csv(args.data_path)
    logger.info(f"Dataset: {len(df)} muestras")
    logger.info(f"Distribución:\n{df['label'].value_counts()}")

    texts = df["text"].values
    labels = df["label"].values

    # Extraer features lingüísticos
    logger.info("Extrayendo marcadores lingüísticos...")
    linguistic_features = extract_linguistic_features(texts)

    # TF-IDF
    logger.info("Generando TF-IDF...")
    tfidf = TfidfVectorizer(max_features=5000, ngram_range=(1, 2), min_df=2)
    tfidf_features = tfidf.fit_transform(texts)

    # Combinar TF-IDF + marcadores lingüísticos
    from scipy.sparse import hstack
    combined_features = hstack([tfidf_features, linguistic_features]).tocsr()

    # === Modelos a entrenar ===
    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=300,
            max_depth=20,
            min_samples_split=5,
            class_weight="balanced",
            random_state=42,
            n_jobs=-1,
        ),
        "gradient_boosting": GradientBoostingClassifier(
            n_estimators=200,
            max_depth=5,
            learning_rate=0.1,
            random_state=42,
        ),
    }

    # === Validación cruzada ===
    skf = StratifiedKFold(n_splits=args.kfold, shuffle=True, random_state=42)
    results = {}

    for model_name, model in models.items():
        logger.info(f"\n=== Entrenando {model_name} ===")
        fold_f1s = []
        fold_aucs = []

        for fold, (train_idx, val_idx) in enumerate(skf.split(combined_features, labels)):
            X_train = combined_features[train_idx]
            y_train = labels[train_idx]
            X_val = combined_features[val_idx]
            y_val = labels[val_idx]

            # SMOTE para balancear clases
            smote = SMOTE(random_state=42)
            X_train_balanced, y_train_balanced = smote.fit_resample(X_train, y_train)

            # Entrenar
            model.fit(X_train_balanced, y_train_balanced)
            y_pred = model.predict(X_val)
            y_proba = model.predict_proba(X_val)

            f1 = f1_score(y_val, y_pred, average="weighted")
            try:
                auc = roc_auc_score(y_val, y_proba, multi_class="ovr")
            except ValueError:
                auc = 0.0

            fold_f1s.append(f1)
            fold_aucs.append(auc)
            logger.info(f"  Fold {fold+1}: F1={f1:.4f}, AUC={auc:.4f}")

        avg_f1 = np.mean(fold_f1s)
        std_f1 = np.std(fold_f1s)
        avg_auc = np.mean(fold_aucs)

        results[model_name] = {
            "avg_f1": round(avg_f1, 4),
            "std_f1": round(std_f1, 4),
            "avg_auc": round(avg_auc, 4),
        }
        logger.info(f"{model_name}: F1={avg_f1:.4f} ± {std_f1:.4f}, AUC={avg_auc:.4f}")

    # === Entrenar modelo final con TODOS los datos ===
    best_model_name = max(results, key=lambda k: results[k]["avg_f1"])
    logger.info(f"\nMejor modelo: {best_model_name}")

    best_model = models[best_model_name]
    smote = SMOTE(random_state=42)
    X_balanced, y_balanced = smote.fit_resample(combined_features, labels)
    best_model.fit(X_balanced, y_balanced)

    # Guardar modelo y vectorizador
    os.makedirs(args.output_dir, exist_ok=True)
    joblib.dump(best_model, os.path.join(args.output_dir, "random_forest.pkl"))
    joblib.dump(tfidf, os.path.join(args.output_dir, "tfidf_vectorizer.pkl"))

    # Guardar reporte
    report = {
        "best_model": best_model_name,
        "results": results,
        "kfold": args.kfold,
        "total_samples": len(df),
        "tfidf_features": tfidf.max_features,
        "linguistic_features": 7,
        "timestamp": datetime.now().isoformat(),
    }
    with open(os.path.join(args.output_dir, "baseline_report.json"), "w") as f:
        json.dump(report, f, indent=2)

    logger.info(f"Modelo guardado en {args.output_dir}")


if __name__ == "__main__":
    main()
