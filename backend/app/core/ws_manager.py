from typing import Dict, Optional
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}

    def connect(self, session_id: str, websocket: WebSocket) -> None:
        self._connections[session_id] = websocket

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    def get(self, session_id: str) -> Optional[WebSocket]:
        return self._connections.get(session_id)

    async def send(self, session_id: str, data: dict) -> None:
        ws = self._connections.get(session_id)
        if ws is not None:
            try:
                await ws.send_json(data)
            except Exception:
                pass

    async def broadcast(self, data: dict) -> None:
        for ws in list(self._connections.values()):
            try:
                await ws.send_json(data)
            except Exception:
                pass


ws_manager = WebSocketManager()
