from fastapi import APIRouter, Depends, Query, HTTPException, status, Body
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.schemas.analysis import RiskLevel
from app.db.postgresql import get_session
from app.services.alert_service import AlertService

router = APIRouter()


class AlertOut(BaseModel):
    id: str
    student_id: str
    student_name: str | None
    course_id: str | None
    course_name: str | None
    risk_level: str
    risk_score: float
    confidence: float
    text_fragment: str
    source: str
    status: str
    created_at: str
    notes: list = []


class NoteInput(BaseModel):
    content: str


class MessageInput(BaseModel):
    content: str
    template: str | None = None  # "meeting" para citar, None = mensaje libre


class RiskValidationInput(BaseModel):
    """Decisión del psicólogo sobre el nivel que calculó el modelo."""

    decision: str  # "confirmado" | "ajustado"
    nivel_ajustado: str | None = None  # obligatorio si decision="ajustado"
    motivo: str | None = None


class ReportInput(BaseModel):
    """Informe de evaluación psicológica del estudiante."""

    contenido: str
    derivacion: str | None = None
    comunicado_al_estudiante: bool = False


@router.get("/", response_model=List[AlertOut])
async def get_alerts(
    risk_level: Optional[RiskLevel] = None,
    alert_status: Optional[str] = Query(None, alias="status"),
    student_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
):
    """Lista alertas con filtros opcionales."""
    service = AlertService(session)
    alerts = await service.get_alerts(
        risk_level=risk_level.value if risk_level else None,
        status=alert_status,
        student_id=student_id,
        limit=limit,
        offset=offset,
    )
    result = []
    for a in alerts:
        notes = await service.get_notes(a.id)
        result.append(AlertOut(
            id=a.id,
            student_id=a.student_id,
            student_name=a.student_name,
            course_id=a.course_id,
            course_name=a.course_name,
            risk_level=a.risk_level.value,
            risk_score=a.risk_score,
            confidence=a.confidence,
            text_fragment=a.text_fragment,
            source=a.source,
            status=a.status.value,
            created_at=a.created_at.isoformat(),
            notes=[{"author": n.author_name, "content": n.content, "date": n.created_at.isoformat()} for n in notes],
        ))
    return result


@router.get("/statistics")
async def get_alert_statistics(
    session: AsyncSession = Depends(get_session),
):
    """Estadísticas de alertas para el dashboard."""
    service = AlertService(session)
    return await service.get_statistics()


@router.get("/{alert_id}", response_model=AlertOut)
async def get_alert_detail(
    alert_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Detalle de una alerta específica."""
    service = AlertService(session)
    alert = await service.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    notes = await service.get_notes(alert_id)
    return AlertOut(
        id=alert.id,
        student_id=alert.student_id,
        student_name=alert.student_name,
        course_id=alert.course_id,
        course_name=alert.course_name,
        risk_level=alert.risk_level.value,
        risk_score=alert.risk_score,
        confidence=alert.confidence,
        text_fragment=alert.text_fragment,
        source=alert.source,
        status=alert.status.value,
        created_at=alert.created_at.isoformat(),
        notes=[{"author": n.author_name, "content": n.content, "date": n.created_at.isoformat()} for n in notes],
    )


@router.patch("/{alert_id}/status")
async def update_alert_status(
    alert_id: str,
    new_status: str = Query(..., description="pendiente, revisada, en_seguimiento, resuelta"),
    session: AsyncSession = Depends(get_session),
):
    """Actualiza el estado de una alerta."""
    service = AlertService(session)
    alert = await service.update_status(alert_id, new_status)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return {"id": alert.id, "status": alert.status.value, "updated": True}


@router.post("/{alert_id}/notes")
async def add_note_to_alert(
    alert_id: str,
    note_input: NoteInput,
    session: AsyncSession = Depends(get_session),
):
    """Agrega una nota del psicólogo a una alerta."""
    service = AlertService(session)
    alert = await service.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    note = await service.add_note(
        alert_id=alert_id,
        author_id="system",
        author_name="Psicólogo",
        content=note_input.content,
    )
    return {"id": note.id, "alert_id": alert_id, "created": True}


# Plantilla fija para citar al alumno a una reunión (evita que el
# psicólogo tenga que redactarla en la demo).
_MEETING_TEMPLATE = (
    "Hola, te escribo desde el Panel Psicológico de la universidad. "
    "Hemos identificado en tu actividad reciente en el aula virtual "
    "algunas señales que nos gustaría conversar contigo, con total "
    "confidencialidad.\n\n"
    "Por favor, coordinemos una reunión breve esta semana. Puedes "
    "responder este mensaje con los horarios en los que te acomoda "
    "(mañana o tarde) y te confirmo la cita.\n\n"
    "Gracias por tu tiempo. Estamos aquí para acompañarte."
)


@router.post("/{alert_id}/send-message")
async def send_message_to_student(
    alert_id: str,
    payload: MessageInput,
    session: AsyncSession = Depends(get_session),
):
    """
    Envía un mensaje directo del admin (via Moodle) al estudiante de
    la alerta.  Con `template="meeting"` se ignora `content` y se envía
    una plantilla fija de citación a reunión.
    """
    from app.services.moodle.client import MoodleClient, MoodleAPIError

    service = AlertService(session)
    alert = await service.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    text = (
        _MEETING_TEMPLATE
        if payload.template == "meeting"
        else payload.content.strip()
    )
    if not text:
        raise HTTPException(status_code=400, detail="Mensaje vacío")

    try:
        student_id_int = int(alert.student_id)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=400,
            detail=f"student_id de la alerta no es numérico: {alert.student_id}",
        )

    client = MoodleClient()
    try:
        result = await client.send_instant_message(student_id_int, text)
    except MoodleAPIError as e:
        raise HTTPException(status_code=502, detail=f"Moodle: {e.message}")

    # Guardar la copia como nota en la alerta (trazabilidad)
    note = await service.add_note(
        alert_id=alert_id,
        author_id="system",
        author_name="Psicólogo — Mensaje enviado",
        content=text,
    )

    return {
        "alert_id": alert_id,
        "sent": True,
        "template": payload.template,
        "moodle_response": result,
        "note_id": note.id,
    }


@router.patch("/{alert_id}/risk-validation")
async def validate_alert_risk(
    alert_id: str,
    payload: RiskValidationInput,
    session: AsyncSession = Depends(get_session),
):
    """Registra si el psicólogo confirma o corrige el nivel que calculó el modelo.

    El campo `risk_level` no se toca nunca: guarda lo que dijo RoBERTa. La
    corrección va aparte, de modo que después se pueda medir cuántas veces
    el criterio clínico coincidió con el automático.
    """
    service = AlertService(session)
    alert = await service.validate_risk(
        alert_id=alert_id,
        decision=payload.decision,
        nivel_ajustado=payload.nivel_ajustado,
        motivo=payload.motivo,
        autor="psicologo",
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    if alert == "invalid":
        raise HTTPException(
            status_code=422,
            detail="Para ajustar el riesgo hay que indicar el nuevo nivel y el motivo",
        )
    return {
        "alert_id": alert.id,
        "riesgo_del_modelo": alert.risk_level.value,
        "decision": alert.risk_validated,
        "nivel_final": (
            alert.risk_level_adjusted.value
            if alert.risk_level_adjusted
            else alert.risk_level.value
        ),
        "motivo": alert.risk_adjust_reason,
    }


@router.post("/{alert_id}/report")
async def create_evaluation_report(
    alert_id: str,
    payload: ReportInput,
    session: AsyncSession = Depends(get_session),
):
    """Registra el informe de evaluación psicológica en el expediente."""
    service = AlertService(session)
    report = await service.create_report(
        alert_id=alert_id,
        contenido=payload.contenido,
        derivacion=payload.derivacion,
        comunicado=payload.comunicado_al_estudiante,
        autor_id="psicologo",
        autor_nombre="Psicólogo institucional",
    )
    if not report:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return {
        "id": report.id,
        "student_id": report.student_id,
        "creado": report.created_at.isoformat(),
        "derivacion": bool(report.referral),
        "comunicado": report.communicated_at is not None,
    }
