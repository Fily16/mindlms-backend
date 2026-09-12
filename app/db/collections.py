"""
Colecciones MongoDB para datos textuales y resultados de análisis.

Colecciones:
- analyzed_texts: Textos anonimizados con resultados de análisis
- student_profiles: Perfiles agregados de riesgo por estudiante
- analysis_history: Historial de todos los análisis realizados
"""

from app.db.mongodb import get_database


# === Schemas de documentos MongoDB ===

ANALYZED_TEXT_SCHEMA = {
    "student_id": str,           # ID anonimizado
    "original_hash": str,        # SHA-256 del texto original (para evitar duplicados)
    "cleaned_text": str,         # Texto limpio y anonimizado
    "source": str,               # foro, chat, tarea
    "course_id": str,
    "course_name": str,
    "linguistic_markers": {
        "first_person_pronouns": float,
        "negations": float,
        "negative_emotions": float,
        "past_tense": float,
        "isolation_references": float,
    },
    "risk_level": str,           # bajo, medio, alto
    "risk_score": float,
    "confidence": float,
    "model_version": str,
    "flagged_fragments": list,
    "analyzed_at": str,          # ISO datetime
}

STUDENT_PROFILE_SCHEMA = {
    "student_id": str,
    "current_risk_level": str,
    "avg_risk_score": float,
    "total_analyses": int,
    "total_alerts": int,
    "risk_trend": list,          # [{date, score}] últimos 30 días
    "courses": list,
    "last_analyzed_at": str,
    "created_at": str,
    "updated_at": str,
}


async def get_analyzed_texts_collection():
    db = get_database()
    if db is None:
        return None
    return db["analyzed_texts"]


async def get_student_profiles_collection():
    db = get_database()
    if db is None:
        return None
    return db["student_profiles"]


async def get_analysis_history_collection():
    db = get_database()
    if db is None:
        return None
    return db["analysis_history"]


async def setup_indexes():
    """Crear índices para optimizar consultas."""
    db = get_database()
    if db is None:
        from loguru import logger
        logger.warning("MongoDB no disponible. Saltando creación de índices.")
        return

    # analyzed_texts
    texts = db["analyzed_texts"]
    await texts.create_index("student_id")
    await texts.create_index("risk_level")
    await texts.create_index("analyzed_at")
    await texts.create_index("original_hash", unique=True)
    await texts.create_index([("student_id", 1), ("analyzed_at", -1)])

    # student_profiles
    profiles = db["student_profiles"]
    await profiles.create_index("student_id", unique=True)
    await profiles.create_index("current_risk_level")
    await profiles.create_index("avg_risk_score")

    # analysis_history
    history = db["analysis_history"]
    await history.create_index("analyzed_at")
    await history.create_index("model_version")
