"""Tests unitarios para el procesador de texto NLP."""

import pytest
from app.services.nlp.text_processor import TextProcessor


@pytest.fixture
def processor():
    return TextProcessor()


class TestCleanText:
    def test_removes_urls(self, processor):
        text = "Estoy mal https://example.com no puedo más"
        result = processor.clean_text(text)
        assert "https://" not in result

    def test_removes_emails(self, processor):
        text = "Contactar a juan@mail.com por favor"
        result = processor.clean_text(text)
        assert "juan@mail.com" not in result

    def test_normalizes_whitespace(self, processor):
        text = "Mucho    espacio   aquí"
        result = processor.clean_text(text)
        assert "  " not in result


class TestLinguisticMarkers:
    def test_detects_first_person_pronouns(self, processor):
        text = "yo me siento mal y mi vida no tiene sentido"
        markers = processor.extract_linguistic_markers(text)
        assert markers.first_person_pronouns > 0

    def test_detects_negations(self, processor):
        text = "no puedo nunca nada me sale bien jamás"
        markers = processor.extract_linguistic_markers(text)
        assert markers.negations > 0

    def test_detects_negative_emotions(self, processor):
        text = "estoy triste ansioso y con miedo de fracaso"
        markers = processor.extract_linguistic_markers(text)
        assert markers.negative_emotions > 0

    def test_detects_isolation(self, processor):
        text = "estoy solo nadie me entiende me siento abandonado"
        markers = processor.extract_linguistic_markers(text)
        assert markers.isolation_references > 0

    def test_low_markers_for_neutral_text(self, processor):
        text = "hoy aprendimos sobre algoritmos de ordenamiento en clase"
        markers = processor.extract_linguistic_markers(text)
        assert markers.negative_emotions == 0
        assert markers.isolation_references == 0
