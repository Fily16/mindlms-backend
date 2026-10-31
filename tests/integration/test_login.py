"""
Login del Panel Psicológico con el servicio y la base reales (SQLite en memoria).

Reproduce el reporte "ingreso mis credenciales y me sale incorrecto": el email
se comparaba tal cual, así que "Psicologo@..." (autocapitalizado del celular) o
un espacio al final respondían 401 aunque la contraseña fuera la correcta.

Monta solo el router de auth para no cargar el clasificador ni Moodle.
"""

import pytest
from fastapi import FastAPI
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.api.v1.endpoints import auth
from app.db.postgresql import get_session
from app.models.user import Base, User, UserRole
from app.services.user_service import UserService

PASSWORD = "MindLMS2026!"


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def cliente():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with maker() as s:
        svc = UserService(s)
        await svc.create_user("psicologo@mindlms.test", PASSWORD, "Dra. Carmen Vega", "psicologo")
        # Usuario guardado con mayúsculas antes de normalizar los emails.
        s.add(User(id="u-legacy", email="Admin@MindLMS.test",
                   hashed_password=svc_hash(PASSWORD), full_name="Admin",
                   role=UserRole.ADMIN))
        await s.commit()

    async def _session():
        async with maker() as s:
            yield s

    api = FastAPI()
    api.include_router(auth.router, prefix="/api/v1/auth")
    api.dependency_overrides[get_session] = _session
    async with AsyncClient(transport=ASGITransport(app=api), base_url="http://test") as c:
        c.maker = maker
        yield c
    await engine.dispose()


def svc_hash(password: str) -> str:
    from app.core.security import get_password_hash
    return get_password_hash(password)


async def _login(c, email, password=PASSWORD):
    return await c.post("/api/v1/auth/login", data={"username": email, "password": password})


@pytest.mark.anyio
@pytest.mark.parametrize("email", [
    "psicologo@mindlms.test",
    "Psicologo@mindlms.test",
    "PSICOLOGO@MINDLMS.TEST",
    "psicologo@mindlms.test ",
    " psicologo@mindlms.test",
])
async def test_login_ignora_mayusculas_y_espacios_del_email(cliente, email):
    r = await _login(cliente, email)
    assert r.status_code == 200, r.json()
    assert r.json()["access_token"]


@pytest.mark.anyio
async def test_login_encuentra_usuario_guardado_con_mayusculas(cliente):
    r = await _login(cliente, "admin@mindlms.test")
    assert r.status_code == 200, r.json()


@pytest.mark.anyio
async def test_contrasena_sigue_distinguiendo_mayusculas(cliente):
    r = await _login(cliente, "psicologo@mindlms.test", "mindlms2026!")
    assert r.status_code == 401
    assert r.json()["detail"] == "Email o contraseña incorrectos"


@pytest.mark.anyio
async def test_email_se_guarda_normalizado(cliente):
    async with cliente.maker() as s:
        user = await UserService(s).create_user("  Nuevo@MindLMS.Test ", PASSWORD, "N", "psicologo")
    assert user.email == "nuevo@mindlms.test"


@pytest.mark.anyio
async def test_set_password_permite_entrar_con_la_nueva(cliente):
    async with cliente.maker() as s:
        svc = UserService(s)
        user = await svc.get_by_email("psicologo@mindlms.test")
        await svc.set_password(user, "OtraClave2026!")
    assert (await _login(cliente, "psicologo@mindlms.test")).status_code == 401
    assert (await _login(cliente, "psicologo@mindlms.test", "OtraClave2026!")).status_code == 200
