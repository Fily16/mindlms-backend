"""
Pruebas de los requisitos ajustados en la auditoría de HU y CP (v1.1).

Cada prueba indica la HU / escenario que cubre. Usa SQLite en memoria en
lugar de PostgreSQL para ejercitar los endpoints y el servicio reales.
"""

import uuid
from datetime import datetime

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.main import app
from app.db.postgresql import get_session
from app.core.security import create_access_token, get_current_user
from app.models.user import Base, User, UserRole
from app.models.alert import Alert, AlertStatus, RiskLevelDB

T_ALTO = "Ya no puedo más con todo esto, me siento completamente solo y siento que nada tiene sentido."


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def _session():
        async with maker() as s:
            yield s

    # Estas pruebas validan la autenticación real: sin el override global
    # de get_current_user que usa test_api_endpoints.py.
    saved = dict(app.dependency_overrides)
    app.dependency_overrides.clear()
    app.dependency_overrides[get_session] = _session
    async with maker() as s:
        s.add_all([
            User(id="u-psi", email="psicologo@mindlms.test", hashed_password="x",
                 full_name="Dra. Carmen Vega", role=UserRole.PSYCHOLOGIST),
            User(id="u-view", email="viewer@mindlms.test", hashed_password="x",
                 full_name="Visitante", role=UserRole.VIEWER),
        ])
        for i, (lvl, st) in enumerate([
            ("alto", "pendiente"), ("alto", "revisada"), ("medio", "pendiente"),
            ("medio", "resuelta"), ("bajo", "pendiente"),
        ]):
            s.add(Alert(
                id=f"a{i}", student_id="101" if i < 3 else "202",
                student_name="Estudiante Prueba", course_id="1", course_name="Curso A",
                risk_level=RiskLevelDB(lvl), risk_score=0.8, confidence=0.9,
                text_fragment=T_ALTO, source="foro", status=AlertStatus(st),
                created_at=datetime(2026, 9, 1, 10, i),
            ))
        await s.commit()
    yield maker
    app.dependency_overrides.clear()
    app.dependency_overrides.update(saved)
    await engine.dispose()


def _auth(role="psicologo", uid="u-psi"):
    return {"Authorization": "Bearer " + create_access_token({"sub": uid, "role": role})}


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# ── HU0002: control de acceso ─────────────────────────────────────────

@pytest.mark.anyio
async def test_hu0002_2_sin_token_no_hay_datos(db):
    async with await _client() as c:
        for url in ("/api/v1/alerts/", "/api/v1/students/", "/api/v1/students/statistics",
                    "/api/v1/ml/detect/status"):
            r = await c.get(url)
            assert r.status_code == 401, url


@pytest.mark.anyio
async def test_hu0002_3_rol_sin_permiso_recibe_403(db):
    async with await _client() as c:
        r = await c.get("/api/v1/alerts/", headers=_auth("viewer", "u-view"))
        assert r.status_code == 403
        assert "no tiene permisos" in r.json()["detail"]


@pytest.mark.anyio
async def test_hu0002_3_login_de_rol_sin_permiso(db, monkeypatch):
    from app.services import user_service

    async def fake_auth(self, email, password):
        return User(id="u-view", email=email, hashed_password="x", full_name="V",
                    role=UserRole.VIEWER, is_active=True)

    monkeypatch.setattr(user_service.UserService, "authenticate", fake_auth)
    async with await _client() as c:
        r = await c.post("/api/v1/auth/login", data={"username": "viewer@mindlms.test", "password": "x"})
        assert r.status_code == 403


@pytest.mark.anyio
async def test_sse_acepta_token_por_query(db):
    from app.core.security import get_current_user as dep
    user = await dep(token=None, access_token=create_access_token({"sub": "u-psi", "role": "psicologo"}))
    assert user["user_id"] == "u-psi"


# ── HU0020: contadores ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_hu0020_contadores_por_nivel_y_estado(db):
    async with await _client() as c:
        r = await c.get("/api/v1/alerts/counts", headers=_auth())
        d = r.json()
        assert d["por_nivel"] == {"bajo": 1, "medio": 2, "alto": 2}
        assert d["por_estado"]["pendiente"] == 3
        # Con filtro de estado, el contador de nivel cuenta dentro del estado
        r = await c.get("/api/v1/alerts/counts", params={"status": "pendiente"}, headers=_auth())
        assert r.json()["por_nivel"] == {"bajo": 1, "medio": 1, "alto": 1}


# ── HU0022: cambio de estado con fecha e historial ───────────────────

@pytest.mark.anyio
async def test_hu0022_cambio_de_estado_registra_fecha_e_historial(db):
    async with await _client() as c:
        r = await c.patch("/api/v1/alerts/a0/status", params={"new_status": "revisada"}, headers=_auth())
        assert r.status_code == 200 and r.json()["updated_at"]
        r = await c.get("/api/v1/alerts/a0", headers=_auth())
        h = r.json()["status_history"]
        assert h[-1]["de"] == "pendiente" and h[-1]["a"] == "revisada"
        assert h[-1]["por"] == "Dra. Carmen Vega"


@pytest.mark.anyio
async def test_hu0022_estado_invalido_422(db):
    async with await _client() as c:
        r = await c.patch("/api/v1/alerts/a0/status", params={"new_status": "cerrada"}, headers=_auth())
        assert r.status_code == 422


# ── HU0023: nota vacía ───────────────────────────────────────────────

@pytest.mark.anyio
async def test_hu0023_2_nota_vacia_422(db):
    async with await _client() as c:
        r = await c.post("/api/v1/alerts/a0/notes", json={"content": "   "}, headers=_auth())
        assert r.status_code == 422
        r = await c.post("/api/v1/alerts/a0/notes", json={"content": "Se contactó al estudiante"}, headers=_auth())
        assert r.status_code == 200
        notas = (await c.get("/api/v1/alerts/a0", headers=_auth())).json()["notes"]
        assert notas[-1]["author"] == "Dra. Carmen Vega"


# ── HU0025: marcadores en el detalle ─────────────────────────────────

@pytest.mark.anyio
async def test_hu0025_detalle_incluye_marcadores(db):
    async with await _client() as c:
        ev = (await c.get("/api/v1/alerts/a0", headers=_auth())).json()["linguistic_evidence"]
        assert "no puedo" in ev["marcadores"]["desesperanza"]
        assert "solo" in ev["marcadores"]["aislamiento"]
        assert ev["fragmentos_alto_riesgo"]


# ── HU0026 / HU0027: validación del riesgo ───────────────────────────

@pytest.mark.anyio
async def test_hu0026_confirmacion_visible_y_nivel_intacto(db):
    async with await _client() as c:
        r = await c.patch("/api/v1/alerts/a2/risk-validation", json={"decision": "confirmado"}, headers=_auth())
        assert r.status_code == 200
        d = (await c.get("/api/v1/alerts/a2", headers=_auth())).json()
        assert d["risk_validated"] == "confirmado" and d["risk_level"] == "medio"
        assert d["validated_at"]


@pytest.mark.anyio
async def test_hu0027_2_ajuste_sin_justificacion_422(db):
    async with await _client() as c:
        r = await c.patch("/api/v1/alerts/a2/risk-validation",
                          json={"decision": "ajustado", "nivel_ajustado": "alto", "motivo": ""},
                          headers=_auth())
        assert r.status_code == 422
        r = await c.patch("/api/v1/alerts/a2/risk-validation",
                          json={"decision": "ajustado", "nivel_ajustado": "urgente", "motivo": "x"},
                          headers=_auth())
        assert r.status_code == 422


# ── HU0028 – HU0031: informe, evidencia y comunicación ───────────────

@pytest.mark.anyio
async def test_hu0028_informe_vacio_422_y_evidencia_incluida(db):
    async with await _client() as c:
        r = await c.post("/api/v1/alerts/a0/report", json={"contenido": " "}, headers=_auth())
        assert r.status_code == 422
        r = await c.post("/api/v1/alerts/a0/report",
                         json={"contenido": "Indicadores de ansiedad moderada."}, headers=_auth())
        assert r.status_code == 200 and r.json()["derivacion"] is False
        exp = (await c.get("/api/v1/students/101/reports", headers=_auth())).json()
        assert "Evidencia lingüística generada por MindLMS" in exp[0]["contenido"]
        assert exp[0]["autor"] == "Dra. Carmen Vega"


@pytest.mark.anyio
async def test_hu0031_comunicacion_requiere_fecha(db):
    async with await _client() as c:
        rid = (await c.post("/api/v1/alerts/a0/report", json={"contenido": "Informe"}, headers=_auth())).json()["id"]
        r = await c.patch(f"/api/v1/alerts/reports/{rid}/communication", json={}, headers=_auth())
        assert r.status_code == 422
        r = await c.patch(f"/api/v1/alerts/reports/{rid}/communication",
                          json={"fecha_comunicacion": "2026-10-01"}, headers=_auth())
        assert r.status_code == 200
        assert r.json()["fecha_comunicacion"].startswith("2026-10-01")


# ── HU0015: atender este caso ────────────────────────────────────────

@pytest.mark.anyio
async def test_hu0015_atender_caso_asigna_y_pasa_a_seguimiento(db):
    async with await _client() as c:
        r = await c.post("/api/v1/students/101/attend", headers=_auth())
        d = r.json()
        assert d["alertas_en_seguimiento"] == 3 and d["asignado_a"] == "Dra. Carmen Vega"
        a = (await c.get("/api/v1/alerts/a0", headers=_auth())).json()
        assert a["status"] == "en_seguimiento" and a["assigned_to"] == "u-psi"


# ── HU0005: estado de la extracción ──────────────────────────────────

@pytest.mark.anyio
async def test_hu0005_estado_de_extraccion(db):
    async with await _client() as c:
        r = await c.get("/api/v1/ml/extraction/status", headers=_auth())
        assert r.status_code == 200
        assert r.json()["estado"] in ("en_vivo", "sin_conexion", "sin_datos")


# ── HU0033: anonimización ────────────────────────────────────────────

def test_hu0033_anonimiza_nombre_correo_y_dni():
    from app.services.nlp.text_processor import TextProcessor

    p = TextProcessor()
    t = "Hola, soy Juan Pérez, mi correo es juan.perez@upc.edu.pe y mi DNI es 12345678. Me siento muy solo."
    a = p.anonymize_text(p.clean_text(t))
    assert "Juan Pérez" not in a and "juan.perez@upc.edu.pe" not in a and "12345678" not in a
    assert "[EMAIL]" in a and "[DNI]" in a
