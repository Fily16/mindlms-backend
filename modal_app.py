"""
Despliegue del backend MindLMS en Modal.

Modal ejecuta la MISMA app FastAPI de `app/main.py`, sin cambios en la API.
Este archivo solo describe la imagen, los recursos y los secretos.

Por qué Modal y no una VM: RoBERTa necesita ~2 GB de RAM, que no caben en
los planes gratuitos de los PaaS habituales. Aquí se piden 4 GB y el
contenedor se apaga solo cuando nadie usa el sistema, así que el crédito
mensual se gasta únicamente durante el uso real.

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

Las tres últimas variables son las que evitan que el backend se ponga a
escanear Moodle solo: en un servicio que cobra por segundo, cada arranque
en frío relanzaría ese trabajo y vaciaría el saldo sin que nadie lo pida.
La detección sigue disponible bajo demanda desde el panel.
"""

import modal

# El RoBERTa fine-tuned (480 MB) vive en un volumen de Modal, subido con:
#   modal volume put mindlms-models ml/data/models/roberta-finetuned /roberta-finetuned
# Así no hace falta publicarlo en ningún sitio ni meterlo en la imagen, y
# se puede reemplazar por un modelo reentrenado sin volver a construir.
models = modal.Volume.from_name("mindlms-models")

image = (
    modal.Image.debian_slim(python_version="3.11")
    # Algunas ruedas (bcrypt, asyncpg) compilan si no hay binario para la
    # plataforma; sin estas herramientas el build falla.
    .apt_install("build-essential")
    .pip_install_from_requirements("requirements.txt")
    .add_local_dir("app", remote_path="/root/app")
)

app = modal.App("mindlms-api")


@app.function(
    image=image,
    cpu=2,
    memory=4096,
    secrets=[modal.Secret.from_name("mindlms")],
    # MODEL_PATH=/models hace que el clasificador busque el RoBERTa en
    # /models/roberta-finetuned, que es donde lo monta este volumen.
    volumes={"/models": models},
    # Un contenedor atiende todas las peticiones: el bus de eventos SSE y
    # el estado de las tareas ML viven en memoria del proceso, así que con
    # varios contenedores un cliente conectado no vería los eventos que
    # publica el vecino.
    max_containers=1,
    # Margen para que una conexión SSE abierta no se corte a mitad.
    timeout=3600,
    # Tras 5 minutos sin tráfico el contenedor se apaga y deja de gastar.
    scaledown_window=300,
)
@modal.concurrent(max_inputs=100)
@modal.asgi_app()
def fastapi_app():
    from app.main import app as mindlms

    return mindlms
