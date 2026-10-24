import unicodedata
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query, HTTPException, status, Body
from typing import Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.schemas.analysis import RiskLevel
from app.db.postgresql import get_session
from app.services.alert_service import AlertService
from app.services.nlp.text_processor import TextProcessor
from app.core.security import get_current_user
from app.models.alert import AlertStatus

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
    # Fecha del último cambio (estado, validación...) — HU0022
    updated_at: str | None = None
    # Validación clínica del nivel calculado por el modelo (HU0026 / HU0027)
    risk_validated: str | None = None
    risk_level_adjusted: str | None = None
    risk_adjust_reason: str | None = None
    validated_at: str | None = None
    # Psicólogo que asumió el caso con "Atender este caso" (HU0015)
    assigned_to: str | None = None
    # Solo en el detalle: historial de estados y marcadores lingüísticos
    status_history: list = []
    linguistic_evidence: dict | None = None


_ESTADOS_VALIDOS = {s.value for s in AlertStatus}
_processor = TextProcessor()


def _iso(dt) -> str | None:
    return dt.isoformat() if dt else None


def _evidencia(texto: str) -> dict:
    """Marcadores lingüísticos del texto de la alerta (HU0025).

    Se recalculan con el mismo TextProcessor del pipeline sobre el texto
    anonimizado que guarda la alerta: misma regla, sin columnas nuevas.
    """
    texto = texto or ""
    palabras = _processor.extract_matched_words(texto)
    return {
        "marcadores": {
            "pronombres_primera_persona": palabras.get("first_person", []),
            "negaciones": palabras.get("negations", []),
            "emociones_negativas": palabras.get("emotions", []),
            "aislamiento": palabras.get("isolation", []),
            "desesperanza": palabras.get("hopelessness", []),
        },
        "fragmentos_alto_riesgo": _processor.detect_high_risk_fragments(texto),
    }


def _alert_out(a, notes, history=None, detalle: bool = False) -> AlertOut:
    return AlertOut(
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
        updated_at=_iso(a.updated_at),
        risk_validated=a.risk_validated,
        risk_level_adjusted=a.risk_level_adjusted.value if a.risk_level_adjusted else None,
        risk_adjust_reason=a.risk_adjust_reason,
        validated_at=_iso(a.validated_at),
        assigned_to=a.assigned_to,
        status_history=[
            {
                "de": h.from_status.value if h.from_status else None,
                "a": h.to_status.value,
                "por": h.changed_by_name,
                "fecha": h.changed_at.isoformat(),
            }
            for h in (history or [])
        ],
        linguistic_evidence=_evidencia(a.text_fragment) if detalle else None,
    )


async def _nombre_usuario(session: AsyncSession, user: dict) -> str:
    from app.services.user_service import UserService
    u = await UserService(session).get_by_id(user.get("user_id", ""))
    return u.full_name if u else "Psicólogo"


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
    # Fecha en que se comunicaron los resultados (HU0031). Si se marca
    # comunicado y no se envía, se usa la fecha actual.
    fecha_comunicacion: date | None = None


class CommunicationInput(BaseModel):
    """Registro de la comunicación de resultados de un informe (HU0031)."""

    fecha_comunicacion: date | None = None


@router.get("/", response_model=List[AlertOut])
async def get_alerts(
    risk_level: Optional[RiskLevel] = None,
    alert_status: Optional[str] = Query(None, alias="status"),
    student_id: Optional[str] = None,
    limit: int = Query(50, ge=1, le=1000),
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
        result.append(_alert_out(a, notes))
    return result


@router.get("/counts")
async def get_alert_counts(
    risk_level: Optional[RiskLevel] = None,
    alert_status: Optional[str] = Query(None, alias="status"),
    student_id: Optional[str] = None,
    session: AsyncSession = Depends(get_session),
):
    """Cantidad de alertas por nivel y por estado para los filtros (HU0020)."""
    if alert_status and alert_status not in _ESTADOS_VALIDOS:
        raise HTTPException(status_code=422, detail="Estado de alerta no válido")
    return await AlertService(session).get_counts(
        risk_level=risk_level.value if risk_level else None,
        status=alert_status,
        student_id=student_id,
    )


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
    history = await service.get_status_history(alert_id)
    return _alert_out(alert, notes, history, detalle=True)


@router.patch("/{alert_id}/status")
async def update_alert_status(
    alert_id: str,
    new_status: str = Query(..., description="pendiente, revisada, en_seguimiento, resuelta"),
    session: AsyncSession = Depends(get_session),
    user: dict = Depends(get_current_user),
):
    """Actualiza el estado de una alerta y registra la fecha del cambio (HU0022)."""
    if new_status not in _ESTADOS_VALIDOS:
        raise HTTPException(
            status_code=422,
            detail="Estado no válido: use pendiente, revisada, en_seguimiento o resuelta",
        )
    service = AlertService(session)
    alert = await service.update_status(
        alert_id, new_status,
        changed_by=user.get("user_id"),
        changed_by_name=await _nombre_usuario(session, user),
    )
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")
    return {
        "id": alert.id,
        "status": alert.status.value,
        "updated": True,
        "updated_at": _iso(alert.updated_at),
    }


@router.post("/{alert_id}/notes")
async def add_note_to_alert(
    alert_id: str,
    note_input: NoteInput,
    session: AsyncSession = Depends(get_session),
    user: dict = Depends(get_current_user),
):
    """Agrega una nota del psicólogo a una alerta (HU0023)."""
    contenido = (note_input.content or "").strip()
    if not contenido:
        raise HTTPException(status_code=422, detail="El contenido de la nota es obligatorio")
    service = AlertService(session)
    alert = await service.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    note = await service.add_note(
        alert_id=alert_id,
        author_id=user.get("user_id") or "system",
        author_name=await _nombre_usuario(session, user),
        content=contenido,
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


def _nombre_normalizado(nombre: str) -> str:
    """Sin tildes, mayúsculas ni espacios de más, para comparar nombres."""
    sin_tildes = unicodedata.normalize("NFKD", nombre or "").encode("ascii", "ignore").decode()
    return " ".join(sin_tildes.lower().split())


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

    # El id de la alerta debe ser el de ese estudiante en ESTE Moodle. Las
    # alertas creadas con otra instalación traen ids que aquí pertenecen a
    # otra persona, y el mensaje le llegaría a quien no corresponde.
    if alert.student_name:
        try:
            usuarios = await client.get_user_by_field("id", str(student_id_int))
        except MoodleAPIError as e:
            raise HTTPException(status_code=502, detail=f"Moodle: {e.message}")
        en_moodle = usuarios[0].get("fullname", "") if usuarios else ""
        if _nombre_normalizado(en_moodle) != _nombre_normalizado(alert.student_name):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"No se envió: en Moodle el id {student_id_int} es "
                    f"{en_moodle or 'un usuario inexistente'}, no "
                    f"{alert.student_name}. Esta alerta viene de otra "
                    f"instalación de Moodle."
                ),
            )

    # Antes de enviar: el aviso de Moodle puede lanzar la detección antes
    # de que esto termine, y el mensaje no debe analizarse como si lo
    # hubiera escrito el estudiante.
    from app.services.ml.checkpoint import detection_checkpoint
    detection_checkpoint.add_panel_message(text)

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
    user: dict = Depends(get_current_user),
):
    """Registra si el psicólogo confirma o corrige el nivel que calculó el modelo.

    El campo `risk_level` no se toca nunca: guarda lo que dijo RoBERTa. La
    corrección va aparte, de modo que después se pueda medir cuántas veces
    el criterio clínico coincidió con el automático.
    """
    if payload.decision not in ("confirmado", "ajustado"):
        raise HTTPException(status_code=422, detail="decision debe ser 'confirmado' o 'ajustado'")
    if payload.nivel_ajustado and payload.nivel_ajustado not in ("bajo", "medio", "alto"):
        raise HTTPException(status_code=422, detail="nivel_ajustado debe ser bajo, medio o alto")
    service = AlertService(session)
    alert = await service.validate_risk(
        alert_id=alert_id,
        decision=payload.decision,
        nivel_ajustado=payload.nivel_ajustado,
        motivo=payload.motivo,
        autor=await _nombre_usuario(session, user),
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
        "validado_por": alert.validated_by,
        "validado_en": _iso(alert.validated_at),
    }


@router.post("/{alert_id}/report")
async def create_evaluation_report(
    alert_id: str,
    payload: ReportInput,
    session: AsyncSession = Depends(get_session),
    user: dict = Depends(get_current_user),
):
    """Registra el informe de evaluación en el expediente (HU0028–HU0031).

    El informe incluye automáticamente la evidencia lingüística de la alerta
    (nivel, score, fragmento anonimizado y marcadores detectados).
    """
    contenido = (payload.contenido or "").strip()
    if not contenido:
        raise HTTPException(status_code=422, detail="El contenido del informe es obligatorio")
    service = AlertService(session)
    alert = await service.get_alert_by_id(alert_id)
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta no encontrada")

    ev = _evidencia(alert.text_fragment)
    marcadores = "; ".join(
        f"{k.replace('_', ' ')}: {', '.join(v)}" for k, v in ev["marcadores"].items() if v
    ) or "sin marcadores detectados"
    evidencia = (
        "\n\n— Evidencia lingüística generada por MindLMS —\n"
        f"Nivel de riesgo (modelo): {alert.risk_level.value} · score {alert.risk_score:.2f}\n"
        f"Fragmento: \"{alert.text_fragment[:300]}\"\n"
        f"Marcadores: {marcadores}"
    )
    fecha = (
        datetime.combine(payload.fecha_comunicacion, datetime.min.time())
        if payload.fecha_comunicacion else None
    )
    report = await service.create_report(
        alert_id=alert_id,
        contenido=contenido + evidencia,
        derivacion=payload.derivacion,
        comunicado=payload.comunicado_al_estudiante,
        autor_id=user.get("user_id") or "psicologo",
        autor_nombre=await _nombre_usuario(session, user),
        fecha_comunicacion=fecha,
    )
    return {
        "id": report.id,
        "student_id": report.student_id,
        "creado": report.created_at.isoformat(),
        "derivacion": bool(report.referral),
        "comunicado": report.communicated_at is not None,
        "fecha_comunicacion": _iso(report.communicated_at),
    }


@router.patch("/reports/{report_id}/communication")
async def register_report_communication(
    report_id: str,
    payload: CommunicationInput,
    session: AsyncSession = Depends(get_session),
):
    """Registra que se comunicaron al estudiante los resultados y el plan de
    seguimiento de un informe ya guardado (HU0031). La fecha es obligatoria."""
    if payload.fecha_comunicacion is None:
        raise HTTPException(status_code=422, detail="La fecha de la comunicación es obligatoria")
    fecha = datetime.combine(payload.fecha_comunicacion, datetime.min.time())
    report = await AlertService(session).register_communication(report_id, fecha)
    if not report:
        raise HTTPException(status_code=404, detail="Informe no encontrado")
    return {
        "id": report.id,
        "comunicado": True,
        "fecha_comunicacion": _iso(report.communicated_at),
    }
