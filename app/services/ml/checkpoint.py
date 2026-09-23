"""
Checkpoint persistente de la detección.

Guarda en disco el hash SHA-256 de cada texto ya analizado y el estado
de la corrida. Cumple dos funciones:

1. **Deduplicación sin MongoDB**: en este entorno Mongo no siempre está
   disponible, así que re-ejecutar la detección duplicaría alertas.
   El checkpoint hace que los textos ya procesados se salten siempre.

2. **Reanudación**: si el backend se apaga a mitad de una detección,
   el estado queda "running" en disco. Al arrancar de nuevo, main.py
   relanza la detección automáticamente y esta continúa exactamente
   donde se quedó (los hashes ya registrados se saltan).
"""

import html
import json
import hashlib
import os
import re
from datetime import datetime, UTC
from pathlib import Path
from typing import Optional
from loguru import logger

# backend/data/detection_checkpoint.json
_BACKEND_DIR = Path(__file__).resolve().parents[3]
CHECKPOINT_PATH = _BACKEND_DIR / "data" / "detection_checkpoint.json"


def text_hash(text: str) -> str:
    """Mismo hash que usa la deduplicación de analysis_service."""
    return hashlib.sha256(text.encode()).hexdigest()


def panel_message_key(text: str) -> str:
    """Hash tolerante al formato: Moodle devuelve el mensaje enviado con
    HTML, saltos y entidades distintos al texto original del panel."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    t = re.sub(r"^\s*\[@\w+\]\s*", "", t)
    t = re.sub(r"[\W_]+", " ", t.lower())
    return hashlib.sha256(" ".join(t.split()).encode()).hexdigest()


class DetectionCheckpoint:
    """Singleton: estado persistente de la detección."""

    _instance: Optional["DetectionCheckpoint"] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._hashes = set()
            cls._instance._state = "idle"
            cls._instance._last_full_scan_ts = 0
            # Mensajes que el psicólogo envió desde el panel. En las
            # conversaciones del admin se leen igual que un texto del
            # estudiante (así se sembraron los datos), así que hay que
            # reconocerlos para no analizarlos como si él los escribiera.
            cls._instance._panel_messages = set()
            cls._instance._load()
        return cls._instance

    def _load(self):
        try:
            if CHECKPOINT_PATH.exists():
                with open(CHECKPOINT_PATH, encoding="utf-8") as f:
                    data = json.load(f)
                self._hashes = set(data.get("hashes", []))
                self._state = data.get("state", "idle")
                # Timestamp de la última corrida completada (epoch UNIX).
                # Sirve para saltarnos contenedores de Moodle no
                # modificados desde entonces — sin hacer la llamada HTTP.
                self._last_full_scan_ts = int(data.get("last_full_scan_ts", 0))
                self._panel_messages = set(data.get("panel_messages", []))
                logger.info(
                    f"Checkpoint cargado: {len(self._hashes)} textos "
                    f"procesados, estado='{self._state}', "
                    f"last_full_scan_ts={self._last_full_scan_ts}"
                )
        except Exception as e:
            logger.warning(f"No se pudo leer el checkpoint: {e}")
            self._hashes = set()
            self._state = "idle"
            self._last_full_scan_ts = 0

    def _save(self):
        try:
            CHECKPOINT_PATH.parent.mkdir(parents=True, exist_ok=True)
            tmp = CHECKPOINT_PATH.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "state": self._state,
                        "updated_at": datetime.now(UTC).isoformat(),
                        "last_full_scan_ts": self._last_full_scan_ts,
                        "hashes": sorted(self._hashes),
                        "panel_messages": sorted(self._panel_messages),
                    },
                    f,
                )
            os.replace(tmp, CHECKPOINT_PATH)
        except Exception as e:
            logger.warning(f"No se pudo guardar el checkpoint: {e}")

    # ── API ──────────────────────────────────────────────

    @property
    def state(self) -> str:
        return self._state

    @property
    def processed_count(self) -> int:
        return len(self._hashes)

    def was_interrupted(self) -> bool:
        """True si el backend murió con una detección en curso."""
        return self._state == "running"

    def has(self, text: str) -> bool:
        return text_hash(text) in self._hashes

    def add(self, text: str):
        """Registra un texto como procesado y persiste de inmediato
        (cada texto cuenta: es lo que permite reanudar tras un corte)."""
        self._hashes.add(text_hash(text))
        self._save()

    def add_hash(self, h: str):
        self._hashes.add(h)

    def add_panel_message(self, text: str):
        """Registra un mensaje del panel ANTES de enviarlo: el aviso de
        Moodle puede disparar la detección antes de que el envío termine."""
        self._panel_messages.add(panel_message_key(text))
        self._save()

    def is_panel_message(self, text: str) -> bool:
        return panel_message_key(text) in self._panel_messages

    def set_state(self, state: str):
        self._state = state
        self._save()

    @property
    def last_full_scan_ts(self) -> int:
        """Epoch UNIX de la última corrida FULL completada (0 = nunca)."""
        return self._last_full_scan_ts

    def set_last_full_scan_ts(self, ts: int):
        """Marca el momento en que terminó una corrida FULL.  El próximo
        full-scan sólo pedirá contenido de Moodle con timemodified > ts."""
        self._last_full_scan_ts = int(ts)
        self._save()

    def flush(self):
        self._save()


detection_checkpoint = DetectionCheckpoint()
