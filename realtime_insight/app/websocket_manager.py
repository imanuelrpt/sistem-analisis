"""WebSocket manager: kelola koneksi client & broadcast payload.

Pakai threading.Lock saat iterasi + send supaya koneksi yang masuk/keluar
tidak menimbulkan race condition (spec teknis).
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import Any

from fastapi import WebSocket

logger = logging.getLogger("realtime_insight.ws")


class ConnectionManager:
    def __init__(self) -> None:
        self._active: set[WebSocket] = set()
        self._lock = threading.Lock()
        # cache payload terakhir agar client baru langsung dapat data
        self._last_payload: dict[str, Any] | None = None
        self._history: deque[dict[str, Any]] = deque(maxlen=200)

    # ------------------------------------------------------------------
    # Manajemen koneksi
    # ------------------------------------------------------------------
    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        with self._lock:
            self._active.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        with self._lock:
            self._active.discard(websocket)

    @property
    def last_payload(self) -> dict[str, Any] | None:
        return self._last_payload

    # ------------------------------------------------------------------
    # Broadcast
    # ------------------------------------------------------------------
    async def broadcast(self, payload: dict[str, Any]) -> None:
        self._last_payload = payload
        self._history.append(payload)

        with self._lock:
            targets = list(self._active)

        if not targets:
            return

        # kirim paralel; koneksi yang gagal akan dihapus setelahnya
        todos = [asyncio.create_task(ws.send_json(payload)) for ws in targets]
        outcomes = await asyncio.gather(*todos, return_exceptions=True)

        failed = [
            ws for ws, outcome in zip(targets, outcomes)
            if isinstance(outcome, Exception)
        ]

        if failed:
            with self._lock:
                for ws in failed:
                    self._active.discard(ws)
                    logger.debug("Hapus koneksi WS gagal: %s", ws)


# instance global
manager = ConnectionManager()