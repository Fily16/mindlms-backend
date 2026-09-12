"""
Registra en el checkpoint de detección TODO el contenido actual de Moodle
(sin analizarlo). Se usa una única vez ANTES de sembrar los datos del
formulario de validación.

Porqué: MongoDB (el deduplicador original) no está disponible en este
entorno, y los ~3.000 textos simulados ya generaron sus alertas. Si no
se registran como procesados, la próxima detección los reanalizaría
(duplicando alertas) y, con el ritmo pausado, tardaría días. Tras este
bootstrap, la detección solo procesa contenido NUEVO (p. ej. los datos
reales del formulario).

Los foros se descargan en lotes concurrentes (el extractor normal es
secuencial y tardaría >10 min con ~2.000 discusiones), pero el TEXTO se
procesa con la MISMA limpieza del extractor para que los hashes
coincidan exactamente con los de la detección.

Uso:
    python scripts/bootstrap_detection_checkpoint.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from app.services.moodle.client import MoodleClient
from app.services.moodle.text_extractor import MoodleTextExtractor
from app.services.ml.checkpoint import detection_checkpoint, text_hash

CONCURRENCY = 15  # llamadas simultáneas al Moodle local


async def hash_forum_posts_fast(
    client: MoodleClient, extractor: MoodleTextExtractor, course_id: int
) -> int:
    """Recorre los foros de un curso bajando los posts en lotes
    concurrentes. Aplica el MISMO filtro y limpieza que el extractor."""
    count = 0
    forums = await client.get_forums_by_course(course_id)
    for forum in forums:
        discussions = await client.get_forum_discussions(forum["id"])
        disc_list = discussions.get("discussions", [])
        logger.info(
            f"  Foro '{forum.get('name', '')}': {len(disc_list)} discusiones"
        )

        for i in range(0, len(disc_list), CONCURRENCY):
            chunk = disc_list[i : i + CONCURRENCY]
            results = await asyncio.gather(
                *[
                    client.get_discussion_posts(d["discussion"])
                    for d in chunk
                ],
                return_exceptions=True,
            )
            for res in results:
                if isinstance(res, Exception):
                    logger.warning(f"    discusión fallida: {res}")
                    continue
                for post in res.get("posts", []):
                    text = extractor._clean_html(post.get("message", ""))
                    if len(text.split()) >= 5:  # mismo umbral del extractor
                        detection_checkpoint.add_hash(text_hash(text))
                        count += 1
            if (i // CONCURRENCY) % 10 == 0 and i > 0:
                logger.info(f"    ... {i}/{len(disc_list)} discusiones")
    return count


async def main():
    client = MoodleClient()
    info = await client.get_site_info()
    admin_id = int(info.get("userid", 0))
    logger.info(f"Conectado a Moodle como admin (id={admin_id})")

    extractor = MoodleTextExtractor(client)
    total = 0

    # 1. Mensajes directos (conversaciones del admin) — 1 llamada, rápido
    msgs = await extractor.extract_messages_from_admin_conversations(admin_id)
    for m in msgs:
        detection_checkpoint.add_hash(text_hash(m["text"]))
    total += len(msgs)
    detection_checkpoint.flush()
    logger.info(f"Mensajes directos registrados: {len(msgs)}")

    # 2. Foros (concurrente) + chats y tareas (pocos, secuencial)
    courses = await client.get_courses()
    for course in courses:
        cid = course.get("id")
        cname = course.get("fullname", cid)
        logger.info(f"Curso '{cname}'...")
        n = await hash_forum_posts_fast(client, extractor, cid)

        extra = []
        extra.extend(await extractor.extract_chat_texts(cid))
        extra.extend(await extractor.extract_assignment_texts(cid))
        for entry in extra:
            detection_checkpoint.add_hash(text_hash(entry["text"]))

        total += n + len(extra)
        detection_checkpoint.flush()  # progreso a disco tras cada curso
        logger.info(f"Curso '{cname}': {n + len(extra)} textos registrados")

    detection_checkpoint.set_state("completed")
    logger.success(
        f"[OK] Checkpoint inicializado con {detection_checkpoint.processed_count} "
        f"hashes ({total} textos vistos). La próxima detección solo "
        f"procesará contenido nuevo."
    )


if __name__ == "__main__":
    asyncio.run(main())
