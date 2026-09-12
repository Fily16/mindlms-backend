"""Servicio completo de gestión de alertas."""

import uuid
from datetime import datetime, timezone, UTC
from typing import Optional
from sqlalchemy import select, func, desc, case, literal
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.alert import Alert, AlertNote, AlertStatus, RiskLevelDB
from app.db.collections import get_student_profiles_collection


def _utcnow_naive() -> datetime:
    """UTC now sin tzinfo — compatible con columnas TIMESTAMP WITHOUT TIME ZONE."""
    return datetime.now(UTC).replace(tzinfo=None)


class AlertService:

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_alert(
        self,
        student_id: str,
        student_name: str,
        course_id: str,
        course_name: str,
        risk_level: str,
        risk_score: float,
        confidence: float,
        text_fragment: str,
        source: str,
    ) -> Alert:
        alert = Alert(
            id=str(uuid.uuid4()),
            student_id=student_id,
            student_name=student_name,
            course_id=course_id,
            course_name=course_name,
            risk_level=RiskLevelDB(risk_level),
            risk_score=risk_score,
            confidence=confidence,
            text_fragment=text_fragment,
            source=source,
            status=AlertStatus.PENDING,
        )
        self.session.add(alert)
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def get_alerts(
        self,
        risk_level: Optional[str] = None,
        status: Optional[str] = None,
        student_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Alert]:
        query = select(Alert).order_by(desc(Alert.created_at))

        if risk_level:
            query = query.where(Alert.risk_level == RiskLevelDB(risk_level))
        if status:
            query = query.where(Alert.status == AlertStatus(status))
        if student_id:
            query = query.where(Alert.student_id == student_id)

        query = query.offset(offset).limit(limit)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_alert_by_id(self, alert_id: str) -> Alert | None:
        result = await self.session.execute(select(Alert).where(Alert.id == alert_id))
        return result.scalar_one_or_none()

    async def update_status(self, alert_id: str, new_status: str) -> Alert | None:
        alert = await self.get_alert_by_id(alert_id)
        if not alert:
            return None
        alert.status = AlertStatus(new_status)
        alert.updated_at = _utcnow_naive()
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def validate_risk(
        self,
        alert_id: str,
        decision: str,
        nivel_ajustado: str | None,
        motivo: str | None,
        autor: str,
    ):
        """Guarda la decisión del psicólogo sobre el nivel del modelo.

        Devuelve la alerta, None si no existe, o la cadena "invalid" cuando
        se pide ajustar sin decir a qué nivel ni por qué.
        """
        alert = await self.get_alert_by_id(alert_id)
        if not alert:
            return None

        if decision == "ajustado":
            if not nivel_ajustado or not (motivo or "").strip():
                return "invalid"
            alert.risk_level_adjusted = RiskLevelDB(nivel_ajustado)
            alert.risk_adjust_reason = motivo.strip()
        else:
            decision = "confirmado"
            alert.risk_level_adjusted = None
            alert.risk_adjust_reason = None

        alert.risk_validated = decision
        alert.validated_by = autor
        alert.validated_at = _utcnow_naive()
        alert.updated_at = _utcnow_naive()
        await self.session.commit()
        await self.session.refresh(alert)
        return alert

    async def create_report(
        self,
        alert_id: str,
        contenido: str,
        derivacion: str | None,
        comunicado: bool,
        autor_id: str,
        autor_nombre: str,
    ):
        """Registra un informe de evaluación en el expediente del estudiante."""
        from app.models.alert import EvaluationReport

        alert = await self.get_alert_by_id(alert_id)
        if not alert:
            return None

        report = EvaluationReport(
            id=str(uuid.uuid4()),
            student_id=alert.student_id,
            student_name=alert.student_name,
            alert_id=alert.id,
            author_id=autor_id,
            author_name=autor_nombre,
            content=contenido.strip(),
            referral=(derivacion or "").strip() or None,
            communicated_at=_utcnow_naive() if comunicado else None,
            created_at=_utcnow_naive(),
        )
        self.session.add(report)
        await self.session.commit()
        await self.session.refresh(report)
        return report

    async def get_reports_by_student(self, student_id: str) -> list:
        """Expediente del estudiante: sus informes, del más reciente al más antiguo."""
        from app.models.alert import EvaluationReport

        result = await self.session.execute(
            select(EvaluationReport)
            .where(EvaluationReport.student_id == student_id)
            .order_by(desc(EvaluationReport.created_at))
        )
        return list(result.scalars().all())

    async def add_note(
        self, alert_id: str, author_id: str, author_name: str, content: str
    ) -> AlertNote:
        note = AlertNote(
            id=str(uuid.uuid4()),
            alert_id=alert_id,
            author_id=author_id,
            author_name=author_name,
            content=content,
        )
        self.session.add(note)
        await self.session.commit()
        await self.session.refresh(note)
        return note

    async def get_notes(self, alert_id: str) -> list[AlertNote]:
        result = await self.session.execute(
            select(AlertNote).where(AlertNote.alert_id == alert_id).order_by(AlertNote.created_at)
        )
        return list(result.scalars().all())

    async def get_statistics(self) -> dict:
        """Estadísticas de alertas para el dashboard."""
        today = _utcnow_naive().replace(hour=0, minute=0, second=0, microsecond=0)

        # Estudiantes por nivel de riesgo ACTUAL (= nivel máximo de sus
        # alertas), consistente con GET /students/?risk_level= para que
        # los contadores del dashboard coincidan con la lista al filtrar.
        risk_order = case(
            (Alert.risk_level == RiskLevelDB.HIGH, literal(3)),
            (Alert.risk_level == RiskLevelDB.MEDIUM, literal(2)),
            else_=literal(1),
        )
        per_student = (
            select(Alert.student_id, func.max(risk_order).label("max_risk_order"))
            .where(Alert.student_id != "")
            .group_by(Alert.student_id)
            .subquery()
        )
        result = await self.session.execute(
            select(per_student.c.max_risk_order, func.count())
            .group_by(per_student.c.max_risk_order)
        )
        counts_by_order = dict(result.all())
        risk_counts = {
            "alto": counts_by_order.get(3, 0),
            "medio": counts_by_order.get(2, 0),
            "bajo": counts_by_order.get(1, 0),
        }

        # Alertas pendientes
        pending_result = await self.session.execute(
            select(func.count(Alert.id)).where(Alert.status == AlertStatus.PENDING)
        )
        pending_count = pending_result.scalar() or 0

        # Alertas de hoy
        today_result = await self.session.execute(
            select(func.count(Alert.id)).where(Alert.created_at >= today)
        )
        today_count = today_result.scalar() or 0

        # Total de estudiantes únicos
        students_result = await self.session.execute(
            select(func.count(func.distinct(Alert.student_id)))
        )
        total_students = students_result.scalar() or 0

        # Total de alertas (risk_counts ahora cuenta estudiantes, no alertas)
        alerts_result = await self.session.execute(select(func.count(Alert.id)))
        total_alerts = alerts_result.scalar() or 0

        return {
            "total_students": total_students,
            "risk_distribution": risk_counts,
            "alerts_today": today_count,
            "alerts_pending": pending_count,
            "total_alerts": total_alerts,
        }

    async def get_student_profiles_from_alerts(
        self,
        risk_level: Optional[str] = None,
        limit: int = 50,
    ) -> list:
        """
        Genera perfiles de estudiantes a partir de las alertas en PostgreSQL.
        Fallback cuando MongoDB no está disponible.
        """
        # Subconsulta: por cada estudiante, obtener su alerta más reciente
        # y agregar estadísticas
        risk_order = case(
            (Alert.risk_level == RiskLevelDB.HIGH, literal(3)),
            (Alert.risk_level == RiskLevelDB.MEDIUM, literal(2)),
            else_=literal(1),
        )

        query = (
            select(
                Alert.student_id,
                func.max(Alert.student_name).label("student_name"),
                func.max(risk_order).label("max_risk_order"),
                func.count(Alert.id).label("total_alerts"),
                func.max(Alert.risk_score).label("max_risk_score"),
                func.avg(Alert.risk_score).label("avg_risk_score"),
                func.max(Alert.created_at).label("last_alert_at"),
            )
            .where(Alert.student_id != "")
            .group_by(Alert.student_id)
        )

        # El filtro por nivel debe ir en SQL (HAVING), ANTES del limit.
        # Si se filtra en Python después del limit, los niveles bajos
        # desaparecen: el top-N ordenado por riesgo los deja fuera.
        target_order = {"alto": 3, "medio": 2, "bajo": 1}.get(risk_level or "")
        if target_order:
            query = query.having(func.max(risk_order) == literal(target_order))

        query = query.order_by(
            func.max(risk_order).desc(), func.avg(Alert.risk_score).desc()
        ).limit(limit)

        result = await self.session.execute(query)
        rows = result.all()

        profiles = []
        for row in rows:
            # Determinar el nivel de riesgo más alto del estudiante
            if row.max_risk_order == 3:
                level = "alto"
            elif row.max_risk_order == 2:
                level = "medio"
            else:
                level = "bajo"

            profiles.append({
                "student_id": row.student_id,
                "student_name": row.student_name or "",
                "current_risk_level": level,
                "total_alerts": row.total_alerts,
                "max_risk_score": round(float(row.max_risk_score), 4),
                "avg_risk_score": round(float(row.avg_risk_score), 4),
                "last_alert_at": row.last_alert_at.isoformat() if row.last_alert_at else None,
            })

        return profiles
