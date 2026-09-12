from fastapi import APIRouter, Depends, Query
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.postgresql import get_session
from app.services.analysis_service import AnalysisService
from app.services.alert_service import AlertService

router = APIRouter()


@router.get("/")
async def get_students(
    risk_level: Optional[str] = None,
    limit: int = Query(50, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
):
    """Lista perfiles de estudiantes con su nivel de riesgo actual."""
    service = AnalysisService(session)
    profiles = await service.get_all_student_profiles(risk_level=risk_level, limit=limit)

    # Fallback: si MongoDB no devuelve perfiles, generar desde alertas (PostgreSQL)
    if not profiles:
        alert_service = AlertService(session)
        profiles = await alert_service.get_student_profiles_from_alerts(
            risk_level=risk_level, limit=limit
        )

    return profiles


@router.get("/statistics")
async def get_statistics(
    session: AsyncSession = Depends(get_session),
):
    """
    Estadísticas generales para el dashboard.

    La distribución de riesgo cuenta ESTUDIANTES por su nivel actual y
    usa la misma fuente que GET /students/ (MongoDB si hay perfiles,
    fallback PostgreSQL): los contadores coinciden con la lista filtrada.
    """
    alert_service = AlertService(session)
    stats = await alert_service.get_statistics()

    analysis_service = AnalysisService(session)
    mongo_dist = await analysis_service.get_risk_distribution()
    if mongo_dist is not None:
        stats["risk_distribution"] = mongo_dist
        stats["total_students"] = sum(mongo_dist.values())

    return stats


@router.get("/{student_id}/history")
async def get_student_history(
    student_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Historial completo de análisis y alertas de un estudiante."""
    service = AnalysisService(session)
    return await service.get_student_history(student_id)


@router.get("/{student_id}/reports")
async def get_student_reports(
    student_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Expediente del estudiante: informes de evaluación registrados."""
    from app.services.alert_service import AlertService

    service = AlertService(session)
    reports = await service.get_reports_by_student(student_id)
    return [
        {
            "id": r.id,
            "autor": r.author_name,
            "contenido": r.content,
            "derivacion": r.referral,
            "comunicado": r.communicated_at is not None,
            "fecha": r.created_at.isoformat(),
        }
        for r in reports
    ]
