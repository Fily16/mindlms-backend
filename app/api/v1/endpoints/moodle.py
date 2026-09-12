"""
Endpoints para integración con Moodle LMS.
- Sincronización de cursos
- Recepción de webhooks
- Consulta de cursos
"""

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.postgresql import get_session
from app.services.moodle.sync_service import MoodleSyncService
from app.services.moodle.webhook_handler import MoodleWebhookHandler

router = APIRouter()


@router.get("/courses")
async def list_moodle_courses(
    session: AsyncSession = Depends(get_session),
):
    """Lista cursos disponibles en Moodle."""
    service = MoodleSyncService(session)
    try:
        courses = await service.get_moodle_courses()
        return {"courses": courses}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Error conectando con Moodle: {str(e)}")


@router.post("/courses/{course_id}/sync")
async def sync_course(
    course_id: int,
    source: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """
    Sincroniza textos de un curso de Moodle y ejecuta análisis.
    - source: 'foro', 'tarea', o None para todo.
    """
    service = MoodleSyncService(session)
    try:
        if source == "foro":
            result = await service.sync_forum_only(course_id)
        elif source == "tarea":
            result = await service.sync_assignments_only(course_id)
        else:
            result = await service.sync_course(course_id)
        return result
    except Exception as e:
        logger.error(f"Error sincronizando curso {course_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Error en sincronización: {str(e)}")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    x_moodle_signature: Optional[str] = Header(None),
    session: AsyncSession = Depends(get_session),
):
    """
    Recibe webhooks de Moodle para procesamiento en tiempo real.
    Moodle envía eventos cuando se crean posts, mensajes, entregas, etc.
    """
    body = await request.body()
    handler = MoodleWebhookHandler()

    if x_moodle_signature:
        if not handler.validate_webhook(body, x_moodle_signature):
            raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    try:
        event_data = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    parsed = handler.parse_event(event_data)
    if not parsed or not handler.should_analyze(parsed):
        return {"status": "ignored", "reason": "Evento no relevante para análisis"}

    service = MoodleSyncService(session)
    result = await service.process_webhook_event(parsed)

    if result:
        return {
            "status": "analyzed",
            "risk_level": result.get("risk_level"),
            "risk_score": result.get("risk_score"),
            "alert_generated": result.get("risk_level") in ("medio", "alto"),
        }

    return {"status": "error", "message": "No se pudo procesar el evento"}
