from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # === General ===
    PROJECT_NAME: str = "MindLMS - Detección Temprana de Salud Mental"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # === Security ===
    SECRET_KEY: str = "change-this-secret-key-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60

    # === CORS ===
    CORS_ORIGINS: List[str] = ["http://localhost:3000", "http://localhost:5173"]

    # === MongoDB ===
    MONGODB_URL: str = "mongodb://localhost:27017"
    MONGODB_DB_NAME: str = "mindlms"

    # === PostgreSQL ===
    POSTGRES_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/mindlms"

    # === Redis ===
    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_CACHE_TTL: int = 3600  # 1 hora en segundos

    # === Moodle LMS ===
    MOODLE_URL: str = "http://localhost:8081"
    MOODLE_TOKEN: str = ""
    MOODLE_WEBHOOK_SECRET: str = "change-this-webhook-secret"

    # === Rate Limiting ===
    RATE_LIMIT_REQUESTS: int = 100  # requests por ventana
    RATE_LIMIT_WINDOW: int = 60    # ventana en segundos

    # === ML Model ===
    MODEL_PATH: str = "ml/data/models"
    MODEL_NAME: str = "roberta-mental-health"
    # Repo del Hugging Face Hub con el RoBERTa fine-tuned (ej:
    # "Fily16/mindlms-roberta-ansiedad"). Si está vacío se usa la carpeta
    # local MODEL_PATH/roberta-finetuned. En despliegue se define esta
    # variable porque el modelo (476 MB) no cabe en GitHub.
    ROBERTA_MODEL_ID: str = ""
    MAX_TEXT_LENGTH: int = 512
    RISK_THRESHOLD_HIGH: float = 0.75
    RISK_THRESHOLD_MEDIUM: float = 0.45

    # === Detección pausada ===
    # Segundos de espera tras cada texto NUEVO analizado. Con ~3 textos
    # por estudiante, 40s ≈ un estudiante nuevo en el dashboard cada
    # ~2 minutos. Poner 0 para analizar sin pausa.
    # Bajado a 0 para la demo: cada mensaje se detecta y muestra al
    # instante en el AnalysisTheater sin retrasos artificiales.
    DETECTION_PACE_SECONDS: int = 0

    # === Entrenamiento automático ===
    # Si no existe un modelo entrenado al arrancar, se entrena el
    # baseline en segundo plano (el psicólogo no gestiona esto).
    AUTO_TRAIN_ON_STARTUP: bool = True

    # === Auto-detección periódica ===
    # Cada N segundos el backend vuelve a escanear Moodle en busca de
    # contenido nuevo. Como el checkpoint deduplica por hash, sólo se
    # analizan textos que aún no han sido vistos (usuarios/mensajes
    # nuevos). Poner 0 para desactivar el auto-scan.
    AUTO_DETECT_INTERVAL_SECONDS: int = 3

    # El auto-scan usa modo QUICK: sólo mensajes directos (1 llamada
    # HTTP) — para tiempo-real barato. Los foros/chats/tareas son
    # cientos de llamadas HTTP → sólo se escanean en el arranque o
    # cuando el psicólogo lo pide manualmente.
    AUTO_DETECT_QUICK_MODE: bool = True

    # Cada N segundos, en vez de un quick-scan, hacemos un FULL-scan
    # (incluye foros, chats y tareas). Gracias al filtro por
    # `timemodified` sólo se piden a Moodle los contenedores con
    # actividad nueva, así que un full ahora dura ~15 segundos
    # (antes ~20 minutos). Se puede correr casi tan seguido como el
    # quick sin castigar al servidor.
    AUTO_DETECT_FULL_INTERVAL_SECONDS: int = 15

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
