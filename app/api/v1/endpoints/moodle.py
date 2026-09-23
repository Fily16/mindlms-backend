"""
Endpoints para integración con Moodle LMS.
- Sincronización de cursos
- Recepción de webhooks
- Consulta de cursos
"""

import json

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.db.postgresql import get_session
from app.services.moodle.sync_service import MoodleSyncService
from app.services.moodle.webhook_handler import MoodleWebhookHandler
from app.services.ml.task_manager import MLTaskManager

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


@router.post("/webhook", status_code=202)
async def receive_webhook(
    request: Request,
    x_moodle_signature: Optional[str] = Header(None),
):
    """
    Aviso del plugin local_mindlms de Moodle: un estudiante publicó algo.

    El aviso solo trae IDs (Moodle no incluye el texto en sus eventos), así
    que no se analiza aquí: se dispara la misma detección de siempre, que
    lee lo nuevo desde la API de Moodle, deduplica con el checkpoint,
    guarda las alertas y las emite por SSE. Se responde de inmediato para
    que Moodle no haga esperar al estudiante.
    """
    body = await request.body()
    handler = MoodleWebhookHandler()

    # Firma obligatoria: sin ella cualquiera podría disparar detecciones.
    if not x_moodle_signature or not handler.validate_webhook(body, x_moodle_signature):
        raise HTTPException(status_code=401, detail="Firma de webhook inválida")

    try:
        event_name = json.loads(body).get("eventname", "")
    except (ValueError, AttributeError):
        raise HTTPException(status_code=400, detail="Payload JSON inválido")

    if event_name not in handler.SUPPORTED_EVENTS:
        return {"status": "ignored", "event": event_name}

    # Los mensajes directos los cubre el modo quick (1 llamada a Moodle);
    # foros, chats y tareas solo los recorre el modo completo.
    quick = event_name == "\\core\\event\\message_sent"
    status = await MLTaskManager().request_detection(quick=quick)
    logger.info(f"Aviso de Moodle {event_name}: detección {status}")
    return {"status": status, "event": event_name}
