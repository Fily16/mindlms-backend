"""
Tests de integración para la integración con Moodle.
Usa mocks de httpx para simular la API de Moodle.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.moodle.client import MoodleClient, MoodleAPIError
from app.services.moodle.text_extractor import MoodleTextExtractor


@pytest.fixture
def mock_client():
    client = MoodleClient(base_url="http://moodle.test", token="test-token")
    return client


class TestMoodleClient:
    @pytest.mark.asyncio
    @patch("app.services.moodle.client.httpx.AsyncClient")
    async def test_get_site_info(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "sitename": "Test Moodle",
            "release": "4.3",
            "fullname": "Admin User",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_httpx_cls.return_value = mock_client_instance

        client = MoodleClient(base_url="http://moodle.test", token="test")
        result = await client.get_site_info()
        assert result["sitename"] == "Test Moodle"

    @pytest.mark.asyncio
    @patch("app.services.moodle.client.httpx.AsyncClient")
    async def test_api_error_handling(self, mock_httpx_cls):
        mock_response = MagicMock()
        mock_response.json.return_value = {
            "exception": "moodle_exception",
            "message": "Invalid token",
            "errorcode": "invalidtoken",
        }
        mock_response.raise_for_status = MagicMock()

        mock_client_instance = AsyncMock()
        mock_client_instance.post.return_value = mock_response
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_httpx_cls.return_value = mock_client_instance

        client = MoodleClient(base_url="http://moodle.test", token="bad-token")
        with pytest.raises(MoodleAPIError) as exc_info:
            await client.get_site_info()
        assert "Invalid token" in str(exc_info.value)


class TestTextExtractor:
    def test_clean_html(self):
        extractor = MoodleTextExtractor(client=MagicMock())
        html = "<p>Hola <strong>mundo</strong>&nbsp;&amp; más</p><br/>"
        result = extractor._clean_html(html)
        assert "<" not in result
        assert "Hola mundo & más" == result

    def test_group_consecutive_messages(self):
        extractor = MoodleTextExtractor(client=MagicMock())
        messages = [
            {"userid": 1, "message": "Hola", "timestamp": 100},
            {"userid": 1, "message": "¿Cómo están?", "timestamp": 101},
            {"userid": 2, "message": "Bien, gracias", "timestamp": 102},
            {"userid": 2, "message": "¿Y tú?", "timestamp": 103},
            {"userid": 1, "message": "Más o menos", "timestamp": 104},
        ]
        grouped = extractor._group_consecutive_messages(messages)
        assert len(grouped) == 3
        assert "Hola" in grouped[0]["text"]
        assert "Cómo están" in grouped[0]["text"]
        assert grouped[0]["userid"] == 1
        assert grouped[1]["userid"] == 2
        assert grouped[2]["userid"] == 1

    def test_group_empty_messages(self):
        extractor = MoodleTextExtractor(client=MagicMock())
        assert extractor._group_consecutive_messages([]) == []
