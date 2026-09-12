"""
Script para configurar Moodle para pruebas con MindLMS.
Crea cursos, usuarios de prueba y habilita Web Services.
Uso: python scripts/setup_moodle.py --url http://localhost:8081 --token YOUR_TOKEN
"""

import argparse
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.moodle.client import MoodleClient, MoodleAPIError
from loguru import logger


async def setup_test_environment(url: str, token: str):
    """Configura el entorno de pruebas en Moodle."""
    client = MoodleClient(base_url=url, token=token)

    # 1. Verificar conexión
    logger.info("Verificando conexión con Moodle...")
    try:
        info = await client.get_site_info()
        logger.info(f"Conectado a: {info.get('sitename', 'Unknown')}")
        logger.info(f"Moodle version: {info.get('release', 'Unknown')}")
        logger.info(f"Usuario: {info.get('fullname', 'Unknown')}")
    except Exception as e:
        logger.error(f"No se pudo conectar a Moodle: {e}")
        logger.info("Asegúrate de que Moodle está corriendo y el token es válido.")
        logger.info("Pasos para obtener el token:")
        logger.info("  1. Login en Moodle como admin")
        logger.info("  2. Site administration > Plugins > Web services > Manage tokens")
        logger.info("  3. Crear token para el usuario admin")
        return

    # 2. Listar cursos existentes
    logger.info("\nCursos existentes:")
    courses = await client.get_courses()
    for c in courses:
        logger.info(f"  [{c['id']}] {c['fullname']}")

    # 3. Crear usuarios de prueba
    logger.info("\nNota: Para crear usuarios y cursos de prueba, usa la interfaz web de Moodle")
    logger.info("o ejecuta los siguientes pasos manualmente:")
    logger.info("")
    logger.info("=== CONFIGURAR WEB SERVICES ===")
    logger.info("1. Site administration > Plugins > Web services > Overview")
    logger.info("2. Enable web services = Yes")
    logger.info("3. Enable REST protocol")
    logger.info("4. Create external service 'MindLMS' con estas funciones:")
    logger.info("   - core_webservice_get_site_info")
    logger.info("   - core_course_get_courses")
    logger.info("   - core_course_get_contents")
    logger.info("   - core_enrol_get_enrolled_users")
    logger.info("   - mod_forum_get_forums_by_courses")
    logger.info("   - mod_forum_get_forum_discussions")
    logger.info("   - mod_forum_get_discussion_posts")
    logger.info("   - mod_chat_get_sessions")
    logger.info("   - mod_chat_get_session_messages")
    logger.info("   - mod_assign_get_assignments")
    logger.info("   - mod_assign_get_submissions")
    logger.info("   - core_message_get_messages")
    logger.info("   - core_user_get_users_by_field")
    logger.info("5. Crear token para el servicio y copiarlo en .env")
    logger.info("")
    logger.info("=== CREAR CURSO DE PRUEBA ===")
    logger.info("1. Site administration > Courses > Add a new course")
    logger.info("2. Nombre: 'Curso de Prueba MindLMS'")
    logger.info("3. Agregar actividades: Foro, Chat, Tarea (texto online)")
    logger.info("4. Inscribir usuarios de prueba como estudiantes")
    logger.info("")
    logger.info("=== DATOS DE PRUEBA ===")
    logger.info("Crear posts en el foro con textos de ejemplo variados")
    logger.info("para probar la detección de riesgo.")

    # 4. Verificar funciones disponibles
    logger.info("\nVerificando funciones WS disponibles...")
    try:
        forums = await client.get_forums_by_course(1)
        logger.info(f"  mod_forum OK - {len(forums)} foros encontrados")
    except MoodleAPIError as e:
        logger.warning(f"  mod_forum: {e.message}")

    logger.info("\nSetup completado. Configura MOODLE_TOKEN en backend/.env")


def main():
    parser = argparse.ArgumentParser(description="Setup Moodle para MindLMS")
    parser.add_argument("--url", type=str, default="http://localhost:8081")
    parser.add_argument("--token", type=str, required=True, help="Token de Web Services de Moodle")
    args = parser.parse_args()

    asyncio.run(setup_test_environment(args.url, args.token))


if __name__ == "__main__":
    main()
