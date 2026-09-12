"""
Servicio de caché con Redis.
Cachea resultados de análisis y consultas frecuentes.
"""

import json
import hashlib
from typing import Optional
from loguru import logger

try:
    import redis.asyncio as aioredis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False
    logger.warning("redis[asyncio] no disponible. Cache desactivado.")

from app.core.config import settings


class CacheService:
    """Servicio de caché con Redis."""

    _instance = None
    _redis = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    async def connect(self):
        """Conecta a Redis."""
        if not REDIS_AVAILABLE:
            return
        if self._redis is not None:
            return
        try:
            self._redis = aioredis.from_url(
                settings.REDIS_URL,
                decode_responses=True,
            )
            await self._redis.ping()
            logger.info("Redis conectado correctamente")
        except Exception as e:
            logger.warning(f"No se pudo conectar a Redis: {e}. Cache desactivado.")
            self._redis = None

    async def disconnect(self):
        """Desconecta de Redis."""
        if self._redis:
            await self._redis.close()
            self._redis = None

    @property
    def is_available(self) -> bool:
        return self._redis is not None

    # === Operaciones de caché ===

    async def get(self, key: str) -> Optional[dict]:
        """Obtiene un valor del caché."""
        if not self.is_available:
            return None
        try:
            value = await self._redis.get(key)
            if value:
                return json.loads(value)
        except Exception as e:
            logger.debug(f"Cache GET error: {e}")
        return None

    async def set(self, key: str, value: dict, ttl: Optional[int] = None):
        """Guarda un valor en caché."""
        if not self.is_available:
            return
        try:
            ttl = ttl or settings.REDIS_CACHE_TTL
            await self._redis.set(key, json.dumps(value, default=str), ex=ttl)
        except Exception as e:
            logger.debug(f"Cache SET error: {e}")

    async def delete(self, key: str):
        """Elimina un valor del caché."""
        if not self.is_available:
            return
        try:
            await self._redis.delete(key)
        except Exception as e:
            logger.debug(f"Cache DELETE error: {e}")

    async def invalidate_pattern(self, pattern: str):
        """Invalida todas las claves que coincidan con un patrón."""
        if not self.is_available:
            return
        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)
            if keys:
                await self._redis.delete(*keys)
                logger.debug(f"Cache invalidated {len(keys)} keys matching {pattern}")
        except Exception as e:
            logger.debug(f"Cache invalidate error: {e}")

    # === Keys helpers ===

    @staticmethod
    def analysis_key(text_hash: str) -> str:
        """Key para resultado de análisis."""
        return f"analysis:{text_hash}"

    @staticmethod
    def student_profile_key(student_id: str) -> str:
        """Key para perfil de estudiante."""
        return f"student:{student_id}"

    @staticmethod
    def statistics_key() -> str:
        """Key para estadísticas del dashboard."""
        return "stats:dashboard"

    @staticmethod
    def hash_text(text: str) -> str:
        """Genera hash de un texto para uso como key."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    # === Rate limiting ===

    async def check_rate_limit(self, identifier: str) -> tuple:
        """
        Verifica rate limit para un identificador (IP o user_id).
        Retorna (allowed: bool, remaining: int, reset_in: int).
        """
        if not self.is_available:
            return True, settings.RATE_LIMIT_REQUESTS, 0

        key = f"ratelimit:{identifier}"
        try:
            current = await self._redis.get(key)
            if current is None:
                await self._redis.set(key, 1, ex=settings.RATE_LIMIT_WINDOW)
                return True, settings.RATE_LIMIT_REQUESTS - 1, settings.RATE_LIMIT_WINDOW

            count = int(current)
            ttl = await self._redis.ttl(key)

            if count >= settings.RATE_LIMIT_REQUESTS:
                return False, 0, ttl

            await self._redis.incr(key)
            return True, settings.RATE_LIMIT_REQUESTS - count - 1, ttl

        except Exception as e:
            logger.debug(f"Rate limit check error: {e}")
            return True, settings.RATE_LIMIT_REQUESTS, 0


# Instancia global
cache = CacheService()
