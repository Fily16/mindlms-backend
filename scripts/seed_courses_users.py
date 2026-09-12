"""
Script para poblar Moodle con datos iniciales de prueba:
- 3 cursos (Ingeniería de Sistemas, Cálculo, Algoritmos)
- 10 estudiantes con perfiles realistas
- Matricula de todos los estudiantes en los 3 cursos

Uso:
    python scripts/seed_courses_users.py
"""

import os
import sys
import requests
from typing import Any


# ============================================================
# Configuración (se lee del entorno; nunca hardcodear el token)
# ============================================================
MOODLE_URL = os.getenv("MOODLE_URL", "http://localhost/moodle")
MOODLE_TOKEN = os.getenv("MOODLE_TOKEN", "")
WS_URL = f"{MOODLE_URL}/webservice/rest/server.php"

if not MOODLE_TOKEN:
    sys.exit(
        "Falta MOODLE_TOKEN. Expórtalo antes de ejecutar:\n"
        "  export MOODLE_TOKEN=<token de web services de Moodle>"
    )

# Rol "student" en Moodle tiene roleid=5 por defecto
STUDENT_ROLE_ID = 5

# Contraseña común para todos los estudiantes de prueba
DEFAULT_PASSWORD = os.getenv("SEED_DEFAULT_PASSWORD", "MindLMS2026!")


# ============================================================
# Datos a crear
# ============================================================
COURSES = [
    {
        "fullname": "Introducción a la Ingeniería de Sistemas",
        "shortname": "INGSIS-2026-01",
        "categoryid": 1,
        "summary": (
            "Curso introductorio a la carrera de Ingeniería de Sistemas. "
            "Fundamentos metodológicos, ciclo de vida del software y áreas "
            "de especialización profesional."
        ),
        "summaryformat": 1,
    },
    {
        "fullname": "Cálculo Diferencial",
        "shortname": "CALC-2026-01",
        "categoryid": 1,
        "summary": (
            "Cálculo diferencial de una variable real. Límites, continuidad, "
            "derivadas y sus aplicaciones en ingeniería."
        ),
        "summaryformat": 1,
    },
    {
        "fullname": "Algoritmos y Estructuras de Datos",
        "shortname": "ALGO-2026-01",
        "categoryid": 1,
        "summary": (
            "Estructuras de datos fundamentales (listas, árboles, grafos), "
            "complejidad algorítmica y diseño de algoritmos eficientes."
        ),
        "summaryformat": 1,
    },
]

# 10 estudiantes con nombres realistas peruanos (contexto UPC Lima)
STUDENTS = [
    {"username": "mgarcia", "firstname": "María", "lastname": "García Torres",
     "email": "maria.garcia@mindlms.test"},
    {"username": "jrodriguez", "firstname": "Juan", "lastname": "Rodríguez Pérez",
     "email": "juan.rodriguez@mindlms.test"},
    {"username": "amartinez", "firstname": "Ana", "lastname": "Martínez Quispe",
     "email": "ana.martinez@mindlms.test"},
    {"username": "clopez", "firstname": "Carlos", "lastname": "López Huamán",
     "email": "carlos.lopez@mindlms.test"},
    {"username": "lfernandez", "firstname": "Lucía", "lastname": "Fernández Rojas",
     "email": "lucia.fernandez@mindlms.test"},
    {"username": "dsanchez", "firstname": "Diego", "lastname": "Sánchez Mendoza",
     "email": "diego.sanchez@mindlms.test"},
    {"username": "storres", "firstname": "Sofía", "lastname": "Torres Castillo",
     "email": "sofia.torres@mindlms.test"},
    {"username": "mramirez", "firstname": "Miguel", "lastname": "Ramírez Flores",
     "email": "miguel.ramirez@mindlms.test"},
    {"username": "vflores", "firstname": "Valentina", "lastname": "Flores Vargas",
     "email": "valentina.flores@mindlms.test"},
    {"username": "svargas", "firstname": "Sebastián", "lastname": "Vargas Salazar",
     "email": "sebastian.vargas@mindlms.test"},
]


# ============================================================
# Helper de llamada a Moodle
# ============================================================
def moodle_call(wsfunction: str, params: dict[str, Any]) -> Any:
    """Llama a una función de Moodle Web Services y retorna el JSON parseado."""
    payload = {
        "wstoken": MOODLE_TOKEN,
        "wsfunction": wsfunction,
        "moodlewsrestformat": "json",
        **params,
    }
    resp = requests.post(WS_URL, data=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if isinstance(data, dict) and "exception" in data:
        raise RuntimeError(
            f"Moodle API error en {wsfunction}: "
            f"{data.get('errorcode')} - {data.get('message')}"
        )
    return data


def flatten_params(prefix: str, items: list[dict]) -> dict:
    """Convierte lista de dicts a formato Moodle: prefix[0][key]=value."""
    flat = {}
    for i, item in enumerate(items):
        for k, v in item.items():
            flat[f"{prefix}[{i}][{k}]"] = v
    return flat


# ============================================================
# 1. Verificar conexión
# ============================================================
def verify_connection() -> None:
    info = moodle_call("core_webservice_get_site_info", {})
    print(f"[OK] Conectado a: {info['sitename']} ({info['release']})")
    print(f"     Usuario: {info['fullname']} (userid={info['userid']})")


# ============================================================
# 2. Crear cursos
# ============================================================
def create_courses() -> list[dict]:
    print("\n=== Creando cursos ===")
    params = flatten_params("courses", COURSES)
    result = moodle_call("core_course_create_courses", params)
    for c in result:
        print(f"  [id={c['id']:3}] {c['shortname']}")
    return result


# ============================================================
# 3. Crear usuarios
# ============================================================
def create_users() -> list[dict]:
    print("\n=== Creando estudiantes ===")
    users_payload = []
    for s in STUDENTS:
        users_payload.append({
            **s,
            "password": DEFAULT_PASSWORD,
            "auth": "manual",
            "lang": "es",
            "city": "Lima",
            "country": "PE",
        })
    params = flatten_params("users", users_payload)
    result = moodle_call("core_user_create_users", params)
    for u in result:
        print(f"  [id={u['id']:3}] {u['username']}")
    return result


# ============================================================
# 4. Matricular estudiantes en cursos
# ============================================================
def enroll_users_in_courses(users: list[dict], courses: list[dict]) -> None:
    print("\n=== Matriculando estudiantes en cursos ===")
    enrolments = []
    for course in courses:
        for user in users:
            enrolments.append({
                "roleid": STUDENT_ROLE_ID,
                "userid": user["id"],
                "courseid": course["id"],
            })
    params = flatten_params("enrolments", enrolments)
    moodle_call("enrol_manual_enrol_users", params)
    print(f"  [OK] {len(enrolments)} matrículas creadas "
          f"({len(users)} estudiantes x {len(courses)} cursos)")


# ============================================================
# Main
# ============================================================
def main() -> int:
    try:
        verify_connection()
        courses = create_courses()
        users = create_users()
        enroll_users_in_courses(users, courses)

        print("\n" + "=" * 50)
        print("[DONE] Seed completado con éxito")
        print("=" * 50)
        print(f"  Cursos creados:       {len(courses)}")
        print(f"  Estudiantes creados:  {len(users)}")
        print(f"  Matrículas:           {len(courses) * len(users)}")
        print(f"\nPassword de todos los estudiantes: {DEFAULT_PASSWORD}")
        print(f"\nVerifica en: {MOODLE_URL}/course/index.php")
        return 0
    except Exception as e:
        print(f"\n[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
