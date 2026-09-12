FROM python:3.11-slim

WORKDIR /app

# Instalar dependencias del sistema
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements e instalar dependencias Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# El modelo de spaCy es_core_news_sm ya viene fijado en requirements.txt

# Copiar código fuente
COPY . .

EXPOSE 8000

# Formato shell para poder respetar $PORT (lo inyectan los PaaS).
# Un solo worker: el bus de eventos SSE, el estado de tareas ML y el
# checkpoint son singletons en memoria de proceso, así que con varios
# workers un cliente SSE no vería los eventos del worker vecino.
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1
