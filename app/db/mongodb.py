from loguru import logger
from app.core.config import settings

client = None
db = None

try:
    from motor.motor_asyncio import AsyncIOMotorClient
    MOTOR_AVAILABLE = True
except ImportError:
    MOTOR_AVAILABLE = False
    logger.warning("motor no disponible. MongoDB deshabilitado.")


async def connect_to_mongo():
    global client, db
    if not MOTOR_AVAILABLE:
        logger.warning("MongoDB no disponible (motor no instalado)")
        return
    try:
        client = AsyncIOMotorClient(settings.MONGODB_URL, serverSelectionTimeoutMS=3000)
        # Verificar conexión
        await client.server_info()
        db = client[settings.MONGODB_DB_NAME]
        logger.info("MongoDB conectado correctamente")
    except Exception as e:
        logger.warning(f"MongoDB no disponible: {e}. Continuando sin MongoDB.")
        client = None
        db = None


async def close_mongo_connection():
    global client
    if client:
        client.close()


def get_database():
    return db
