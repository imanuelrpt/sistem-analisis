"""Router WebSocket — endpoint live dashboard di /api/ws/live."""

from __future__ import annotations

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..websocket_manager import manager

router = APIRouter(prefix="/api/ws", tags=["ws"])


@router.websocket("/live")
async def ws_live(websocket: WebSocket) -> None:
    """Client terima payload dashboard real-time.

    Setelah connect, client langsung dikirim payload terakhir (jika ada)
    supaya dashboard terisi walaupun baru buka di tengah siklus.
    """
    await manager.connect(websocket)
    try:
        if manager.last_payload is not None:
            await websocket.send_json(manager.last_payload)

        while True:
            # menerima ping/keepalive; abaikan isinya
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:  # noqa: BLE001 - koneksi terputus mendadak
        manager.disconnect(websocket)