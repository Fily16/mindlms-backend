"""
Servicio de sincronización Moodle → MindLMS.
Orquesta la extracción de textos y el análisis automático.
"""

from typing import Optional
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.moodle.client import MoodleClient
from app.services.moodle.text_extractor import MoodleTextExtractor
from app.services.analysis_service import AnalysisService


class MoodleSyncService:
    """Sincroniza datos de Moodle y ejecuta análisis."""

    def __init__(self, session: AsyncSession, client: Optional[MoodleClient] = None):
        self.client = client or MoodleClient()
        self.extractor = MoodleTextExtractor(self.client)
        self.analysis_service = AnalysisService(session)

    async def sync_course(self, course_id: int) -> dict:
        """
        Sincroniza un curso completo: extrae textos y analiza.
        Retorna resumen con conteos y alertas generadas.
        """
        logger.info(f"Iniciando sincronización del curso {course_id}")

        # Extraer todos los textos del curso
        texts_by_student = await self.extractor.extract_course_texts_for_students(course_id)

        total_texts = 0
        total_analyzed = 0
        total_alerts = 0
        errors = 0

        for student_id, texts in texts_by_student.items():
            for entry in texts:
                total_texts += 1
                try:
                    result = await self.analysis_service.analyze_text(
                        text=entry["text"],
                        student_id=student_id,
                        student_name=entry.get("student_name", ""),
                        source=entry["source"],
                        course_id=str(course_id),
                        course_name=entry.get("source_detail", ""),
                    )
                    total_analyzed += 1
                    if result.get("risk_level") in ("medio", "alto"):
                        total_alerts += 1
                except Exception as e:
                    errors += 1
                    logger.error(f"Error analizando texto de {student_id}: {e}")

        summary = {
            "course_id": course_id,
            "total_students": len(texts_by_student),
            "total_texts": total_texts,
            "total_analyzed": total_analyzed,
            "total_alerts": total_alerts,
            "errors": errors,
        }
        logger.info(f"Sincronización completada: {summary}")
        return summary

    async def sync_forum_only(self, course_id: int) -> dict:
        """Sincroniza solo foros de un curso."""
        texts = await self.extractor.extract_forum_texts(course_id)
        return await self._analyze_texts(texts, course_id, "foro")

    async def sync_assignments_only(self, course_id: int) -> dict:
        """Sincroniza solo tareas de un curso."""
        texts = await self.extractor.extract_assignment_texts(course_id)
        return await self._analyze_texts(texts, course_id, "tarea")

    async def process_webhook_event(self, parsed_event: dict) -> Optional[dict]:
        """Procesa un evento de webhook ya parseado."""
        if not parsed_event or not parsed_event.get("text"):
            return None

        try:
            result = await self.analysis_service.analyze_text(
                text=parsed_event["text"],
                student_id=parsed_event["user_id"],
                source=parsed_event["source"],
                course_id=parsed_event.get("course_id", ""),
                course_name=parsed_event.get("source_detail", ""),
            )
            return result
        except Exception as e:
            logger.error(f"Error procesando webhook: {e}")
            return None

    async def get_moodle_courses(self) -> list:
        """Lista cursos disponibles en Moodle."""
        return await self.client.get_courses()

    async def get_course_students(self, course_id: int) -> list:
        """Lista estudiantes de un curso en Moodle."""
        users = await self.client.get_enrolled_users(course_id)
        return [
            {
                "id": u["id"],
                "username": u.get("username", ""),
                "fullname": u.get("fullname", ""),
                "email": u.get("email", ""),
                "roles": [r["shortname"] for r in u.get("roles", [])],
            }
            for u in users
            if any(r["shortname"] == "student" for r in u.get("roles", []))
        ]

    async def _analyze_texts(self, texts: list, course_id: int, source: str) -> dict:
        """Helper para analizar una lista de textos extraídos."""
        analyzed = 0
        alerts = 0
        errors = 0

        for entry in texts:
            try:
                result = await self.analysis_service.analyze_text(
                    text=entry["text"],
                    student_id=entry["student_id"],
                    student_name=entry.get("student_name", ""),
                    source=source,
                    course_id=str(course_id),
                    course_name=entry.get("source_detail", ""),
                )
                analyzed += 1
                if result.get("risk_level") in ("medio", "alto"):
                    alerts += 1
            except Exception as e:
                errors += 1
                logger.error(f"Error: {e}")

        return {
            "course_id": course_id,
            "source": source,
            "total_texts": len(texts),
            "analyzed": analyzed,
            "alerts": alerts,
            "errors": errors,
        }
