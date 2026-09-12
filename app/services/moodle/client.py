"""
Cliente API para Moodle Web Services.
Se conecta a una instancia de Moodle para extraer textos de foros,
chats y tareas para análisis de salud mental.

Documentación Moodle WS: https://docs.moodle.org/dev/Web_service_API_functions
"""

import httpx
from typing import Optional
from loguru import logger

from app.core.config import settings


class MoodleClient:
    """Cliente async para la API de Moodle Web Services."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        token: Optional[str] = None,
    ):
        self.base_url = (base_url or settings.MOODLE_URL).rstrip("/")
        self.token = token or settings.MOODLE_TOKEN
        self.ws_url = f"{self.base_url}/webservice/rest/server.php"

    @staticmethod
    def _flatten_params(params: dict) -> dict:
        """
        Convierte parámetros con listas/dicts al formato que Moodle espera.
        Moodle requiere arrays indexados: `key[0]=v1&key[1]=v2` en vez de `key=v1&key=v2`.
        Dicts anidados: `key[subkey]=v`.
        """
        flat: dict = {}
        for key, value in params.items():
            if isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        for sub_k, sub_v in item.items():
                            flat[f"{key}[{i}][{sub_k}]"] = sub_v
                    else:
                        flat[f"{key}[{i}]"] = item
            elif isinstance(value, dict):
                for sub_k, sub_v in value.items():
                    flat[f"{key}[{sub_k}]"] = sub_v
            else:
                flat[key] = value
        return flat

    async def _call(self, function: str, **params) -> dict:
        """Llamada genérica a Moodle Web Services."""
        payload = {
            "wstoken": self.token,
            "wsfunction": function,
            "moodlewsrestformat": "json",
            **self._flatten_params(params),
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(self.ws_url, data=payload)
            response.raise_for_status()
            data = response.json()

            if isinstance(data, dict) and "exception" in data:
                logger.error(f"Moodle API error: {data['message']}")
                raise MoodleAPIError(data["message"], data.get("errorcode"))

            return data

    # === Información del sitio ===

    async def get_site_info(self) -> dict:
        """Obtiene información del sitio Moodle."""
        return await self._call("core_webservice_get_site_info")

    # === Cursos ===

    async def get_courses(self) -> list:
        """Lista todos los cursos disponibles."""
        return await self._call("core_course_get_courses")

    async def get_enrolled_users(self, course_id: int) -> list:
        """Lista usuarios inscritos en un curso."""
        return await self._call("core_enrol_get_enrolled_users", courseid=course_id)

    async def get_course_contents(self, course_id: int) -> list:
        """Obtiene el contenido/módulos de un curso."""
        return await self._call("core_course_get_contents", courseid=course_id)

    # === Foros ===

    async def get_forum_discussions(self, forum_id: int) -> dict:
        """Obtiene discusiones de un foro."""
        return await self._call(
            "mod_forum_get_forum_discussions",
            forumid=forum_id,
        )

    async def get_discussion_posts(self, discussion_id: int) -> dict:
        """Obtiene todos los posts de una discusión."""
        return await self._call(
            "mod_forum_get_discussion_posts",
            discussionid=discussion_id,
        )

    async def get_forums_by_course(self, course_id: int) -> list:
        """Lista todos los foros de un curso."""
        return await self._call("mod_forum_get_forums_by_courses", courseids=[course_id])

    # === Chat ===

    async def get_chat_sessions(self, chat_id: int) -> dict:
        """Obtiene sesiones de un chat."""
        return await self._call("mod_chat_get_sessions", chatid=chat_id)

    async def get_chat_messages(self, chat_id: int, session_start: int = 0) -> dict:
        """Obtiene mensajes de una sesión de chat."""
        return await self._call(
            "mod_chat_get_session_messages",
            chatid=chat_id,
            sessionstart=session_start,
        )

    # === Tareas (Assignments) ===

    async def get_assignments(self, course_id: int) -> dict:
        """Obtiene tareas de un curso."""
        return await self._call(
            "mod_assign_get_assignments",
            courseids=[course_id],
        )

    async def get_submissions(self, assignment_id: int) -> dict:
        """Obtiene entregas de una tarea."""
        return await self._call(
            "mod_assign_get_submissions",
            assignmentids=[assignment_id],
        )

    # === Mensajes directos ===

    async def get_user_messages(self, user_id: int, other_user_id: int = 0) -> dict:
        """
        Obtiene mensajes enviados por un usuario.
        Usa core_message_get_messages con useridto/useridfrom.
        """
        return await self._call(
            "core_message_get_messages",
            useridto=other_user_id,
            useridfrom=user_id,
            type="conversations",
        )

    async def send_instant_message(
        self, to_user_id: int, message: str
    ) -> dict:
        """
        Envía un mensaje directo del admin (dueño del token) al usuario
        indicado. Usa el endpoint estándar `core_message_send_instant_messages`.
        """
        return await self._call(
            "core_message_send_instant_messages",
            messages=[{
                "touserid": to_user_id,
                "text": message,
                "textformat": 1,  # 1 = HTML
            }],
        )

    async def get_conversations(self, user_id: int) -> dict:
        """Obtiene las conversaciones de un usuario (Moodle 3.6+)."""
        return await self._call(
            "core_message_get_conversations",
            userid=user_id,
        )

    async def get_conversation_messages(
        self, user_id: int, conversation_id: int, limit: int = 100
    ) -> dict:
        """Obtiene mensajes de una conversación específica (Moodle 3.6+)."""
        return await self._call(
            "core_message_get_conversation_messages",
            currentuserid=user_id,
            convid=conversation_id,
            limitnum=limit,
        )

    # === Utilidades ===

    async def get_user_by_field(self, field: str, value: str) -> list:
        """Busca usuario por campo (email, username, etc.)."""
        return await self._call(
            "core_user_get_users_by_field",
            field=field,
            values=[value],
        )


class MoodleAPIError(Exception):
    """Error de la API de Moodle."""
    def __init__(self, message: str, errorcode: Optional[str] = None):
        self.message = message
        self.errorcode = errorcode
        super().__init__(f"[{errorcode}] {message}")
