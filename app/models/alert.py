"""Modelo de alerta en PostgreSQL."""

from sqlalchemy import Column, String, Float, DateTime, Text, Enum as SAEnum, ForeignKey
from sqlalchemy.orm import relationship
from datetime import datetime
import enum

from app.models.user import Base


class AlertStatus(str, enum.Enum):
    PENDING = "pendiente"
    REVIEWED = "revisada"
    FOLLOWING = "en_seguimiento"
    RESOLVED = "resuelta"


class RiskLevelDB(str, enum.Enum):
    LOW = "bajo"
    MEDIUM = "medio"
    HIGH = "alto"


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False, index=True)
    student_name = Column(String, nullable=True)
    course_id = Column(String, nullable=True)
    course_name = Column(String, nullable=True)
    risk_level = Column(SAEnum(RiskLevelDB), nullable=False, index=True)
    risk_score = Column(Float, nullable=False)
    confidence = Column(Float, nullable=False)
    text_fragment = Column(Text, nullable=False)
    source = Column(String, nullable=False)  # foro, chat, tarea
    status = Column(SAEnum(AlertStatus), default=AlertStatus.PENDING, index=True)
    assigned_to = Column(String, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # --- Validación del psicólogo sobre la clasificación automática ---
    # El nivel lo calcula el modelo, pero la decisión clínica es del
    # profesional: puede confirmarlo o corregirlo dejando el motivo.
    # risk_level conserva SIEMPRE lo que dijo el modelo, para poder
    # comparar después el criterio humano contra el automático.
    risk_validated = Column(String, nullable=True)  # "confirmado" | "ajustado"
    risk_level_adjusted = Column(SAEnum(RiskLevelDB), nullable=True)
    risk_adjust_reason = Column(Text, nullable=True)
    validated_by = Column(String, nullable=True)
    validated_at = Column(DateTime, nullable=True)


class EvaluationReport(Base):
    """Informe de evaluación psicológica: el expediente del estudiante.

    Se liga al estudiante y no solo a una alerta, para que el historial se
    lea completo aunque las alertas que lo originaron queden resueltas.
    """

    __tablename__ = "evaluation_reports"

    id = Column(String, primary_key=True)
    student_id = Column(String, nullable=False, index=True)
    student_name = Column(String, nullable=True)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=True, index=True)
    author_id = Column(String, nullable=False)
    author_name = Column(String, nullable=False)
    # Evidencia y conclusión de la evaluación.
    content = Column(Text, nullable=False)
    # Derivación a un especialista externo, cuando el caso lo amerita.
    referral = Column(Text, nullable=True)
    # Marca de que se comunicaron los resultados al estudiante.
    communicated_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class AlertNote(Base):
    __tablename__ = "alert_notes"

    id = Column(String, primary_key=True)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False, index=True)
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    author_name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
