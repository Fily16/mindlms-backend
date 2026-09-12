"""Tests unitarios para el handler de webhooks de Moodle."""

import pytest
from app.services.moodle.webhook_handler import MoodleWebhookHandler


@pytest.fixture
def handler():
    return MoodleWebhookHandler()


class TestParseEvent:
    def test_forum_post_created(self, handler):
        event = {
            "eventname": "\\mod_forum\\event\\post_created",
            "userid": "42",
            "courseid": "5",
            "timecreated": 1711600000,
            "contexturl": "http://moodle/mod/forum/discuss.php?d=1",
            "other": {
                "content": "Me siento muy estresado con los exámenes y no puedo dormir",
                "forumname": "Foro General",
            },
        }
        parsed = handler.parse_event(event)
        assert parsed is not None
        assert parsed["source"] == "foro"
        assert parsed["user_id"] == "42"
        assert parsed["course_id"] == "5"
        assert "estresado" in parsed["text"]

    def test_chat_message(self, handler):
        event = {
            "eventname": "\\mod_chat\\event\\message_sent",
            "userid": "10",
            "courseid": "3",
            "timecreated": 1711600000,
            "other": {
                "message": "No sé qué hacer con mi vida, estoy muy triste y cansado de todo",
            },
        }
        parsed = handler.parse_event(event)
        assert parsed is not None
        assert parsed["source"] == "chat"

    def test_assignment_submission(self, handler):
        event = {
            "eventname": "\\mod_assign\\event\\submission_created",
            "userid": "15",
            "courseid": "7",
            "timecreated": 1711600000,
            "other": {
                "onlinetext": "En mi reflexión personal debo decir que me siento muy ansioso y preocupado por mi futuro",
                "assignmentname": "Reflexión semana 5",
            },
        }
        parsed = handler.parse_event(event)
        assert parsed is not None
        assert parsed["source"] == "tarea"

    def test_ignores_unsupported_event(self, handler):
        event = {
            "eventname": "\\core\\event\\course_viewed",
            "userid": "1",
            "courseid": "1",
            "timecreated": 1711600000,
        }
        parsed = handler.parse_event(event)
        assert parsed is None

    def test_ignores_short_text(self, handler):
        event = {
            "eventname": "\\mod_forum\\event\\post_created",
            "userid": "1",
            "courseid": "1",
            "timecreated": 1711600000,
            "other": {"content": "Ok"},
        }
        parsed = handler.parse_event(event)
        assert parsed is None


class TestShouldAnalyze:
    def test_valid_text(self, handler):
        parsed = {
            "text": "Me siento muy estresado con los exámenes y no puedo dormir bien",
            "source": "foro",
        }
        assert handler.should_analyze(parsed) is True

    def test_short_text(self, handler):
        parsed = {"text": "Hola", "source": "chat"}
        assert handler.should_analyze(parsed) is False

    def test_code_text(self, handler):
        parsed = {
            "text": "function() { if (x > 0) { return true; } else { return false; } }",
            "source": "foro",
        }
        assert handler.should_analyze(parsed) is False

    def test_none_event(self, handler):
        assert handler.should_analyze(None) is False
