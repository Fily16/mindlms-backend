"""
Despliegue del backend MindLMS en Modal.

Modal ejecuta la MISMA app FastAPI de `app/main.py`, sin cambios en la API.
Este archivo solo describe la imagen, los recursos y los secretos.

Por qué Modal y no una VM: RoBERTa necesita ~2 GB de RAM, que no caben en
los planes gratuitos de los PaaS habituales. Aquí se piden 4 GB y el
contenedor se apaga solo cuando nadie usa el sistema, así que el crédito
mensual cubre el consumo según el tiempo de ejecución.

Primer despliegue:

    pip install modal
    python -m modal setup

    modal volume create mindlms-models
    modal volume put mindlms-models \\
        ml/data/models/roberta-finetuned /roberta-finetuned

    modal secret create mindlms \\
        POSTGRES_URL=... MONGODB_URL=... SECRET_KEY=... \\
        MODEL_PATH=/models \\
        MOODLE_URL=... MOODLE_TOKEN=... \\
        CORS_ORIGINS='["https://mindlms-frontend.vercel.app"]' \\
        DEBUG=false AUTO_TRAIN_ON_STARTUP=false \\
        AUTO_DETECT_ON_STARTUP=false AUTO_DETECT_INTERVAL_SECONDS=0
    modal deploy modal_app.py

La detección automática se habilita explícitamente en fastapi_app para el
despliegue actual. No se habilita el entrenamiento automático.

Detección automática "mientras se usa":
    El contenedor NO queda encendido 24/7 (min_containers=0). Mientras
    alguien tiene el panel abierto, la conexión en vivo (SSE) lo mantiene
    encendido y el escaneo corre cada 30 s; al cerrar el panel se apaga a
    los 5 minutos y deja de gastar. Al volver a abrirlo, la detección de
    arranque revisa lo que se escribió en Moodle mientras estaba apagado,
    y el checkpoint en el volumen mindlms-detection-state evita volver a
    analizar lo ya visto.

    Por qué no 24/7: Modal cobra por tiempo encendido (lo mayor entre lo
    reservado y lo usado), así que 2 núcleos + 4 GB encendidos siempre
    cuestan ~$3/día y agotan los $30 mensuales en ~10 días, escaneen o no.
    Además cada escaneo descarga ~6 MB/min del Moodle de Railway aunque no
    haya nada nuevo, y el tráfico de salida de Railway se cobra por GB.
"""

import modal

# El RoBERTa fine-tuned (480 MB) vive en un volumen de Modal, subido con:
#   modal volume put mindlms-models ml/data/models/roberta-finetuned /roberta-finetuned
# Así no hace falta publicarlo en ningún sitio ni meterlo en la imagen, y
# se puede reemplazar por un modelo reentrenado sin volver a construir.
models = modal.Volume.from_name("mindlms-models")
detection_state = modal.Volume.from_name("mindlms-detection-state")

image = (
    modal.Image.debian_slim(python_version="3.11")
    # Algunas ruedas (bcrypt, asyncpg) compilan si no hay binario para la
    # plataforma; sin estas herramientas el build falla.
    .apt_install("build-essential")
    # torch CPU explícito: en Linux, `pip install torch` arrastra por
    # defecto los paquetes de CUDA (varios GB) que aquí no sirven de nada
    # porque no hay GPU. Instalarlo antes deja satisfecho el requirement.
    .pip_install("torch==2.6.0", index_url="https://download.pytorch.org/whl/cpu")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("app", remote_path="/root/app")
)

app = modal.App("mindlms-api")


@app.function(
    image=image,
    cpu=2,
    memory=4096,
    secrets=[
        modal.Secret.from_name("mindlms"),
        # Conexion recuperada; conserva sin cambios Moodle, JWT y demas secretos.
        modal.Secret.from_name("mindlms-database-recovery"),
    ],
    # MODEL_PATH=/models hace que el clasificador busque el RoBERTa en
    # /models/roberta-finetuned, que es donde lo monta este volumen.
    volumes={"/models": models, "/root/data": detection_state},
    # Un contenedor atiende todas las peticiones: el bus de eventos SSE y
    # el estado de las tareas ML viven en memoria del proceso, así que con
    # varios contenedores un cliente conectado no vería los eventos que
    # publica el vecino.
    max_containers=1,
    # Sin contenedor fijo: se enciende cuando alguien usa el panel y el
    # escaneo automático corre mientras siga encendido. Con 1 quedaría
    # encendido 24/7 (~$3/día en Modal, ver docstring).
    min_containers=0,
    # Margen para que una conexión SSE abierta no se corte a mitad.
    timeout=3600,
    # Tras 5 minutos sin nadie conectado el contenedor se apaga y deja de gastar.
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def fastapi_app():
    import os

    # Debe aplicarse antes de importar Settings y construir el engine SQLAlchemy.
    os.environ["POSTGRES_URL"] = os.environ["MINDLMS_POSTGRES_URL"]
    os.environ.update({
        "AUTO_TRAIN_ON_STARTUP": "false",
        "AUTO_DETECT_ON_STARTUP": "true",
        "AUTO_DETECT_INTERVAL_SECONDS": "30",
        "AUTO_DETECT_QUICK_MODE": "false",
        "AUTO_DETECT_FULL_INTERVAL_SECONDS": "30",
        "DETECTION_PACE_SECONDS": "0",
    })
    from app.main import app as mindlms

    return mindlms
