"""Tests unitarios para el servicio de caché."""

import pytest
from app.services.cache import CacheService


class TestCacheKeys:
    def test_analysis_key(self):
        key = CacheService.analysis_key("abc123")
        assert key == "analysis:abc123"

    def test_student_profile_key(self):
        key = CacheService.student_profile_key("student_42")
        assert key == "student:student_42"

    def test_statistics_key(self):
        key = CacheService.statistics_key()
        assert key == "stats:dashboard"

    def test_hash_text(self):
        h1 = CacheService.hash_text("texto de prueba")
        h2 = CacheService.hash_text("texto de prueba")
        h3 = CacheService.hash_text("otro texto")
        assert h1 == h2  # Determinístico
        assert h1 != h3  # Diferente texto = diferente hash
        assert len(h1) == 16  # Truncado a 16 chars


class TestCacheWithoutRedis:
    """Tests que verifican el comportamiento graceful cuando Redis no está disponible."""

    @pytest.mark.asyncio
    async def test_get_returns_none(self):
        service = CacheService.__new__(CacheService)
        service._redis = None
        result = await service.get("any_key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_does_not_fail(self):
        service = CacheService.__new__(CacheService)
        service._redis = None
        await service.set("key", {"data": 1})  # No debe lanzar excepción

    @pytest.mark.asyncio
    async def test_rate_limit_allows_when_no_redis(self):
        service = CacheService.__new__(CacheService)
        service._redis = None
        allowed, remaining, reset = await service.check_rate_limit("test_ip")
        assert allowed is True

    def test_is_available_false(self):
        service = CacheService.__new__(CacheService)
        service._redis = None
        assert service.is_available is False
