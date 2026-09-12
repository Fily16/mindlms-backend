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


class AlertNote(Base):
    __tablename__ = "alert_notes"

    id = Column(String, primary_key=True)
    alert_id = Column(String, ForeignKey("alerts.id"), nullable=False, index=True)
    author_id = Column(String, ForeignKey("users.id"), nullable=False)
    author_name = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
