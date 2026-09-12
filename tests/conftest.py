"""
Configuración global de pytest.
Fixtures compartidos entre tests unitarios e integración.
"""

import sys
import os
import pytest

# Asegurar que el directorio backend está en el path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture(autouse=True)
def reset_singletons():
    """Reset singletons entre tests para evitar estado compartido."""
    from app.services.ml.classifier import RiskClassifier
    RiskClassifier._instance = None
    RiskClassifier._model = None
    RiskClassifier._tokenizer = None
    RiskClassifier._rf_model = None
    RiskClassifier._mode = "rules"

    from app.services.cache import CacheService
    CacheService._instance = None
    CacheService._redis = None

    yield
