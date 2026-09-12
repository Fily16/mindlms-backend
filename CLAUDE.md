# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Proyecto

**MindLMS** - API para detección temprana de ansiedad y estrés en estudiantes dentro de plataformas educativas (Moodle) mediante PLN y ML. Tesis de Ingeniería de Sistemas en UPC.

Stack: FastAPI + Python 3.11, PostgreSQL (SQLAlchemy async), MongoDB (Motor async), Redis (caché + rate limiting), PyTorch + Transformers (RoBERTa), spaCy (español).

## Comandos

```bash
# Servidor de desarrollo
uvicorn app.main:app --reload --port 8000

# Tests
pytest                          # todos los tests
pytest tests/unit/              # solo unitarios
pytest tests/integration/       # solo integración
pytest tests/unit/test_classifier.py -v  # un archivo específico
pytest -k "test_clean_text"     # un test por nombre

# Pipeline ML (ejecutar como módulos desde backend/)
python -m ml.data.pipeline.download_datasets --output_dir ml/data/raw
python -m ml.data.pipeline.preprocess --input_dir ml/data/raw --output_dir ml/data/processed
python -m ml.training.train_baseline --data_path ml/data/processed/train.csv
python -m ml.training.train_roberta --data_path ml/data/processed/train.csv --epochs 5

# Scripts utilitarios
python scripts/create_psychologist.py       # crear usuario psicólogo
python scripts/seed_courses_users.py        # seed de datos en Moodle
python scripts/test_moodle_connection.py    # verificar conexión Moodle
python scripts/bootstrap_detection_checkpoint.py  # registrar contenido actual de Moodle como ya procesado
```

## Arquitectura

### Flujo principal de análisis

Texto de Moodle llega por **webhook** (`POST /api/v1/moodle/webhook`) o por **sincronización manual** (`POST /api/v1/moodle/courses/{id}/sync`). El flujo es:

1. `MoodleWebhookHandler` valida firma HMAC y parsea el evento
2. `AnalysisService.analyze_text()` orquesta el pipeline completo:
   - Deduplicación por SHA-256 del texto (consulta MongoDB)
   - `TextProcessor`: limpieza, anonimización (Ley 29733), extracción de marcadores lingüísticos
   - `RiskClassifier`: clasificación con RoBERTa > Random Forest > reglas (fallback en cascada)
   - Almacenamiento en MongoDB (texto analizado + perfil del estudiante)
   - Creación de alerta en PostgreSQL
3. `DetectionEventBus` notifica al frontend vía SSE (`GET /api/v1/ml/detect/events`)

### Base de datos dual

- **PostgreSQL** (SQLAlchemy async): datos relacionales - `users`, `alerts`, `alert_notes`. Modelos en `app/models/`.
- **MongoDB** (Motor async): datos de análisis - colecciones `analyzed_texts`, `student_profiles`, `analysis_history`. Schemas en `app/db/collections.py`.
- Ambas bases son opcionales al arrancar: si no están disponibles, la app continúa con funcionalidad degradada.

### Clasificador ML (`app/services/ml/classifier.py`)

Singleton con carga lazy. Tres modos en cascada:
1. **transformer**: RoBERTa fine-tuned desde `ml/data/models/roberta-finetuned/`
2. **random_forest**: Random Forest + TF-IDF desde `ml/data/models/random_forest.pkl`
3. **rules**: score compuesto basado en marcadores lingüísticos (fallback sin modelo entrenado)

Si hay fragmentos de alto riesgo (patrones regex en `HIGH_RISK_PATTERNS`), el nivel mínimo se eleva a "medio".

### Tareas en segundo plano (`app/services/ml/task_manager.py`)

Entrenamiento y detección se ejecutan como tareas async en background. El frontend consulta el estado vía polling (`GET /api/v1/ml/train/status`, `GET /api/v1/ml/detect/status`) y recibe alertas nuevas por SSE.

### Detección pausada + checkpoint (`app/services/ml/checkpoint.py`)

- La detección espera `DETECTION_PACE_SECONDS` (default 40s) tras cada texto NUEVO analizado: el dashboard ve llegar los casos uno a uno.
- `data/detection_checkpoint.json` guarda el hash SHA-256 de cada texto procesado: es la deduplicación (MongoDB no siempre está disponible) y el punto de reanudación. Si el backend se apaga a mitad de una detección, `main.py` la reanuda automáticamente al arrancar.
- `scripts/bootstrap_detection_checkpoint.py` registra el contenido actual de Moodle sin analizarlo (corre una vez antes de sembrar datos nuevos).
- El entrenamiento es automático: al arrancar, si no existe `ml/data/models/random_forest.pkl`, se entrena el baseline (`AUTO_TRAIN_ON_STARTUP`). El frontend ya no tiene botón de entrenar.

### Datos reales del formulario de validación

`moodle-data-generator/scripts/05_seed_validation_form.py` siembra las respuestas reales del formulario (Excel) como mensajes directos con prefijo `[VALIDACION]`. El extractor lo detecta, lo quita del texto y etiqueta `source="formulario_validacion"` → el dashboard muestra el sello "DATOS REALES". El evento SSE `new_alert` incluye `source`.

### API endpoints (prefijo `/api/v1`)

| Grupo       | Prefijo      | Descripción                                      |
|-------------|-------------|--------------------------------------------------|
| Auth        | `/auth`     | Login JWT, datos del usuario actual               |
| Alertas     | `/alerts`   | CRUD de alertas, notas de psicólogo, estadísticas |
| Estudiantes | `/students` | Perfiles de riesgo, historial, estadísticas       |
| Moodle      | `/moodle`   | Sincronización de cursos, webhooks                |
| ML          | `/ml`       | Entrenar modelo, ejecutar detección, SSE          |

### Servicios Moodle (`app/services/moodle/`)

- `client.py`: cliente httpx async para Moodle Web Services (foros, chats, tareas, mensajes directos)
- `text_extractor.py`: extrae textos de las distintas fuentes de un curso
- `webhook_handler.py`: parsea eventos de Moodle, filtra por tipo y relevancia
- `sync_service.py`: orquesta extracción + análisis por curso

## Configuración

Variables de entorno en `.env` (ver `.env.example`). Clase `Settings` en `app/core/config.py` con valores por defecto para desarrollo local. Umbrales de riesgo: `RISK_THRESHOLD_HIGH=0.75`, `RISK_THRESHOLD_MEDIUM=0.45`.

## Tests

pytest con `asyncio_mode = auto`. El fixture `reset_singletons` en `conftest.py` resetea los singletons (RiskClassifier, CacheService) entre tests. Los tests usan mocks para MongoDB, Redis y Moodle.

## Idioma

Todo el proyecto está en español: variables, comentarios, mensajes de error de la API, respuestas al usuario, datos de prueba. Los niveles de riesgo son "bajo", "medio", "alto". Los estados de alerta son "pendiente", "revisada", "en_seguimiento", "resuelta".
