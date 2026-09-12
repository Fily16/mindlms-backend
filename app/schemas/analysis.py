from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime
from enum import Enum


class RiskLevel(str, Enum):
    LOW = "bajo"
    MEDIUM = "medio"
    HIGH = "alto"


class TextAnalysisRequest(BaseModel):
    text: str = Field(..., min_length=10, max_length=5000, description="Texto a analizar")
    source: Optional[str] = Field(None, description="Origen: foro, chat, tarea")
    course_id: Optional[str] = Field(None, description="ID del curso en el LMS")


class LinguisticMarkers(BaseModel):
    first_person_pronouns: float = Field(description="Frecuencia de pronombres primera persona")
    negations: float = Field(description="Frecuencia de negaciones")
    negative_emotions: float = Field(description="Score de emociones negativas")
    past_tense: float = Field(description="Frecuencia de tiempo pasado")
    isolation_references: float = Field(description="Referencias a aislamiento")


class TextAnalysisResponse(BaseModel):
    risk_level: RiskLevel
    risk_score: float = Field(ge=0.0, le=1.0, description="Score de riesgo 0-1")
    confidence: float = Field(ge=0.0, le=1.0, description="Confianza del modelo")
    linguistic_markers: LinguisticMarkers
    flagged_fragments: List[str] = Field(description="Fragmentos de texto relevantes")
    analyzed_at: datetime


class AlertCreate(BaseModel):
    student_id: str
    risk_level: RiskLevel
    risk_score: float
    text_fragment: str
    source: str


class AlertResponse(BaseModel):
    id: str
    student_id: str
    risk_level: RiskLevel
    risk_score: float
    text_fragment: str
    source: str
    status: str = "pendiente"
    created_at: datetime
    notes: List[str] = []
