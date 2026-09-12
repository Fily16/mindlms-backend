"""
Endpoints para control del pipeline de ML desde el dashboard.
- Entrenar modelo (baseline o RoBERTa)
- Ejecutar detección sobre textos de Moodle
- Consultar estado de cada proceso
- SSE stream para notificaciones en tiempo real
"""

import asyncio
import json
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional

from app.services.ml.task_manager import MLTaskManager, TaskType
from app.services.ml.events import detection_event_bus

router = APIRouter()


class TrainRequest(BaseModel):
    model_type: str = "baseline"  # "baseline" o "roberta"


# ── Entrenamiento ──────────────────────────────────────────

@router.post("/train")
async def start_training(body: TrainRequest):
    """Inicia el pipeline de entrenamiento en segundo plano."""
    if body.model_type not in ("baseline", "roberta"):
        raise HTTPException(
            status_code=400,
            detail="model_type debe ser 'baseline' o 'roberta'",
        )

    manager = MLTaskManager()

    if manager.is_busy(TaskType.TRAINING):
        raise HTTPException(
            status_code=409,
            detail="Ya hay un entrenamiento en ejecución",
        )

    await manager.start_training(model_type=body.model_type)
    return {"status": "started", "model_type": body.model_type}


@router.get("/train/status")
async def get_training_status():
    """Devuelve el estado actual del entrenamiento (para polling)."""
    manager = MLTaskManager()
    status = manager.get_status(TaskType.TRAINING)
    return status.to_dict()


# ── Detección ──────────────────────────────────────────────

@router.post("/detect")
async def start_detection():
    """Inicia la extracción de textos de Moodle + análisis con el modelo."""
    manager = MLTaskManager()

    if manager.is_busy(TaskType.DETECTION):
        raise HTTPException(
            status_code=409,
            detail="Ya hay una detección en ejecución",
        )

    await manager.start_detection()
    return {"status": "started"}


@router.get("/detect/status")
async def get_detection_status():
    """Devuelve el estado actual de la detección (para polling)."""
    manager = MLTaskManager()
    status = manager.get_status(TaskType.DETECTION)
    return status.to_dict()


@router.post("/detect/reset-timestamp")
async def reset_detection_timestamp(since_ts: int = Query(0)):
    """
    Fuerza el `last_full_scan_ts` del checkpoint al valor dado
    (por defecto 0 = re-escanear todo).  Usado cuando queda contenido
    de Moodle atrapado en el "hueco" temporal del filtro `since_ts`.

    Como el checkpoint es singleton en memoria, esto es la única forma
    de resetearlo sin reiniciar el backend.
    """
    from app.services.ml.checkpoint import detection_checkpoint
    old = detection_checkpoint.last_full_scan_ts
    detection_checkpoint.set_last_full_scan_ts(int(since_ts))
    return {
        "old_ts": old,
        "new_ts": int(since_ts),
        "hashes_count": detection_checkpoint.processed_count,
    }


@router.post("/detect/reload-checkpoint")
async def reload_checkpoint():
    """
    Recarga el checkpoint del disco al singleton en memoria.
    Útil cuando se modifica el JSON del checkpoint externamente
    (por ejemplo para quitar un hash y forzar re-análisis).
    """
    from app.services.ml.checkpoint import detection_checkpoint
    before = detection_checkpoint.processed_count
    before_ts = detection_checkpoint.last_full_scan_ts
    detection_checkpoint._load()
    return {
        "before_hashes": before,
        "after_hashes": detection_checkpoint.processed_count,
        "before_ts": before_ts,
        "after_ts": detection_checkpoint.last_full_scan_ts,
    }


@router.post("/detect/forget-text")
async def forget_text_hash(hash: str = Query(...)):
    """
    Elimina un hash SHA-256 del checkpoint en memoria y disco.
    Permite forzar re-análisis de un texto específico sin borrar
    el resto del checkpoint.
    """
    from app.services.ml.checkpoint import detection_checkpoint
    was_present = hash in detection_checkpoint._hashes
    if was_present:
        detection_checkpoint._hashes.discard(hash)
        detection_checkpoint._save()
    return {
        "hash": hash,
        "was_present": was_present,
        "hashes_count": detection_checkpoint.processed_count,
    }


@router.post("/detect/force-full")
async def force_full_scan():
    """
    Fuerza un full-scan INMEDIATO.  Si hay uno corriendo (quick o full)
    lo cancela primero.  Usado en la demo cuando el psicólogo agrega
    contenido en Moodle y quiere verlo detectado sin esperar el tick
    del auto-scan periódico.
    """
    manager = MLTaskManager()

    if manager.is_busy(TaskType.DETECTION):
        # Esperar a que termine el actual — no lo matamos, solo
        # arrancamos otro apenas se libere el flag
        for _ in range(30):
            await asyncio.sleep(0.5)
            if not manager.is_busy(TaskType.DETECTION):
                break
        else:
            raise HTTPException(
                status_code=409,
                detail="Ya hay una detección en ejecución (timeout esperando)",
            )

    await manager.start_detection(quick=False)
    return {"status": "started", "mode": "FULL"}


# ── SSE: notificaciones en tiempo real ────────────────────

@router.get("/detect/events")
async def detection_events_stream():
    """
    Server-Sent Events — el frontend se conecta aquí y recibe un
    aviso cada vez que se guarda una alerta nueva.  Solo se envía
    datos cuando hay algo nuevo; sin polling innecesario.
    """
    queue = detection_event_bus.subscribe()

    async def event_generator():
        try:
            while True:
                try:
                    # Espera hasta 30s por un evento; si no llega, envía keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive para que el navegador no cierre la conexión
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            detection_event_bus.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
