"""
Bus de eventos para notificar al frontend via SSE (Server-Sent Events).
Cuando la deteccion guarda una alerta nueva, publica un evento.
Los clientes SSE conectados reciben el aviso y refrescan sus datos.
"""

import asyncio
from loguru import logger


class DetectionEventBus:

    def __init__(self):
        self._subscribers: list[asyncio.Queue] = []

    def subscribe(self) -> asyncio.Queue:
        """Registra un nuevo cliente SSE."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._subscribers.append(queue)
        logger.debug(f"SSE: nuevo suscriptor ({len(self._subscribers)} total)")
        return queue

    def unsubscribe(self, queue: asyncio.Queue):
        """Desregistra un cliente SSE."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
        logger.debug(f"SSE: suscriptor desconectado ({len(self._subscribers)} total)")

    async def publish(self, event: dict):
        """Envia un evento a todos los clientes conectados."""
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                pass  # Si un suscriptor es lento, se salta


# Singleton global
detection_event_bus = DetectionEventBus()
