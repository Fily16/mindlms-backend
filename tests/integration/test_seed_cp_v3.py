"""
Verificación del seed de los Casos de Prueba v3 (scripts/seed_cp_v3.py).

Carga el conjunto `referencia` en una base SQLite en memoria y comprueba por API
los totales que citan los CP: 10 estudiantes (Alto 2, Medio 3, Bajo 5) y 12
alertas (Pendiente 5, Revisada 3, En seguimiento 2, Resuelta 2).
"""

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.security import create_access_token
from app.db.postgresql import get_session
from app.main import app
from app.models.user import Base
from scripts.seed_cp_v3 import asegurar_usuarios, cargar, limpiar, resumen, filas
from app.services.user_service import UserService


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def seed():
    """Base limpia + el seed cargado, con la app apuntando a ella."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session():
        async with maker() as s:
            yield s

    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _session
    yield maker
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)
    await engine.dispose()


async def _cargar(maker, conjunto="referencia"):
    async with maker() as s:
        await asegurar_usuarios(s)
        await limpiar(s)
        psi = await UserService(s).get_by_email("psicologo@mindlms.test")
        return await cargar(s, conjunto, psi)


def _auth():
    return {"Authorization": "Bearer " + create_access_token({"sub": "u-psi", "role": "psicologo"})}


def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.anyio
async def test_seed_referencia_conteos_por_api(seed):
    await _cargar(seed)
    async with _client() as c:
        counts = (await c.get("/api/v1/alerts/counts", headers=_auth())).json()
        assert counts["total_nivel"] == 12 and counts["total_estado"] == 12
        assert counts["por_nivel"] == {"alto": 3, "medio": 4, "bajo": 5}
        assert counts["por_estado"] == {
            "pendiente": 5,
            "revisada": 3,
            "en_seguimiento": 2,
            "resuelta": 2,
        }

        stats = (await c.get("/api/v1/students/statistics", headers=_auth())).json()
        assert stats["risk_distribution"] == {"alto": 2, "medio": 3, "bajo": 5}
        assert stats["total_students"] == 10

        estudiantes = (await c.get("/api/v1/students/", headers=_auth())).json()
        assert len(estudiantes) == 10
        # CP004 escenario 2 y CP034: estudiante.prueba03 no existe en el conjunto.
        assert all(e["student_id"] != "estudiante.prueba03" for e in estudiantes)


@pytest.mark.anyio
async def test_seed_referencia_es_idempotente(seed):
    await _cargar(seed)
    await _cargar(seed)
    async with _client() as c:
        counts = (await c.get("/api/v1/alerts/counts", headers=_auth())).json()
        assert counts["total_nivel"] == 12 and counts["total_estado"] == 12


@pytest.mark.anyio
async def test_seed_sin_alto_no_tiene_altas_ni_resueltas(seed):
    await _cargar(seed, "sin_alto")
    async with _client() as c:
        counts = (await c.get("/api/v1/alerts/counts", headers=_auth())).json()
        assert counts["total_nivel"] == 8
        assert counts["por_nivel"]["alto"] == 0
        assert counts["por_estado"]["resuelta"] == 0

        stats = (await c.get("/api/v1/students/statistics", headers=_auth())).json()
        assert stats["risk_distribution"] == {"alto": 0, "medio": 3, "bajo": 5}


@pytest.mark.anyio
async def test_seed_vacio_deja_el_panel_en_cero(seed):
    await _cargar(seed, "vacio")
    async with _client() as c:
        counts = (await c.get("/api/v1/alerts/counts", headers=_auth())).json()
        assert counts["total_nivel"] == 0
        stats = (await c.get("/api/v1/students/statistics", headers=_auth())).json()
        assert stats["total_students"] == 0
        assert (await c.get("/api/v1/students/", headers=_auth())).json() == []


def test_resumen_de_cada_conjunto_coincide_con_el_documento():
    ref = resumen(filas("referencia"))
    assert ref["estudiantes"] == 10 and ref["alertas"] == 12
    assert ref["niveles"] == {"alto": 2, "medio": 3, "bajo": 5}
    assert ref["estados"] == {"pendiente": 5, "revisada": 3, "en_seguimiento": 2, "resuelta": 2}

    sin_alto = resumen(filas("sin_alto"))
    assert sin_alto["estudiantes"] == 8 and sin_alto["alertas"] == 8
    assert sin_alto["niveles"] == {"alto": 0, "medio": 3, "bajo": 5}
    assert sin_alto["estados"]["resuelta"] == 0

    assert resumen(filas("vacio"))["alertas"] == 0
