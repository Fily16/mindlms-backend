"""
Script para poblar Moodle con datos de prueba simulando actividad estudiantil.
Crea posts en foros con textos que representan distintos niveles de riesgo.
Uso: python scripts/seed_moodle_data.py --url http://localhost:8081 --token TOKEN --forum_id 1
"""

import argparse
import asyncio
import sys
import os
import random

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx
from loguru import logger


# Textos de prueba por nivel de riesgo
TEST_POSTS = {
    "alto": [
        {
            "subject": "No puedo más",
            "message": "Honestamente no sé cómo seguir. La presión de los exámenes finales me tiene al borde. No duermo, no como bien, y siento que nadie entiende lo que estoy pasando. A veces pienso que sería mejor desaparecer y que nadie me necesita realmente.",
        },
        {
            "subject": "Todo mal",
            "message": "Ya no aguanto más la universidad. Cada día es peor, me siento completamente solo y vacío. No vale la pena seguir esforzándome porque nada va a cambiar. Mis padres esperan demasiado de mí y yo solo quiero que pare el dolor.",
        },
    ],
    "medio": [
        {
            "subject": "Estresado con los parciales",
            "message": "Llevo varias semanas sin poder dormir bien por la ansiedad de los exámenes. Me tiemblan las manos antes de cada parcial y me cuesta concentrarme. Siento mucha presión y no sé cómo manejarlo.",
        },
        {
            "subject": "Necesito consejos",
            "message": "Últimamente me siento muy triste y desmotivado con mis estudios. No tengo ganas de ir a clases y me cuesta levantarme por las mañanas. Creo que el estrés me está afectando más de lo que pensaba.",
        },
        {
            "subject": "Problemas para concentrarme",
            "message": "No puedo enfocarme en mis tareas, mi mente está en otro lado constantemente. Tengo mucha angustia sin motivo aparente y me da miedo presentar en público. ¿Alguien más se siente así?",
        },
    ],
    "bajo": [
        {
            "subject": "Buena clase hoy",
            "message": "La clase de hoy estuvo muy interesante. El profesor explicó muy bien el tema de redes neuronales y pude entender todos los conceptos. Estoy motivado para seguir aprendiendo.",
        },
        {
            "subject": "Proyecto grupal avanzando",
            "message": "Nos reunimos con el grupo y avanzamos bastante en el proyecto final. Dividimos las tareas de forma equitativa y todos están comprometidos. Creo que nos va a ir muy bien.",
        },
        {
            "subject": "Aprobé el parcial!",
            "message": "Acabo de ver mis notas y aprobé el parcial de cálculo con buena nota. Todo el esfuerzo de estudiar valió la pena. Me siento muy contento y motivado para los siguientes exámenes.",
        },
        {
            "subject": "Gracias por la ayuda",
            "message": "Quiero agradecer a los compañeros que me ayudaron con las dudas del laboratorio. Gracias a ustedes pude completar mi tarea a tiempo. Es genial tener un grupo tan solidario.",
        },
    ],
}


async def create_forum_post(url: str, token: str, forum_id: int, subject: str, message: str):
    """Crea un post en un foro de Moodle."""
    ws_url = f"{url}/webservice/rest/server.php"
    payload = {
        "wstoken": token,
        "wsfunction": "mod_forum_add_discussion",
        "moodlewsrestformat": "json",
        "forumid": forum_id,
        "subject": subject,
        "message": message,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(ws_url, data=payload)
        data = response.json()
        if isinstance(data, dict) and "exception" in data:
            logger.error(f"Error creando post: {data.get('message', '')}")
            return None
        return data


async def seed_forum(url: str, token: str, forum_id: int):
    """Puebla un foro con posts de prueba."""
    logger.info(f"Creando posts de prueba en foro {forum_id}...")

    total = 0
    for risk_level, posts in TEST_POSTS.items():
        for post in posts:
            result = await create_forum_post(
                url, token, forum_id,
                post["subject"], post["message"],
            )
            if result:
                total += 1
                logger.info(f"  [{risk_level}] Creado: {post['subject']}")
            await asyncio.sleep(1)  # Evitar rate limiting de Moodle

    logger.info(f"Total posts creados: {total}")


def main():
    parser = argparse.ArgumentParser(description="Seed Moodle con datos de prueba")
    parser.add_argument("--url", type=str, default="http://localhost:8081")
    parser.add_argument("--token", type=str, required=True)
    parser.add_argument("--forum_id", type=int, required=True, help="ID del foro de Moodle")
    args = parser.parse_args()

    asyncio.run(seed_forum(args.url, args.token, args.forum_id))


if __name__ == "__main__":
    main()
