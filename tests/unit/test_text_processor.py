"""Tests unitarios para el procesador de texto NLP."""

import pytest
from app.services.nlp import text_processor as tp_module
from app.services.nlp.text_processor import TextProcessor


@pytest.fixture
def processor():
    return TextProcessor()


@pytest.fixture(params=[True, False], ids=["con_spacy", "sin_spacy"])
def anonymizer(request, monkeypatch):
    """Anonimizador con y sin spaCy: el ambiente desplegado puede no tenerlo."""
    if request.param and not tp_module.SPACY_AVAILABLE:
        pytest.skip("spaCy no instalado")
    monkeypatch.setattr(tp_module, "SPACY_AVAILABLE", request.param)
    processor = TextProcessor()
    return lambda text: processor.anonymize_text(processor.clean_text(text))


class TestAnonymizeNames:
    """HU0033 / DEV-01: el nombre de la persona no debe quedar en el texto guardado."""

    @pytest.mark.parametrize(
        "text, expected",
        [
            (
                "Hola, soy Juan Pérez, mi correo es juan.perez@upc.edu.pe y mi DNI es 12345678. Me siento muy solo.",
                "Hola, soy [NOMBRE], mi correo es [EMAIL] y mi DNI es [DNI]. Me siento muy solo.",
            ),
            (
                "Hola, soy Juan Perez, mi correo es juan.perez@upc.edu.pe y mi DNI es 12345678. Me siento muy solo.",
                "Hola, soy [NOMBRE], mi correo es [EMAIL] y mi DNI es [DNI]. Me siento muy solo.",
            ),
            (
                "Hola, soy juan perez, mi correo es juan.perez@upc.edu.pe y mi DNI es 12345678. Me siento muy solo.",
                "Hola, soy [NOMBRE], mi correo es [EMAIL] y mi DNI es [DNI]. Me siento muy solo.",
            ),
            ("Hola, me llamo Ana María Torres y necesito ayuda.", "Hola, me llamo [NOMBRE] y necesito ayuda."),
            ("Mi nombre es Luis Gómez y estoy cansado.", "Mi nombre es [NOMBRE] y estoy cansado."),
            ("Soy Juan de la Cruz, no puedo más.", "Soy [NOMBRE], no puedo más."),
        ],
    )
    def test_enmascara_el_nombre(self, anonymizer, text, expected):
        assert anonymizer(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "Hola a todos, ¿alguien sabe hasta qué hora se puede subir la tarea del foro? Ref. 18:14",
            "Ya no puedo más con todo esto, me siento completamente solo y siento que nada tiene sentido. Ref. 18:20",
            "Estoy muy estresado por los exámenes, no duermo bien y me preocupa desaprobar el curso. Ref. 18:14",
            "Soy estudiante de Programación Avanzada y estoy cansado de Cálculo Diferencial.",
            "soy muy malo en esto, soy del curso de Física I",
            "Hoy me llamo la atención el profesor.",
            "SOY PESIMO ALUMNO",
        ],
    )
    def test_no_altera_textos_sin_nombre(self, anonymizer, text):
        assert anonymizer(text) == TextProcessor().clean_text(text)

    def test_fragmentos_de_alto_riesgo_sin_nombre(self, anonymizer):
        anonimizado = anonymizer("Soy Juan Pérez y ya no puedo más con todo")
        fragmentos = TextProcessor().detect_high_risk_fragments(anonimizado)
        assert fragmentos and all("juan" not in f and "pérez" not in f for f in fragmentos)


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
