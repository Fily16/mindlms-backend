"""
Test de conexión end-to-end usando MoodleClient (read-only).
Verifica que el backend puede leer datos reales del Moodle local.

Uso:
    python scripts/test_moodle_connection.py
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.services.moodle.client import MoodleClient, MoodleAPIError
from app.core.config import settings


async def main() -> int:
    print("=" * 60)
    print("  Test de conexión: Backend <-> Moodle local")
    print("=" * 60)
    print(f"  MOODLE_URL:   {settings.MOODLE_URL}")
    print(f"  MOODLE_TOKEN: {settings.MOODLE_TOKEN[:8]}...{settings.MOODLE_TOKEN[-4:]}")
    print()

    client = MoodleClient()

    # === 1. Site info ===
    print("[1/5] GET site info...")
    try:
        info = await client.get_site_info()
        print(f"      OK - {info['sitename']} | Moodle {info['release']}")
        print(f"      Admin: {info['fullname']} (id={info['userid']})")
        print(f"      Funciones WS autorizadas: {len(info['functions'])}")
    except MoodleAPIError as e:
        print(f"      FAIL: {e}")
        return 1

    # === 2. Cursos ===
    print("\n[2/5] GET cursos...")
    courses = await client.get_courses()
    print(f"      OK - {len(courses)} cursos encontrados")
    # Filtrar cursos reales (excluir Site home id=1)
    real_courses = [c for c in courses if c["id"] != 1]
    for c in real_courses:
        print(f"        [id={c['id']}] {c['fullname']}")

    if not real_courses:
        print("      [WARN] No hay cursos reales. Corre seed_courses_users.py primero.")
        return 1

    # === 3. Usuarios matriculados ===
    target_course = real_courses[0]
    print(f"\n[3/5] GET usuarios matriculados en '{target_course['shortname']}'...")
    enrolled = await client.get_enrolled_users(target_course["id"])
    print(f"      OK - {len(enrolled)} usuarios matriculados")
    for u in enrolled[:5]:
        roles = [r["shortname"] for r in u.get("roles", [])]
        print(f"        [{u['id']}] {u['fullname']:30} | {roles}")
    if len(enrolled) > 5:
        print(f"        ... y {len(enrolled) - 5} más")

    # === 4. Contenidos del curso ===
    print(f"\n[4/5] GET contenido del curso '{target_course['shortname']}'...")
    contents = await client.get_course_contents(target_course["id"])
    print(f"      OK - {len(contents)} secciones")
    total_modules = sum(len(s.get("modules", [])) for s in contents)
    print(f"      Total módulos/recursos: {total_modules}")

    # === 5. Foros del curso ===
    print(f"\n[5/5] GET foros del curso '{target_course['shortname']}'...")
    forums = await client.get_forums_by_course(target_course["id"])
    print(f"      OK - {len(forums)} foros encontrados")
    for f in forums:
        print(f"        [forum_id={f['id']}] {f['name']}")
    if not forums:
        print("      [INFO] No hay foros aún. Tenemos que crearlos en Moodle UI.")

    # === Resumen ===
    print("\n" + "=" * 60)
    print("  Conexión OK: El backend puede leer datos del Moodle local")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
