"""
Tests de integración para los endpoints de la API.
Usa TestClient de FastAPI con mocks de las bases de datos.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.core.security import get_current_user


# Mock del usuario autenticado
async def mock_current_user():
    return {"sub": "test@test.com", "role": "psicologo"}


# Override de dependencia
app.dependency_overrides[get_current_user] = mock_current_user


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
class TestHealthEndpoint:
    async def test_health_check(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/health")
            assert response.status_code == 200
            data = response.json()
            assert data["status"] == "ok"
            assert "version" in data


@pytest.mark.anyio
class TestAuthEndpoints:
    @patch("app.api.v1.endpoints.auth.UserService")
    async def test_login_invalid_credentials(self, mock_user_service):
        mock_instance = AsyncMock()
        mock_instance.authenticate.return_value = None
        mock_user_service.return_value = mock_instance

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post("/api/v1/auth/login", data={
                "username": "wrong@test.com",
                "password": "wrong",
            })
            assert response.status_code == 401


@pytest.mark.anyio
class TestAnalysisEndpoints:
    @patch("app.api.v1.endpoints.analysis.AnalysisService")
    async def test_analyze_text(self, mock_analysis_service):
        mock_instance = AsyncMock()
        mock_instance.analyze_text.return_value = {
            "risk_level": "bajo",
            "risk_score": 0.15,
            "confidence": 0.65,
            "linguistic_markers": {
                "first_person_pronouns": 0.0,
                "negations": 0.0,
                "negative_emotions": 0.0,
                "past_tense": 0.0,
                "isolation_references": 0.0,
            },
            "flagged_fragments": [],
            "analyzed_at": "2026-03-28T12:00:00",
            "cached": False,
        }
        mock_analysis_service.return_value = mock_instance

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/analysis/analyze-text",
                json={
                    "text": "Hoy fue un buen día en clase, aprendí mucho sobre redes neuronales",
                    "student_id": "student_001",
                    "source": "foro",
                    "course_id": "1",
                },
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "risk_level" in data
            assert "risk_score" in data

    async def test_analyze_text_too_short(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/analysis/analyze-text",
                json={"text": "Hola"},
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 422  # Validation error


@pytest.mark.anyio
class TestMoodleEndpoints:
    @patch("app.api.v1.endpoints.moodle.MoodleSyncService")
    async def test_list_courses(self, mock_sync):
        mock_instance = AsyncMock()
        mock_instance.get_moodle_courses.return_value = [
            {"id": 1, "fullname": "Curso Test"}
        ]
        mock_sync.return_value = mock_instance

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/moodle/courses",
                headers={"Authorization": "Bearer fake-token"},
            )
            assert response.status_code == 200
            data = response.json()
            assert "courses" in data

    async def test_webhook_invalid_json(self):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/moodle/webhook",
                content=b"not json",
                headers={"Content-Type": "application/json"},
            )
            assert response.status_code == 400

    @patch("app.api.v1.endpoints.moodle.MoodleSyncService")
    @patch("app.api.v1.endpoints.moodle.MoodleWebhookHandler")
    async def test_webhook_irrelevant_event(self, mock_handler_cls, mock_sync):
        mock_handler = MagicMock()
        mock_handler.validate_webhook.return_value = True
        mock_handler.parse_event.return_value = None
        mock_handler_cls.return_value = mock_handler

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/moodle/webhook",
                json={"eventname": "\\core\\event\\course_viewed"},
            )
            assert response.status_code == 200
            assert response.json()["status"] == "ignored"
