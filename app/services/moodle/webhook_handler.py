"""
Handler de webhooks de Moodle.
Procesa eventos en tiempo real: nuevos posts en foros, mensajes de chat,
entregas de tareas. Moodle envía estos eventos si se configura un
"Event observer" o un plugin de webhook.

Configuración en Moodle: el plugin propio local_mindlms (en el repo
mindlms-backend, deploy/moodle-railway/local_mindlms) observa estos
eventos y envía un POST firmado con HMAC a /api/v1/moodle/webhook.
"""

import hashlib
import hmac
from typing import Optional
from loguru import logger

from app.core.config import settings


class MoodleWebhookHandler:
    """Procesa webhooks/eventos de Moodle."""

    # Eventos que nos interesan para análisis de texto
    SUPPORTED_EVENTS = {
        "\\mod_forum\\event\\discussion_created",
        "\\mod_forum\\event\\post_created",
        "\\mod_forum\\event\\post_updated",
        "\\mod_chat\\event\\message_sent",
        "\\mod_assign\\event\\submission_created",
        "\\mod_assign\\event\\submission_updated",
        "\\core\\event\\message_sent",
    }

    def validate_webhook(self, payload: bytes, signature: str) -> bool:
        """Valida la firma HMAC del webhook."""
        expected = hmac.new(
            settings.MOODLE_WEBHOOK_SECRET.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_event(self, event_data: dict) -> Optional[dict]:
        """
        Parsea un evento de Moodle y extrae la información relevante.
        Retorna None si el evento no es relevante para análisis.
        """
        event_name = event_data.get("eventname", "")

        if event_name not in self.SUPPORTED_EVENTS:
            logger.debug(f"Evento ignorado: {event_name}")
            return None

        # Extraer datos comunes
        parsed = {
            "event_type": event_name,
            "user_id": str(event_data.get("userid", "")),
            "course_id": str(event_data.get("courseid", "")),
            "timestamp": event_data.get("timecreated", 0),
            "context_url": event_data.get("contexturl", ""),
        }

        # Extraer texto según tipo de evento
        other = event_data.get("other", {})

        if "forum" in event_name:
            parsed["source"] = "foro"
            parsed["text"] = other.get("content", "") or other.get("message", "")
            parsed["source_detail"] = other.get("forumname", "")
            parsed["object_id"] = event_data.get("objectid")

        elif "chat" in event_name:
            parsed["source"] = "chat"
            parsed["text"] = other.get("message", "")
            parsed["source_detail"] = "chat"

        elif "assign" in event_name:
            parsed["source"] = "tarea"
            parsed["text"] = other.get("onlinetext", "") or other.get("content", "")
            parsed["source_detail"] = other.get("assignmentname", "")

        elif "message_sent" in event_name:
            parsed["source"] = "mensaje"
            parsed["text"] = other.get("text", "") or other.get("message", "")
            parsed["source_detail"] = "mensaje_directo"

        # Filtrar eventos sin texto significativo
        if not parsed.get("text") or len(parsed["text"].split()) < 5:
            logger.debug(f"Evento {event_name} sin texto suficiente, ignorado")
            return None

        return parsed

    def should_analyze(self, parsed_event: dict) -> bool:
        """Determina si un evento parseado debe ser analizado."""
        if not parsed_event:
            return False

        text = parsed_event.get("text", "")

        # No analizar textos muy cortos
        if len(text.split()) < 5:
            return False

        # No analizar textos que parecen ser solo código o URLs
        code_ratio = sum(1 for c in text if c in "{}()[];=<>") / max(len(text), 1)
        if code_ratio > 0.1:
            return False

        return True
