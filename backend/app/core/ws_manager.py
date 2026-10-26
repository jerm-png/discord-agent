from typing import Dict
from fastapi import WebSocket


class WebSocketManager:
    def __init__(self):
        self._connections: Dict[str, WebSocket] = {}

    def connect(self, session_id: str, websocket: WebSocket) -> None:
        self._connections[session_id] = websocket

    def disconnect(self, session_id: str) -> None:
        self._connections.pop(session_id, None)

    async def send(self, session_id: str, data: dict) -> None:
        ws = self._connections.get(session_id)
        if ws is not None:
            try:
                await ws.send_json(data)
            except Exception:
                pass


ws_manager = WebSocketManager()
