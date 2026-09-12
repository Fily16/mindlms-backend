"""Tests unitarios para el clasificador de riesgo."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from app.services.ml.classifier import RiskClassifier
from app.schemas.analysis import RiskLevel


@pytest.fixture
def classifier():
    """Crea un clasificador fresco para cada test."""
    # Reset singleton
    RiskClassifier._instance = None
    RiskClassifier._model = None
    RiskClassifier._tokenizer = None
    RiskClassifier._rf_model = None
    RiskClassifier._mode = "rules"
    return RiskClassifier()


class TestRulesClassifier:
    """Tests para el clasificador basado en reglas (fallback)."""

    @pytest.mark.asyncio
    async def test_low_risk_neutral_text(self, classifier):
        result = await classifier.predict(
            "Hoy tuve una buena clase de programación y aprendí mucho"
        )
        assert result["risk_level"] in (RiskLevel.LOW, RiskLevel.MEDIUM)
        assert 0 <= result["risk_score"] <= 1
        assert 0 <= result["confidence"] <= 1

    @pytest.mark.asyncio
    async def test_high_risk_text(self, classifier):
        result = await classifier.predict(
            "No quiero vivir más, me quiero morir, estoy solo y nadie me necesita"
        )
        assert result["risk_level"] in (RiskLevel.MEDIUM, RiskLevel.HIGH)
        assert result["risk_score"] > 0.3

    @pytest.mark.asyncio
    async def test_flagged_fragments_detected(self, classifier):
        result = await classifier.predict(
            "A veces pienso que quiero morir y que no vale la pena seguir"
        )
        assert "flagged_fragments" in result
        assert len(result["flagged_fragments"]) > 0

    @pytest.mark.asyncio
    async def test_flagged_elevates_low_to_medium(self, classifier):
        """Si hay fragmentos de alto riesgo, el nivel mínimo es medio."""
        result = await classifier.predict(
            "Todo bien pero a veces pienso en suicidio"
        )
        assert result["risk_level"] != RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_confidence_for_rules(self, classifier):
        """El clasificador de reglas debe tener confianza menor."""
        result = await classifier.predict("Me siento triste hoy")
        assert result["confidence"] <= 0.7

    @pytest.mark.asyncio
    async def test_result_structure(self, classifier):
        result = await classifier.predict("Un texto cualquiera para prueba")
        assert "risk_level" in result
        assert "risk_score" in result
        assert "confidence" in result
        assert "flagged_fragments" in result


class TestScoreToLevel:
    def test_high_score(self, classifier):
        assert classifier._score_to_level(0.8) == RiskLevel.HIGH

    def test_medium_score(self, classifier):
        assert classifier._score_to_level(0.5) == RiskLevel.MEDIUM

    def test_low_score(self, classifier):
        assert classifier._score_to_level(0.2) == RiskLevel.LOW

    def test_boundary_high(self, classifier):
        assert classifier._score_to_level(0.75) == RiskLevel.HIGH

    def test_boundary_medium(self, classifier):
        assert classifier._score_to_level(0.45) == RiskLevel.MEDIUM
