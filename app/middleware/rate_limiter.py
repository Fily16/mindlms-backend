"""
Middleware de rate limiting basado en Redis.
Limita requests por IP o por usuario autenticado.

NOTA sobre orden de middlewares en Starlette/FastAPI:
  El ÚLTIMO middleware agregado con app.add_middleware() es el MÁS EXTERNO.
  CORSMiddleware DEBE ser el más externo para que los preflight OPTIONS
  siempre reciban los headers Access-Control-Allow-*.
  Por eso en main.py se agrega PRIMERO RateLimitMiddleware y DESPUÉS CORS.
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from loguru import logger

from app.services.cache import cache
from app.core.config import settings


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Middleware de rate limiting."""

    EXEMPT_PATHS = {"/docs", "/redoc", "/openapi.json", "/health"}

    async def dispatch(self, request: Request, call_next):
        # Siempre dejar pasar preflight CORS (OPTIONS).
        # CORSMiddleware se encarga de responderlos; este middleware
        # no debe interferir ni consumir cuota de rate limit.
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path

        # Exentar rutas de documentación y health check
        if any(path.startswith(p) for p in self.EXEMPT_PATHS):
            return await call_next(request)

        # Exentar webhooks (tienen su propia validación)
        if "/webhook" in path:
            return await call_next(request)

        # Si el cache no está disponible (Redis apagado), dejar pasar
        # sin rate limiting en lugar de bloquear toda la API.
        if not cache.is_available:
            return await call_next(request)

        # Identificar: JWT user_id si autenticado, sino IP.
        identifier = request.client.host if request.client else "unknown"
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            identifier = f"user:{auth_header[-8:]}"

        allowed, remaining, reset_in = await cache.check_rate_limit(identifier)

        if not allowed:
            logger.debug(f"Rate limit excedido para {identifier}")
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Demasiadas solicitudes. Intente de nuevo más tarde.",
                    "retry_after": reset_in,
                },
                headers={
                    "X-RateLimit-Limit": str(settings.RATE_LIMIT_REQUESTS),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(reset_in),
                    "Retry-After": str(reset_in),
                },
            )

        response = await call_next(request)

        # Headers informativos de rate limit
        response.headers["X-RateLimit-Limit"] = str(settings.RATE_LIMIT_REQUESTS)
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-RateLimit-Reset"] = str(reset_in)

        return response
