"""
Extractor de textos desde Moodle para análisis de salud mental.
Recopila textos de foros, chats y tareas, los agrupa por estudiante
y los envía al pipeline de análisis.
"""

import re
from typing import Optional
from datetime import datetime, timezone
from loguru import logger

from app.services.moodle.client import MoodleClient, MoodleAPIError


class MoodleTextExtractor:
    """Extrae y estructura textos de Moodle para análisis."""

    def __init__(self, client: Optional[MoodleClient] = None):
        self.client = client or MoodleClient()
        # Evitar extraer mensajes directos duplicados cuando un estudiante
        # está inscrito en múltiples cursos
        self._processed_msg_users: set[int] = set()

    async def extract_forum_texts(
        self, course_id: int, since_ts: int = 0
    ) -> list:
        """Extrae todos los textos de foros de un curso.

        Con since_ts > 0 solo procesa discusiones cuyo timemodified
        (última actividad) sea posterior — así evitamos pedir cientos
        de posts que ya conocemos.
        """
        texts = []
        skipped_discussions = 0
        try:
            forums = await self.client.get_forums_by_course(course_id)
            for forum in forums:
                forum_id = forum["id"]
                forum_name = forum.get("name", "")
                logger.info(f"Procesando foro: {forum_name} (ID: {forum_id})")

                discussions = await self.client.get_forum_discussions(forum_id)
                discussion_list = discussions.get("discussions", [])

                for disc in discussion_list:
                    # Saltar discusiones sin actividad nueva
                    disc_ts = int(
                        disc.get("timemodified") or disc.get("usermodified") or 0
                    )
                    if since_ts and disc_ts and disc_ts <= since_ts:
                        skipped_discussions += 1
                        continue
                    posts = await self.client.get_discussion_posts(disc["discussion"])
                    for post in posts.get("posts", []):
                        text = self._clean_html(post.get("message", ""))
                        if len(text.split()) >= 5:  # Mínimo 5 palabras
                            # Moodle API: datos del autor están en post.author
                            author = post.get("author", {})
                            user_id = str(author.get("id", post.get("userid", "")))
                            user_name = author.get("fullname", post.get("userfullname", ""))
                            texts.append({
                                "text": text,
                                "student_id": user_id,
                                "student_name": user_name,
                                "source": "foro",
                                "source_detail": forum_name,
                                "course_id": str(course_id),
                                "timestamp": datetime.fromtimestamp(
                                    post.get("timecreated", 0), tz=timezone.utc
                                ).isoformat(),
                                "moodle_post_id": post.get("id"),
                            })
        except MoodleAPIError as e:
            logger.error(f"Error extrayendo foros del curso {course_id}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado en foros: {e}")

        logger.info(
            f"Foros curso {course_id}: {len(texts)} textos extraídos"
            f" (saltadas {skipped_discussions} discusiones sin cambios)"
        )
        return texts

    async def extract_chat_texts(
        self, course_id: int, since_ts: int = 0
    ) -> list:
        """Extrae textos de chats de un curso."""
        texts = []
        try:
            contents = await self.client.get_course_contents(course_id)
            for section in contents:
                for module in section.get("modules", []):
                    if module.get("modname") != "chat":
                        continue

                    chat_id = module["instance"]
                    chat_name = module.get("name", "")
                    logger.info(f"Procesando chat: {chat_name} (ID: {chat_id})")

                    sessions = await self.client.get_chat_sessions(chat_id)
                    for session in sessions.get("sessions", []):
                        session_end = int(
                            session.get("sessionend")
                            or session.get("sessionstart", 0)
                        )
                        # Saltar sesiones cerradas antes del último scan
                        if since_ts and session_end and session_end <= since_ts:
                            continue
                        messages = await self.client.get_chat_messages(
                            chat_id, session.get("sessionstart", 0)
                        )
                        # Agrupar mensajes consecutivos del mismo usuario
                        grouped = self._group_consecutive_messages(
                            messages.get("messages", [])
                        )
                        for group in grouped:
                            if len(group["text"].split()) >= 5:
                                texts.append({
                                    "text": group["text"],
                                    "student_id": str(group["userid"]),
                                    "student_name": "",
                                    "source": "chat",
                                    "source_detail": chat_name,
                                    "course_id": str(course_id),
                                    "timestamp": group["timestamp"],
                                })
        except MoodleAPIError as e:
            logger.error(f"Error extrayendo chats del curso {course_id}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado en chats: {e}")

        logger.info(f"Chats curso {course_id}: {len(texts)} textos extraídos")
        return texts

    async def extract_assignment_texts(
        self, course_id: int, since_ts: int = 0
    ) -> list:
        """Extrae textos de entregas de tareas."""
        texts = []
        try:
            result = await self.client.get_assignments(course_id)
            courses = result.get("courses", [])
            for course in courses:
                for assignment in course.get("assignments", []):
                    assign_id = assignment["id"]
                    assign_name = assignment.get("name", "")
                    logger.info(f"Procesando tarea: {assign_name} (ID: {assign_id})")

                    subs = await self.client.get_submissions(assign_id)
                    for sub in subs.get("assignments", [{}])[0].get("submissions", []):
                        # Saltar entregas sin cambios
                        sub_ts = int(sub.get("timemodified") or 0)
                        if since_ts and sub_ts and sub_ts <= since_ts:
                            continue
                        # Extraer texto online
                        for plugin in sub.get("plugins", []):
                            if plugin.get("type") == "onlinetext":
                                for area in plugin.get("editorfields", []):
                                    raw_text = area.get("text", "")
                                    text = self._clean_html(raw_text)
                                    if len(text.split()) >= 10:
                                        texts.append({
                                            "text": text,
                                            "student_id": str(sub.get("userid", "")),
                                            "student_name": "",
                                            "source": "tarea",
                                            "source_detail": assign_name,
                                            "course_id": str(course_id),
                                            "timestamp": datetime.fromtimestamp(
                                                sub.get("timemodified", 0),
                                                tz=timezone.utc,
                                            ).isoformat(),
                                        })
        except MoodleAPIError as e:
            logger.error(f"Error extrayendo tareas del curso {course_id}: {e}")
        except Exception as e:
            logger.error(f"Error inesperado en tareas: {e}")

        logger.info(f"Tareas curso {course_id}: {len(texts)} textos extraídos")
        return texts

    async def extract_direct_messages(self, course_id: int) -> list:
        """
        Extrae mensajes directos de los estudiantes inscritos en un curso.
        Los mensajes directos son del sistema de mensajería de Moodle
        (core_message), NO de foros ni chats de módulo.
        """
        texts = []
        try:
            enrolled = await self.client.get_enrolled_users(course_id)

            # Filtrar: solo usuarios con rol "student" en este curso
            students = [
                u for u in enrolled
                if any(
                    r.get("shortname") == "student"
                    for r in u.get("roles", [])
                )
            ]

            if not students:
                logger.info(
                    f"Curso {course_id}: sin estudiantes para mensajes directos"
                )
                return texts

            logger.info(
                f"Curso {course_id}: extrayendo mensajes directos de "
                f"{len(students)} estudiantes..."
            )

            for i, student in enumerate(students):
                user_id = student["id"]
                user_name = student.get("fullname", "")

                # Evitar procesar el mismo estudiante de otro curso
                if user_id in self._processed_msg_users:
                    continue
                self._processed_msg_users.add(user_id)

                try:
                    # Intentar API moderna (Moodle 3.6+): conversaciones
                    msgs = await self._extract_user_conversations(
                        user_id, user_name, course_id
                    )
                    texts.extend(msgs)
                except MoodleAPIError:
                    # Fallback: API legacy core_message_get_messages
                    try:
                        msgs = await self._extract_user_messages_legacy(
                            user_id, user_name, course_id
                        )
                        texts.extend(msgs)
                    except MoodleAPIError as e2:
                        logger.warning(
                            f"No se pudieron obtener mensajes del "
                            f"estudiante {user_id} ({user_name}): {e2}"
                        )
                except Exception as e:
                    logger.warning(
                        f"Error mensajes estudiante {user_id}: {e}"
                    )

                if (i + 1) % 50 == 0:
                    logger.info(
                        f"  Mensajes directos: {i + 1}/{len(students)} "
                        f"estudiantes, {len(texts)} textos"
                    )

        except MoodleAPIError as e:
            logger.error(
                f"Error obteniendo usuarios del curso {course_id}: {e}"
            )
        except Exception as e:
            logger.error(f"Error inesperado en mensajes directos: {e}")

        logger.info(
            f"Mensajes directos curso {course_id}: "
            f"{len(texts)} textos extraídos"
        )
        return texts

    async def extract_messages_from_admin_conversations(
        self, admin_user_id: int
    ) -> list:
        """
        Extrae mensajes desde las conversaciones del administrador.

        En Moodle, los mensajes generados por el sistema/script usan la
        cuenta admin como remitente.  Cada conversación 1-a-1 del admin
        tiene como miembro al estudiante destino.  Este método lee esas
        conversaciones y atribuye el texto al estudiante miembro,
        permitiendo analizarlos como textos estudiantiles.

        Retorna una lista de dicts con la misma estructura que los demás
        extractores (text, student_id, student_name, source, …).
        """
        texts: list = []
        try:
            convs_data = await self.client.get_conversations(admin_user_id)

            if isinstance(convs_data, dict):
                conversations = convs_data.get("conversations", [])
            elif isinstance(convs_data, list):
                conversations = convs_data
            else:
                return texts

            logger.info(
                f"Admin tiene {len(conversations)} conversaciones "
                f"— extrayendo mensajes..."
            )

            for conv in conversations:
                # Solo conversaciones 1-a-1 (type=1)
                if conv.get("type") != 1:
                    continue

                members = conv.get("members", [])
                if not members:
                    continue

                # El miembro es el estudiante (el otro participante)
                student = members[0]
                student_id = student.get("id")
                student_name = student.get("fullname", "")

                if not student_id:
                    continue

                # Evitar duplicados si el mismo estudiante aparece
                # en varias conversaciones
                if student_id in self._processed_msg_users:
                    continue
                self._processed_msg_users.add(student_id)

                # Extraer mensajes inline de la conversación
                for msg in conv.get("messages", []):
                    raw_text = msg.get("text", "")
                    text = self._clean_html(raw_text)

                    # Remover tags tipo [@username] al inicio
                    text = re.sub(r"^\[@\w+\]\s*", "", text).strip()

                    # Marcador de datos reales del formulario de validación:
                    # el seeder antepone [VALIDACION] al texto. Se quita del
                    # texto (no debe influir en el análisis) y se etiqueta
                    # la fuente para que el dashboard muestre "DATOS REALES".
                    is_validation = text.startswith("[VALIDACION]")
                    if is_validation:
                        text = text[len("[VALIDACION]"):].strip()

                    if len(text.split()) < 5:
                        continue

                    texts.append({
                        "text": text,
                        "student_id": str(student_id),
                        "student_name": student_name,
                        "source": (
                            "formulario_validacion"
                            if is_validation
                            else "mensaje_directo"
                        ),
                        "source_detail": (
                            "Formulario de validación (datos reales)"
                            if is_validation
                            else f"Conversación con {student_name}"
                        ),
                        "course_id": "",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    })

        except MoodleAPIError as e:
            logger.error(f"Error extrayendo conversaciones del admin: {e}")
        except Exception as e:
            logger.error(
                f"Error inesperado en conversaciones del admin: {e}"
            )

        logger.info(
            f"Conversaciones del admin: {len(texts)} textos de "
            f"estudiantes extraídos"
        )
        return texts

    async def _extract_user_conversations(
        self, user_id: int, user_name: str, course_id: int
    ) -> list:
        """Extrae mensajes usando la API de conversaciones (Moodle 3.6+)."""
        texts = []
        convs_data = await self.client.get_conversations(user_id)

        # La respuesta puede ser una lista directa o un dict con clave "conversations"
        if isinstance(convs_data, dict):
            conversations = convs_data.get("conversations", [])
        elif isinstance(convs_data, list):
            conversations = convs_data
        else:
            return texts

        for conv in conversations:
            conv_id = conv.get("id")
            if not conv_id:
                continue

            try:
                msg_data = await self.client.get_conversation_messages(
                    user_id, conv_id
                )
                messages = msg_data.get("messages", [])

                for msg in messages:
                    # Solo mensajes ENVIADOS por el estudiante
                    if msg.get("useridfrom") != user_id:
                        continue

                    text = self._clean_html(msg.get("text", ""))
                    if len(text.split()) >= 5:
                        texts.append({
                            "text": text,
                            "student_id": str(user_id),
                            "student_name": user_name,
                            "source": "mensaje_directo",
                            "source_detail": self._get_conv_detail(conv),
                            "course_id": str(course_id),
                            "timestamp": datetime.fromtimestamp(
                                msg.get("timecreated", 0), tz=timezone.utc
                            ).isoformat(),
                        })
            except Exception as e:
                logger.debug(
                    f"Error en conversación {conv_id} de usuario {user_id}: {e}"
                )

        return texts

    async def _extract_user_messages_legacy(
        self, user_id: int, user_name: str, course_id: int
    ) -> list:
        """Extrae mensajes usando la API legacy core_message_get_messages."""
        texts = []
        result = await self.client.get_user_messages(user_id)
        messages = result.get("messages", [])

        for msg in messages:
            # Solo mensajes ENVIADOS por el estudiante
            if msg.get("useridfrom") != user_id:
                continue

            raw_text = (
                msg.get("text", "")
                or msg.get("fullmessagehtml", "")
                or msg.get("smallmessage", "")
            )
            text = self._clean_html(raw_text)
            if len(text.split()) >= 5:
                texts.append({
                    "text": text,
                    "student_id": str(user_id),
                    "student_name": msg.get("userfromfullname", user_name),
                    "source": "mensaje_directo",
                    "source_detail": (
                        f"Mensaje a {msg.get('usertofullname', 'usuario')}"
                    ),
                    "course_id": str(course_id),
                    "timestamp": datetime.fromtimestamp(
                        msg.get("timecreated", 0), tz=timezone.utc
                    ).isoformat(),
                })

        return texts

    def _get_conv_detail(self, conv: dict) -> str:
        """Obtiene descripción de una conversación para el campo source_detail."""
        members = conv.get("members", [])
        if members:
            names = [m.get("fullname", "?") for m in members[:2]]
            return f"Conversación con {', '.join(names)}"
        return "Mensaje directo"

    async def extract_all_texts(self, course_id: int) -> list:
        """Extrae textos de todas las fuentes de un curso."""
        all_texts = []
        all_texts.extend(await self.extract_forum_texts(course_id))
        all_texts.extend(await self.extract_chat_texts(course_id))
        all_texts.extend(await self.extract_assignment_texts(course_id))
        all_texts.extend(await self.extract_direct_messages(course_id))

        logger.info(f"Total textos curso {course_id}: {len(all_texts)}")
        return all_texts

    async def extract_course_texts_for_students(self, course_id: int) -> dict:
        """Extrae y agrupa textos por estudiante."""
        all_texts = await self.extract_all_texts(course_id)
        by_student = {}
        for entry in all_texts:
            sid = entry["student_id"]
            if sid not in by_student:
                by_student[sid] = []
            by_student[sid].append(entry)
        return by_student

    # === Utilidades ===

    def _clean_html(self, html: str) -> str:
        """Remueve tags HTML y decodifica entidades."""
        text = re.sub(r"<br\s*/?>", " ", html)
        text = re.sub(r"<[^>]+>", "", text)
        text = re.sub(r"&nbsp;", " ", text)
        text = re.sub(r"&amp;", "&", text)
        text = re.sub(r"&lt;", "<", text)
        text = re.sub(r"&gt;", ">", text)
        text = re.sub(r"&quot;", '"', text)
        text = re.sub(r"&#\d+;", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _group_consecutive_messages(self, messages: list) -> list:
        """Agrupa mensajes consecutivos del mismo usuario en chats."""
        if not messages:
            return []

        grouped = []
        current = {
            "userid": messages[0].get("userid"),
            "text": self._clean_html(messages[0].get("message", "")),
            "timestamp": datetime.fromtimestamp(
                messages[0].get("timestamp", 0), tz=timezone.utc
            ).isoformat(),
        }

        for msg in messages[1:]:
            uid = msg.get("userid")
            text = self._clean_html(msg.get("message", ""))
            if uid == current["userid"]:
                current["text"] += " " + text
            else:
                grouped.append(current)
                current = {
                    "userid": uid,
                    "text": text,
                    "timestamp": datetime.fromtimestamp(
                        msg.get("timestamp", 0), tz=timezone.utc
                    ).isoformat(),
                }

        grouped.append(current)
        return grouped
