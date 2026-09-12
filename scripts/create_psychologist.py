"""
Crea un usuario psicólogo en PostgreSQL para poder usar el dashboard.

Uso:
    python scripts/create_psychologist.py

Credenciales que se crean (configurables por variables de entorno):
    Email:    PSYCHOLOGIST_EMAIL    (default: psicologo@mindlms.test)
    Password: PSYCHOLOGIST_PASSWORD (default: solo para desarrollo local)
    Rol:      psicologo

En un despliegue accesible desde internet, definir SIEMPRE
PSYCHOLOGIST_PASSWORD: el default es público porque este repo es público.
"""

import asyncio
import os
import sys
from pathlib import Path

# Para que encuentre app/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.postgresql import init_db, async_session
from app.services.user_service import UserService


EMAIL = os.getenv("PSYCHOLOGIST_EMAIL", "psicologo@mindlms.test")
PASSWORD = os.getenv("PSYCHOLOGIST_PASSWORD", "MindLMS2026!")
FULL_NAME = os.getenv("PSYCHOLOGIST_NAME", "Dra. Carmen Vega")
ROLE = "psicologo"


async def main():
    await init_db()
    async with async_session() as session:
        svc = UserService(session)
        existing = await svc.get_by_email(EMAIL)
        if existing:
            print(f"[OK] Ya existe: {EMAIL} (id={existing.id})")
            return
        user = await svc.create_user(EMAIL, PASSWORD, FULL_NAME, ROLE)
        print(f"[OK] Usuario creado:")
        print(f"     Email:    {EMAIL}")
        print(f"     Password: {PASSWORD}")
        print(f"     Nombre:   {FULL_NAME}")
        print(f"     Rol:      {ROLE}")
        print(f"     ID:       {user.id}")


if __name__ == "__main__":
    asyncio.run(main())
