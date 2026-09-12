"""
Servicio orquestador de análisis de texto.
Coordina NLP → ML → Almacenamiento → Alertas.
"""

import hashlib
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.nlp.text_processor import TextProcessor
from app.services.ml.classifier import RiskClassifier
from app.services.alert_service import AlertService
from app.db.collections import get_analyzed_texts_collection, get_student_profiles_collection
from app.core.config import settings


class AnalysisService:

    def __init__(self, session: AsyncSession):
        self.processor = TextProcessor()
        self.classifier = RiskClassifier()
        self.alert_service = AlertService(session)
        self.session = session

    async def analyze_text(
        self,
        text: str,
        student_id: str,
        student_name: str = "",
        source: str = "foro",
        course_id: str = "",
        course_name: str = "",
    ) -> dict:
        """Pipeline completo de análisis de un texto."""

        # 1. Verificar duplicados por hash
        text_hash = hashlib.sha256(text.encode()).hexdigest()
        texts_col = await get_analyzed_texts_collection()
        if texts_col is not None:
            existing = await texts_col.find_one({"original_hash": text_hash})
            if existing:
                return {
                    "risk_level": existing["risk_level"],
                    "risk_score": existing["risk_score"],
                    "confidence": existing["confidence"],
                    "linguistic_markers": existing["linguistic_markers"],
                    "flagged_fragments": existing["flagged_fragments"],
                    "analyzed_at": existing["analyzed_at"],
                    "cached": True,
                }

        # 2. Limpiar y anonimizar texto
        cleaned = self.processor.clean_text(text)
        anonymized = self.processor.anonymize_text(cleaned)

        # 3. Extraer marcadores lingüísticos + palabras exactas
        markers = self.processor.extract_linguistic_markers(cleaned)
        matched_words = self.processor.extract_matched_words(cleaned)

        # 4. Clasificar con modelo ML
        prediction = await self.classifier.predict(cleaned)

        # 5. Guardar resultado en MongoDB
        now = datetime.now(timezone.utc).isoformat()
        doc = {
            "student_id": student_id,
            "original_hash": text_hash,
            "cleaned_text": anonymized,
            "source": source,
            "course_id": course_id,
            "course_name": course_name,
            "linguistic_markers": {
                "first_person_pronouns": markers.first_person_pronouns,
                "negations": markers.negations,
                "negative_emotions": markers.negative_emotions,
                "past_tense": markers.past_tense,
                "isolation_references": markers.isolation_references,
            },
            "risk_level": prediction["risk_level"].value,
            "risk_score": prediction["risk_score"],
            "confidence": prediction["confidence"],
            "model_version": settings.MODEL_NAME,
            "flagged_fragments": prediction.get("flagged_fragments", []),
            "analyzed_at": now,
        }
        if texts_col is not None:
            await texts_col.insert_one(doc)

        # 6. Actualizar perfil del estudiante en MongoDB
        await self._update_student_profile(
            student_id, prediction["risk_level"].value, prediction["risk_score"]
        )

        # 7. Generar alerta para todos los niveles de riesgo
        await self.alert_service.create_alert(
            student_id=student_id,
            student_name=student_name,
            course_id=course_id,
            course_name=course_name,
            risk_level=prediction["risk_level"].value,
            risk_score=prediction["risk_score"],
            confidence=prediction["confidence"],
            text_fragment=anonymized[:500],
            source=source,
        )

        return {
            "risk_level": prediction["risk_level"].value,
            "risk_score": prediction["risk_score"],
            "confidence": prediction["confidence"],
            "linguistic_markers": {
                "first_person_pronouns": markers.first_person_pronouns,
                "negations": markers.negations,
                "negative_emotions": markers.negative_emotions,
                "past_tense": markers.past_tense,
                "isolation_references": markers.isolation_references,
            },
            "matched_words": matched_words,
            "flagged_fragments": prediction.get("flagged_fragments", []),
            "word_count": len(cleaned.split()),
            "char_count": len(cleaned),
            "model_backend": prediction.get("model_backend", "transformer"),
            "analyzed_at": now,
            "cached": False,
        }

    async def _update_student_profile(self, student_id: str, risk_level: str, risk_score: float):
        """Actualiza o crea el perfil de riesgo del estudiante."""
        profiles_col = await get_student_profiles_collection()
        if profiles_col is None:
            return
        now = datetime.now(timezone.utc).isoformat()

        existing = await profiles_col.find_one({"student_id": student_id})
        if existing:
            total = existing["total_analyses"] + 1
            new_avg = (existing["avg_risk_score"] * existing["total_analyses"] + risk_score) / total
            trend = existing.get("risk_trend", [])
            trend.append({"date": now, "score": risk_score})
            # Mantener solo los últimos 90 registros
            trend = trend[-90:]

            await profiles_col.update_one(
                {"student_id": student_id},
                {"$set": {
                    "current_risk_level": risk_level,
                    "avg_risk_score": round(new_avg, 4),
                    "total_analyses": total,
                    "risk_trend": trend,
                    "last_analyzed_at": now,
                    "updated_at": now,
                }},
            )
        else:
            await profiles_col.insert_one({
                "student_id": student_id,
                "current_risk_level": risk_level,
                "avg_risk_score": risk_score,
                "total_analyses": 1,
                "total_alerts": 0,
                "risk_trend": [{"date": now, "score": risk_score}],
                "courses": [],
                "last_analyzed_at": now,
                "created_at": now,
                "updated_at": now,
            })

    async def get_student_history(self, student_id: str) -> dict:
        """Historial completo de un estudiante."""
        texts_col = await get_analyzed_texts_collection()
        profiles_col = await get_student_profiles_collection()

        if texts_col is None or profiles_col is None:
            return {
                "student_id": student_id,
                "profile": {"current_risk_level": "bajo", "avg_risk_score": 0, "total_analyses": 0, "risk_trend": []},
                "analyses": [],
            }

        profile = await profiles_col.find_one({"student_id": student_id})
        analyses = await texts_col.find(
            {"student_id": student_id}
        ).sort("analyzed_at", -1).limit(100).to_list(100)

        # Limpiar _id de MongoDB
        for a in analyses:
            a["_id"] = str(a["_id"])

        return {
            "student_id": student_id,
            "profile": {
                "current_risk_level": profile["current_risk_level"] if profile else "bajo",
                "avg_risk_score": profile["avg_risk_score"] if profile else 0,
                "total_analyses": profile["total_analyses"] if profile else 0,
                "risk_trend": profile.get("risk_trend", []) if profile else [],
            },
            "analyses": analyses,
        }

    async def get_all_student_profiles(
        self, risk_level: Optional[str] = None, limit: int = 50
    ) -> list:
        """Lista todos los perfiles de estudiantes."""
        profiles_col = await get_student_profiles_collection()
        if profiles_col is None:
            return []
        query = {}
        if risk_level:
            query["current_risk_level"] = risk_level
        cursor = profiles_col.find(query).sort("avg_risk_score", -1).limit(limit)
        profiles = await cursor.to_list(limit)
        for p in profiles:
            p["_id"] = str(p["_id"])
        return profiles

    async def get_risk_distribution(self) -> Optional[dict]:
        """
        Cuenta estudiantes por nivel de riesgo actual en MongoDB.
        Devuelve None si MongoDB no está disponible o no hay perfiles,
        para que el caller haga fallback a PostgreSQL (misma regla que
        get_all_student_profiles → la lista y los contadores coinciden).
        """
        profiles_col = await get_student_profiles_collection()
        if profiles_col is None:
            return None
        pipeline = [{"$group": {"_id": "$current_risk_level", "n": {"$sum": 1}}}]
        rows = await profiles_col.aggregate(pipeline).to_list(10)
        if not rows:
            return None
        dist = {"alto": 0, "medio": 0, "bajo": 0}
        for row in rows:
            level = row.get("_id")
            if level in dist:
                dist[level] = row.get("n", 0)
        return dist
