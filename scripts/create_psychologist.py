"""
Crea un usuario psicólogo en PostgreSQL para poder usar el dashboard.

Uso:
    python scripts/create_psychologist.py
    python scripts/create_psychologist.py --reset-password   # si ya existe

--reset-password: si el usuario ya existe, le pone la contraseña de
PSYCHOLOGIST_PASSWORD (o la default), lo reactiva y le asegura el rol
psicologo. Sirve cuando el login del dashboard responde "Email o contraseña
incorrectos" y no se sabe con qué contraseña se creó el usuario.

Credenciales que se crean (configurables por variables de entorno):
    Email:    PSYCHOLOGIST_EMAIL    (default: psicologo@mindlms.test)
    Password: PSYCHOLOGIST_PASSWORD (default: solo para desarrollo local)
    Rol:      psicologo

En un despliegue accesible desde internet, definir SIEMPRE
PSYCHOLOGIST_PASSWORD: el default es público porque este repo es público.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

# Para que encuentre app/
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.postgresql import init_db, async_session
from app.models.user import UserRole
from app.services.user_service import UserService, normalizar_email


EMAIL = normalizar_email(os.getenv("PSYCHOLOGIST_EMAIL", "psicologo@mindlms.test"))
PASSWORD = os.getenv("PSYCHOLOGIST_PASSWORD", "MindLMS2026!")
FULL_NAME = os.getenv("PSYCHOLOGIST_NAME", "Dra. Carmen Vega")
ROLE = "psicologo"


async def main(reset_password: bool = False):
    await init_db()
    async with async_session() as session:
        svc = UserService(session)
        existing = await svc.get_by_email(EMAIL)
        if existing:
            if not reset_password:
                print(f"[OK] Ya existe: {existing.email} (id={existing.id})")
                print(f"     Rol: {existing.role.value}  Activo: {existing.is_active}")
                print("     La contraseña NO se cambió. Para fijarla usa --reset-password.")
                return
            existing.role = UserRole(ROLE)
            existing.is_active = True
            await svc.set_password(existing, PASSWORD)
            print(f"[OK] Contraseña restablecida:")
            print(f"     Email:    {existing.email}")
            print(f"     Password: {PASSWORD}")
            print(f"     Rol:      {ROLE} (activo)")
            return
        user = await svc.create_user(EMAIL, PASSWORD, FULL_NAME, ROLE)
        print(f"[OK] Usuario creado:")
        print(f"     Email:    {EMAIL}")
        print(f"     Password: {PASSWORD}")
        print(f"     Nombre:   {FULL_NAME}")
        print(f"     Rol:      {ROLE}")
        print(f"     ID:       {user.id}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="si el usuario ya existe, fija su contraseña, lo reactiva y le da rol psicologo",
    )
    asyncio.run(main(parser.parse_args().reset_password))
