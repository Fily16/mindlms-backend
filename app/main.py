import os
import asyncio

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from contextlib import asynccontextmanager
from loguru import logger

from app.core.config import settings
from app.api.v1.router import api_router
from app.db.mongodb import connect_to_mongo, close_mongo_connection
from app.db.postgresql import init_db
from app.db.collections import setup_indexes
from app.services.ml.classifier import RiskClassifier
from app.services.cache import cache
from app.middleware.rate_limiter import RateLimitMiddleware


async def _auto_tasks_on_startup():
    """
    Tareas autónomas tras el arranque (el psicólogo no las gestiona):

    1. Entrenamiento automático: si no existe un modelo entrenado,
       se entrena el baseline en segundo plano.
    2. Reanudación de la detección: si el backend se apagó con una
       detección en curso (checkpoint en estado "running"), se relanza
       y continúa exactamente donde se quedó.
    """
    await asyncio.sleep(5)  # dejar que la app termine de calentar
    from app.services.ml.task_manager import MLTaskManager
    from app.services.ml.checkpoint import detection_checkpoint

    manager = MLTaskManager()

    if settings.AUTO_TRAIN_ON_STARTUP:
        backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        model_file = os.path.join(
            backend_dir, "ml", "data", "models", "random_forest.pkl"
        )
        if not os.path.exists(model_file):
            logger.info("No hay modelo entrenado: iniciando auto-entrenamiento...")
            try:
                await manager.start_training("baseline")
            except RuntimeError:
                pass  # ya hay un entrenamiento corriendo

    # Detección inicial al arrancar:
    # - Si el checkpoint está VACÍO (primera vez) → escaneo COMPLETO.
    # - Si ya hay checkpoint (incluso "interrumpido" por un reload) →
    #   modo QUICK. Los foros/chats/tareas ya están en el checkpoint;
    #   el auto-scan de mensajes directos atrapa lo nuevo. Reanudar
    #   con FULL sólo tiene sentido si nunca se completó ni un ciclo.
    if not settings.AUTO_DETECT_ON_STARTUP:
        # En un hosting que cobra por segundo y apaga el contenedor cuando
        # nadie usa el sistema, cada arranque en frío relanzaría esta
        # detección y consumiría saldo sin que nadie lo pida.
        logger.info("Detección automática al arrancar desactivada por configuración")
        return

    need_full = detection_checkpoint.processed_count == 0
    logger.info(
        f"Iniciando detección automática "
        f"({detection_checkpoint.processed_count} textos ya en checkpoint, "
        f"mode={'FULL' if need_full else 'QUICK'})..."
    )
    try:
        await manager.start_detection(quick=not need_full)
    except RuntimeError:
        pass  # ya hay una detección corriendo


async def _periodic_moodle_scan():
    """
    Loop autónomo que re-escanea Moodle cada N segundos buscando
    contenido nuevo (usuarios, mensajes, foros).  Es la manera de
    "escuchar Moodle en vivo" sin webhooks: el checkpoint deduplica
    por hash, así que sólo se analizan textos aún no vistos.

    Si el psicólogo agrega un mensaje a un estudiante en Moodle, en el
    siguiente tick (a lo sumo AUTO_DETECT_INTERVAL_SECONDS segundos) el
    sistema lo detecta y emite el SSE `new_alert`.
    """
    from app.services.ml.task_manager import MLTaskManager, TaskType

    if settings.AUTO_DETECT_INTERVAL_SECONDS <= 0:
        logger.info("Auto-scan periódico desactivado (interval=0).")
        return

    manager = MLTaskManager()
    interval = settings.AUTO_DETECT_INTERVAL_SECONDS
    logger.info(
        f"Auto-scan de Moodle activo: cada {interval}s se busca contenido nuevo."
    )

    # dejar que la detección inicial termine antes del primer tick
    await asyncio.sleep(interval)

    # Alternancia: la mayoría de ticks son QUICK (rápido, mensajes
    # directos). Cada N segundos se hace un FULL (incluye foros, chats,
    # tareas). Así se atrapa contenido nuevo en cualquier fuente.
    default_quick = settings.AUTO_DETECT_QUICK_MODE
    full_every = max(
        settings.AUTO_DETECT_FULL_INTERVAL_SECONDS // max(interval, 1), 0
    )
    tick = 0
    while True:
        tick += 1
        # Full si toca por cadencia (y el usuario no lo desactivó)
        do_full = (
            full_every > 0
            and (tick % full_every == 0)
            and default_quick  # sólo si por default estamos en quick
        ) or (not default_quick)

        try:
            if not manager.is_busy(TaskType.DETECTION):
                await manager.start_detection(quick=not do_full)
        except RuntimeError:
            pass  # corrida en paralelo
        except Exception as e:
            logger.warning(f"Auto-scan tick falló: {e}")

        await asyncio.sleep(interval)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events."""
    logger.info("Iniciando MindLMS API...")

    # Startup - Base de datos
    await connect_to_mongo()
    # PostgreSQL: si no responde, la API arranca igual y sirve lo que no
    # dependa de él. Las BD gestionadas gratuitas (Aiven) se apagan por
    # inactividad, y un fallo aquí tumbaría todo el proceso.
    try:
        await init_db()
    except Exception as e:
        logger.error(f"PostgreSQL no disponible al arrancar: {e}")
    await setup_indexes()
    logger.info("Bases de datos conectadas y configuradas")

    # Startup - Redis cache
    await cache.connect()

    # Startup - Modelo ML
    classifier = RiskClassifier()
    await classifier.load_model()
    logger.info("Modelo ML cargado")

    # Startup - Tareas autónomas (auto-entrenamiento + reanudar detección)
    asyncio.create_task(_auto_tasks_on_startup())
    # Escaneo periódico de Moodle: detecta contenido nuevo sin reiniciar
    asyncio.create_task(_periodic_moodle_scan())

    yield

    # Shutdown
    await cache.disconnect()
    await close_mongo_connection()
    logger.info("MindLMS API detenida")


app = FastAPI(
    title=settings.PROJECT_NAME,
    description=(
        "API para la detección temprana de ansiedad y estrés "
        "en estudiantes dentro de plataformas educativas mediante PLN y ML."
    ),
    version="0.1.0",
    lifespan=lifespan,
)

# ── Middlewares ──────────────────────────────────────────────
# Starlette ejecuta el ÚLTIMO add_middleware como el más EXTERNO.
# CORS debe ser el más externo para que SIEMPRE inyecte
# Access-Control-Allow-* en la respuesta (incluido preflight OPTIONS).
# Rate limiter va primero (interno) para no interferir con CORS.
app.add_middleware(RateLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
)

# ── Manejo global de errores ────────────────────────────────
# Captura excepciones no controladas para que SIEMPRE devuelvan
# JSON con status 500 en lugar de un "Internal Server Error" plano.
# CORSMiddleware (outer) añade los headers CORS a ESTA respuesta,
# evitando que el browser muestre un falso "CORS error".
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Error no manejado en {request.method} {request.url.path}: {exc}")
    return JSONResponse(
        status_code=500,
        content={"detail": "Error interno del servidor"},
    )


# Registrar rutas
app.include_router(api_router, prefix="/api/v1")


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "version": "0.1.0",
        "cache": "connected" if cache.is_available else "disconnected",
    }
