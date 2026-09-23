"""
Gestor de tareas en segundo plano para entrenamiento y detección.
Usa un dict en memoria para rastrear el estado de cada tarea.
"""

import asyncio
import subprocess
import sys
import os
import json
from enum import Enum
from datetime import datetime, UTC
from typing import Optional
from dataclasses import dataclass, field, asdict
from loguru import logger


class TaskType(str, Enum):
    TRAINING = "training"
    DETECTION = "detection"


class TaskState(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class TaskStatus:
    state: TaskState = TaskState.IDLE
    task_type: Optional[TaskType] = None
    current_step: str = ""
    progress: int = 0  # 0-100
    steps_completed: int = 0
    total_steps: int = 0
    logs: list[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        d = asdict(self)
        # Limitar logs a los últimos 30 para no saturar el frontend
        d["logs"] = d["logs"][-30:]
        return d


class MLTaskManager:
    """Singleton que gestiona las tareas de ML en segundo plano."""

    _instance: Optional["MLTaskManager"] = None
    _lock = asyncio.Lock()

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._training = TaskStatus()
            cls._instance._detection = TaskStatus()
            cls._instance._current_process: Optional[asyncio.subprocess.Process] = None
            # Detección pedida por un aviso de Moodle mientras otra corría:
            # None = nada pendiente; True/False = el modo quick pendiente.
            cls._instance._pending_quick: Optional[bool] = None
        return cls._instance

    def get_status(self, task_type: TaskType) -> TaskStatus:
        if task_type == TaskType.TRAINING:
            return self._training
        return self._detection

    def is_busy(self, task_type: TaskType) -> bool:
        status = self.get_status(task_type)
        return status.state == TaskState.RUNNING

    async def start_training(self, model_type: str = "baseline"):
        """Inicia el pipeline de entrenamiento en segundo plano."""
        if self.is_busy(TaskType.TRAINING):
            raise RuntimeError("Ya hay un entrenamiento en ejecución")

        self._training = TaskStatus(
            state=TaskState.RUNNING,
            task_type=TaskType.TRAINING,
            current_step="Iniciando pipeline de entrenamiento...",
            total_steps=3,
            started_at=datetime.now(UTC).isoformat(),
        )

        asyncio.create_task(self._run_training_pipeline(model_type))

    async def start_detection(self, quick: bool = False):
        """
        Inicia la sincronización + detección con Moodle.

        Con quick=True se salta el escaneo profundo de foros/chats/tareas
        (cientos de llamadas HTTP) y sólo se leen mensajes directos
        (1 llamada). Ideal para el auto-scan periódico de tiempo real.
        """
        if self.is_busy(TaskType.DETECTION):
            raise RuntimeError("Ya hay una detección en ejecución")

        self._detection = TaskStatus(
            state=TaskState.RUNNING,
            task_type=TaskType.DETECTION,
            current_step="Conectando con Moodle...",
            total_steps=3,
            started_at=datetime.now(UTC).isoformat(),
        )

        asyncio.create_task(self._run_detection_and_pending(quick=quick))

    async def request_detection(self, quick: bool = False) -> str:
        """
        Pide una detección desde un aviso de Moodle (webhook).

        Si no hay ninguna corriendo, arranca ya. Si hay una en curso, deja
        otra pendiente para cuando termine: la corrida actual pudo leer
        Moodle antes de que existiera el texto que motivó el aviso. Varios
        avisos seguidos se agrupan en UNA sola corrida pendiente, y basta
        con que uno pida modo completo para que la pendiente sea completa.
        """
        if not self.is_busy(TaskType.DETECTION):
            await self.start_detection(quick=quick)
            return "started"
        if self._pending_quick is None:
            self._pending_quick = quick
        else:
            self._pending_quick = self._pending_quick and quick
        return "queued"

    async def _run_detection_and_pending(self, quick: bool):
        await self._run_detection_pipeline(quick=quick)
        pending, self._pending_quick = self._pending_quick, None
        if pending is not None:
            try:
                await self.start_detection(quick=pending)
            except RuntimeError:
                pass  # otra corrida arrancó en medio y ya leerá lo nuevo

    async def _run_training_pipeline(self, model_type: str):
        """Ejecuta el pipeline completo: download → preprocess → train."""
        backend_dir = os.path.dirname(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        steps = [
            {
                "name": "Generando dataset sintético",
                "cmd": [
                    sys.executable, "-m", "ml.data.pipeline.download_datasets",
                    "--output_dir", "ml/data/raw",
                ],
            },
            {
                "name": "Preprocesando textos",
                "cmd": [
                    sys.executable, "-m", "ml.data.pipeline.preprocess",
                    "--input_dir", "ml/data/raw",
                    "--output_dir", "ml/data/processed",
                ],
            },
        ]

        # Elegir script de entrenamiento según el tipo
        if model_type == "roberta":
            steps.append({
                "name": "Entrenando modelo RoBERTa",
                "cmd": [
                    sys.executable, "-m", "ml.training.train_roberta",
                    "--data_path", "ml/data/processed/train.csv",
                    "--epochs", "3",
                ],
            })
        else:
            steps.append({
                "name": "Entrenando modelo baseline (Random Forest)",
                "cmd": [
                    sys.executable, "-m", "ml.training.train_baseline",
                    "--data_path", "ml/data/processed/train.csv",
                ],
            })

        self._training.total_steps = len(steps)

        try:
            for i, step in enumerate(steps):
                self._training.current_step = step["name"]
                self._training.steps_completed = i
                self._training.progress = int((i / len(steps)) * 100)
                self._training.logs.append(f"[Paso {i + 1}/{len(steps)}] {step['name']}")
                logger.info(f"ML Training step {i + 1}: {step['name']}")

                returncode = await self._run_subprocess(
                    step["cmd"], backend_dir, TaskType.TRAINING
                )

                if returncode != 0:
                    raise RuntimeError(
                        f"Paso '{step['name']}' falló con código {returncode}"
                    )

            # Verificar que el modelo se generó
            model_path = os.path.join(backend_dir, "ml", "data", "models")
            if model_type == "roberta":
                expected = os.path.join(model_path, "roberta-finetuned", "config.json")
            else:
                expected = os.path.join(model_path, "random_forest.pkl")

            model_exists = os.path.exists(expected)

            self._training.state = TaskState.COMPLETED
            self._training.progress = 100
            self._training.steps_completed = len(steps)
            self._training.current_step = "Entrenamiento completado"
            self._training.finished_at = datetime.now(UTC).isoformat()
            self._training.result = {
                "model_type": model_type,
                "model_saved": model_exists,
                "model_path": model_path,
            }

            # Intentar leer el reporte si existe
            report_file = "baseline_report.json" if model_type != "roberta" else "roberta-finetuned/training_report.json"
            report_path = os.path.join(model_path, report_file)
            if os.path.exists(report_path):
                with open(report_path) as f:
                    self._training.result["report"] = json.load(f)

            self._training.logs.append("✓ Entrenamiento completado exitosamente")
            logger.info("ML Training pipeline completed successfully")

        except Exception as e:
            self._training.state = TaskState.FAILED
            self._training.error = str(e)
            self._training.current_step = f"Error: {str(e)}"
            self._training.finished_at = datetime.now(UTC).isoformat()
            self._training.logs.append(f"✗ Error: {str(e)}")
            logger.error(f"ML Training pipeline failed: {e}")

    # ── helpers para detección incremental ──────────────────────────

    async def _analyze_texts_immediate(
        self, texts: list, admin_user_id: str,
        course_id: int, course_name: str, counters: dict,
    ):
        """
        Analiza una lista de textos y guarda alertas al instante.

        - Salta los textos ya registrados en el checkpoint (deduplicación
          persistente: re-ejecutar o reanudar nunca duplica alertas).
        - Tras cada texto NUEVO analizado espera DETECTION_PACE_SECONDS:
          el dashboard ve llegar los casos uno a uno, en tiempo real,
          en lugar de recibir todo de golpe.
        """
        from app.core.config import settings
        from app.services.analysis_service import AnalysisService
        from app.services.ml.events import detection_event_bus
        from app.services.ml.checkpoint import detection_checkpoint
        from app.db.postgresql import async_session

        if not texts:
            return

        pace = max(int(getattr(settings, "DETECTION_PACE_SECONDS", 40)), 0)

        async with async_session() as session:
            service = AnalysisService(session)
            for entry in texts:
                sid = entry["student_id"]
                if sid == admin_user_id:
                    continue

                # ── Checkpoint: ya procesado en una corrida anterior ──
                if detection_checkpoint.has(entry["text"]):
                    counters["skipped"] = counters.get("skipped", 0) + 1
                    continue

                counters["texts"] += 1
                try:
                    result = await service.analyze_text(
                        text=entry["text"],
                        student_id=sid,
                        student_name=entry.get("student_name", ""),
                        source=entry["source"],
                        course_id=str(course_id),
                        course_name=course_name,
                    )
                    counters["analyzed"] += 1
                    if result.get("risk_level") in ("medio", "alto"):
                        counters["alerts"] += 1

                    # Registrar en el checkpoint (persiste al instante:
                    # si se corta la luz aquí, este texto no se repite)
                    detection_checkpoint.add(entry["text"])

                    # ── Notificar al frontend via SSE (todos los niveles) ──
                    # Payload enriquecido: el frontend abre un "teatro de
                    # análisis" que muestra el texto, marcadores, score
                    # y flagged fragments en tiempo real.
                    await detection_event_bus.publish({
                        "type": "new_alert",
                        "student_id": sid,
                        "student_name": entry.get("student_name", ""),
                        "risk_level": result.get("risk_level", "bajo"),
                        "risk_score": result.get("risk_score", 0.0),
                        "confidence": result.get("confidence", 0.0),
                        "text": entry.get("text", ""),
                        "source": entry.get("source", ""),
                        "course_name": course_name,
                        "linguistic_markers": result.get(
                            "linguistic_markers", {}
                        ),
                        "matched_words": result.get("matched_words", {}),
                        "flagged_fragments": result.get(
                            "flagged_fragments", []
                        ),
                        "word_count": result.get("word_count", 0),
                        "char_count": result.get("char_count", 0),
                        "model_backend": result.get("model_backend", "transformer"),
                        "counters": counters.copy(),
                    })

                    # ── Ritmo pausado: el psicólogo ve llegar los casos
                    #    de a pocos (configurable en .env) ──
                    if pace:
                        self._detection.current_step = (
                            f"Analizado: {entry.get('student_name', 'estudiante')}"
                            f" — esperando siguiente texto..."
                        )
                        await asyncio.sleep(pace)
                except Exception as e:
                    counters["errors"] += 1
                    logger.warning(f"Error analizando texto: {e}")

    def _update_detection_result(self, counters: dict, course_count: int):
        """Actualiza el resultado incremental visible desde el frontend."""
        self._detection.result = {
            "courses_total": course_count,
            "total_texts": counters["texts"],
            "analyzed": counters["analyzed"],
            "alerts_generated": counters["alerts"],
            "students_processed": counters["students"],
            "errors": counters["errors"],
            "skipped": counters.get("skipped", 0),
        }

    # ── pipeline principal ───────────────────────────────────────

    async def _run_detection_pipeline(self, quick: bool = False):
        """
        Detección incremental: cada estudiante procesado se guarda
        al instante en PostgreSQL y es visible en el dashboard.

        quick=True: sólo mensajes directos (1 llamada HTTP). Los foros/
        chats/tareas son cientos de llamadas HTTP y se omiten para no
        castigar el auto-scan periódico.
        """
        from app.services.moodle.client import MoodleClient, MoodleAPIError
        from app.services.moodle.text_extractor import MoodleTextExtractor
        from app.services.ml.checkpoint import detection_checkpoint
        from app.db.postgresql import async_session
        from app.models.alert import Alert
        from sqlalchemy import delete

        # Marcar la corrida como "running" en disco: si el backend se
        # apaga a mitad, al reiniciar main.py la reanuda automáticamente.
        detection_checkpoint.set_state("running")

        try:
            # ── Paso 1: Conectar con Moodle ──────────────────────
            mode_tag = "QUICK (solo mensajes directos)" if quick else "FULL (foros + chats + tareas + mensajes)"
            self._detection.current_step = f"Conectando con Moodle... [{mode_tag}]"
            self._detection.steps_completed = 0
            self._detection.progress = 5
            self._detection.logs.append(f"[1/4] Conectando con Moodle... modo={mode_tag}")

            # Capturar el timestamp de INICIO de la corrida. Al terminar
            # lo usaremos como marca del checkpoint (con margen) para que
            # cualquier post creado DURANTE la corrida no quede en el
            # "hueco" entre inicio y fin y sea procesado en la siguiente.
            import time as _time_module
            run_start_ts = int(_time_module.time())

            client = MoodleClient()
            site_info = await client.get_site_info()
            admin_user_id = str(site_info.get("userid", ""))
            logger.info(f"Admin user ID (excluido): {admin_user_id}")

            courses = await client.get_courses()
            course_count = len(courses)
            self._detection.logs.append(f"  -> {course_count} cursos encontrados")

            if course_count == 0:
                self._detection.state = TaskState.COMPLETED
                self._detection.progress = 100
                self._detection.current_step = "No hay cursos"
                self._detection.finished_at = datetime.now(UTC).isoformat()
                self._detection.result = {
                    "courses_total": 0, "total_texts": 0,
                    "analyzed": 0, "alerts_generated": 0,
                    "students_processed": 0, "errors": 0,
                }
                return

            # ── Paso 2: Limpiar alertas previas del admin ────────
            self._detection.current_step = "Limpiando alertas del administrador..."
            self._detection.progress = 8
            self._detection.logs.append("[2/4] Limpiando alertas del admin...")

            async with async_session() as session:
                del_result = await session.execute(
                    delete(Alert).where(Alert.student_id == admin_user_id)
                )
                await session.commit()
                deleted = del_result.rowcount
                if deleted:
                    self._detection.logs.append(
                        f"  -> {deleted} alertas del admin eliminadas"
                    )

            # ── Paso 3: Extraer y analizar INCREMENTALMENTE ──────
            self._detection.logs.append(
                "[3/4] Extrayendo y analizando textos (incremental)..."
            )
            self._detection.steps_completed = 1
            self._detection.progress = 10

            extractor = MoodleTextExtractor(client)
            counters = {
                "texts": 0, "analyzed": 0, "alerts": 0,
                "students": 0, "errors": 0, "skipped": 0,
            }

            # ─ 3a. Mensajes directos PRIMERO (rápido: 1 llamada API) ─
            self._detection.current_step = (
                "Extrayendo mensajes directos..."
            )
            self._detection.logs.append(
                "  Paso 3a: Mensajes directos (conversaciones)..."
            )

            try:
                all_msgs = (
                    await extractor.extract_messages_from_admin_conversations(
                        int(admin_user_id)
                    )
                )
                self._detection.logs.append(
                    f"    {len(all_msgs)} mensajes de estudiantes encontrados"
                )

                # Agrupar por estudiante para procesar incremental
                by_student: dict[str, list] = {}
                for msg in all_msgs:
                    sid = msg["student_id"]
                    by_student.setdefault(sid, []).append(msg)

                total_students = len(by_student)
                for si, (sid, msgs) in enumerate(by_student.items()):
                    await self._analyze_texts_immediate(
                        msgs, admin_user_id, 0, "Mensajería directa",
                        counters,
                    )
                    counters["students"] += 1
                    self._update_detection_result(counters, course_count)

                    # Progreso: mensajes ocupan 10% → 80%
                    pct = 10 + int(((si + 1) / max(total_students, 1)) * 70)
                    self._detection.progress = min(pct, 80)

                    if (si + 1) % 20 == 0:
                        self._detection.current_step = (
                            f"Mensajes: {si+1}/{total_students} "
                            f"estudiantes | {counters['alerts']} alertas"
                        )

            except Exception as e:
                self._detection.logs.append(
                    f"    ⚠ Error mensajes directos: {str(e)[:80]}"
                )
                logger.error(f"Error extrayendo mensajes del admin: {e}")

            # ─ 3b. Foros, chats, tareas por curso ─
            # Sólo en modo completo. En quick sáltalo: son cientos de
            # llamadas HTTP por curso y el objetivo del auto-scan es
            # atrapar mensajes directos nuevos en segundos.
            if quick:
                self._detection.logs.append(
                    "  Paso 3b omitido (quick=True: sólo mensajes directos)"
                )
                self._detection.progress = 95
            else:
                # since_ts: última corrida full completada. Los foros/
                # chats/tareas modificados antes de este ts se saltan
                # ANTES de la llamada HTTP a Moodle → escaneos
                # subsecuentes son casi instantáneos si no hay cambios.
                since_ts = detection_checkpoint.last_full_scan_ts
                if since_ts:
                    self._detection.logs.append(
                        f"  Paso 3b: sólo contenido nuevo desde ts={since_ts}"
                    )
                else:
                    self._detection.logs.append(
                        "  Paso 3b: primer escaneo completo (baseline)"
                    )

                for idx, course in enumerate(courses):
                    course_id = course.get("id")
                    course_name = course.get("fullname", f"Curso {course_id}")

                    self._detection.current_step = (
                        f"Curso: {course_name} ({idx + 1}/{course_count})"
                    )
                    self._detection.logs.append(f"    Curso: {course_name}")

                    try:
                        forum_texts = await extractor.extract_forum_texts(
                            course_id, since_ts=since_ts
                        )
                        chat_texts = await extractor.extract_chat_texts(
                            course_id, since_ts=since_ts
                        )
                        assign_texts = await extractor.extract_assignment_texts(
                            course_id, since_ts=since_ts
                        )
                        batch = forum_texts + chat_texts + assign_texts

                        if batch:
                            await self._analyze_texts_immediate(
                                batch, admin_user_id, course_id, course_name,
                                counters,
                            )
                            self._update_detection_result(counters, course_count)
                    except Exception as e:
                        self._detection.logs.append(
                            f"      ⚠ Error foros/chats/tareas: {str(e)[:60]}"
                        )

                    # Progreso: cursos ocupan 80% → 95%
                    pct = 80 + int(((idx + 1) / course_count) * 15)
                    self._detection.progress = min(pct, 95)

                # Al completar una corrida full, avanzamos el checkpoint
                # usando el timestamp de INICIO de la corrida (menos 60s
                # de margen). CRÍTICO: si usáramos "ahora", perderíamos
                # todo lo creado durante la corrida — porque puede haber
                # tardado minutos y el filtro `since_ts` ya lo bloquearía
                # la próxima vez.
                new_ts = run_start_ts - 60
                detection_checkpoint.set_last_full_scan_ts(new_ts)
                self._detection.logs.append(
                    f"  Paso 3b: checkpoint avanzado a ts={new_ts} "
                    f"(inicio de corrida - 60s)"
                )

            # ── Paso 4: Completado ───────────────────────────────
            self._detection.state = TaskState.COMPLETED
            self._detection.progress = 100
            self._detection.steps_completed = 4
            self._detection.current_step = "Deteccion completada"
            self._detection.finished_at = datetime.now(UTC).isoformat()
            self._update_detection_result(counters, course_count)
            self._detection.logs.append(
                f"✓ Completado: {counters['analyzed']} textos nuevos, "
                f"{counters.get('skipped', 0)} ya procesados (saltados), "
                f"{counters['alerts']} alertas, "
                f"{counters['students']} estudiantes con mensajes"
            )
            detection_checkpoint.set_state("completed")
            logger.info(f"Detection completed: {self._detection.result}")

            # Notificar al frontend que terminó
            from app.services.ml.events import detection_event_bus
            await detection_event_bus.publish({
                "type": "detection_complete",
                "counters": counters.copy(),
            })

        except Exception as e:
            self._detection.state = TaskState.FAILED
            self._detection.error = str(e)
            self._detection.current_step = f"Error: {str(e)}"
            self._detection.finished_at = datetime.now(UTC).isoformat()
            self._detection.logs.append(f"✗ Error: {str(e)}")
            # "failed": no se auto-reanuda en bucle; al relanzar manualmente
            # continúa desde el checkpoint sin repetir nada.
            detection_checkpoint.set_state("failed")
            logger.error(f"Detection pipeline failed: {e}")

    async def _run_subprocess(
        self, cmd: list[str], cwd: str, task_type: TaskType
    ) -> int:
        """
        Ejecuta un subproceso y captura su salida en tiempo real.
        Usa subprocess.Popen en un hilo separado para compatibilidad
        con Windows (asyncio.create_subprocess_exec puede fallar bajo
        uvicorn en Windows).
        """
        status = self.get_status(task_type)

        def _run_sync() -> int:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=cwd,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            for line in proc.stdout:
                stripped = line.strip()
                if stripped:
                    status.logs.append(stripped)
                    if "Fold" in stripped:
                        status.current_step = (
                            stripped.split("|")[-1].strip()
                            if "|" in stripped else stripped
                        )
                    elif "Epoch" in stripped:
                        status.current_step = (
                            stripped.split("|")[-1].strip()
                            if "|" in stripped else stripped
                        )
            proc.wait()
            return proc.returncode

        return await asyncio.to_thread(_run_sync)
