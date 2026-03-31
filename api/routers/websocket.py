import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from api.core.database import _supabase_get

router = APIRouter()


class ConnectionManager:
    """
    Manages active WebSocket connections and per-connection route subscriptions.

    Each connection may optionally subscribe to a single route_id filter.
    Connections with no filter receive all vehicle positions.
    """

    def __init__(self):
        self._connections: dict[WebSocket, Optional[str]] = {}

    def connect(self, ws: WebSocket, route_id: Optional[str] = None) -> None:
        self._connections[ws] = route_id

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    def subscribe(self, ws: WebSocket, route_id: Optional[str]) -> None:
        if ws in self._connections:
            self._connections[ws] = route_id

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast_positions(self, positions: list) -> None:
        dead: set = set()
        for ws, route_filter in list(self._connections.items()):
            payload = (
                [p for p in positions if p.get("route_id") == route_filter]
                if route_filter is not None
                else positions
            )
            try:
                await ws.send_text(json.dumps({"type": "positions", "data": payload}))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_alert(self, alert: dict) -> None:
        dead: set = set()
        message = json.dumps({"type": "geofence_alert", "data": alert})
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def _fetch_ws_positions() -> list:
    """Fetch latest vehicle positions for WebSocket broadcast."""
    try:
        query = "vehicle_positions_latest?select=vehicle_id,latitude,longitude,speed_kmh,occupancy_pct,recorded_at,vehicles(name,name_ar,assigned_route_id)"
        positions = await _supabase_get(query)
        result = []
        for pos in positions or []:
            vehicle = pos.get("vehicles") or {}
            result.append(
                {
                    "vehicle_id": pos.get("vehicle_id"),
                    "route_id": vehicle.get("assigned_route_id"),
                    "vehicle_name": vehicle.get("name", ""),
                    "vehicle_name_ar": vehicle.get("name_ar", ""),
                    "latitude": pos.get("latitude"),
                    "longitude": pos.get("longitude"),
                    "speed_kmh": pos.get("speed_kmh"),
                    "occupancy_pct": pos.get("occupancy_pct"),
                    "timestamp": pos.get("recorded_at", datetime.utcnow().isoformat()),
                }
            )
        return result
    except Exception:
        return []


async def _ws_broadcast_loop() -> None:
    """Background loop that pushes position updates to WebSocket clients every second."""
    while True:
        if ws_manager.count > 0:
            positions = await _fetch_ws_positions()
            await ws_manager.broadcast_positions(positions)
        await asyncio.sleep(1)


@router.get("/api/ws/stats", tags=["websocket"])
async def websocket_stats():
    """Returns current WebSocket connection statistics."""
    return JSONResponse({"active_connections": ws_manager.count})


@router.websocket("/api/ws/track")
async def websocket_vehicle_tracking(websocket: WebSocket):
    """
    WebSocket endpoint for real-time vehicle position streaming.

    Connect via: ws://<host>/api/ws/track

    Server → client messages:
      { "type": "positions", "data": [...] }
      { "type": "geofence_alert", "data": {...} }
      { "type": "pong" }
      { "type": "subscribed", "route_id": "<uuid>" }
      { "type": "unsubscribed" }

    Client → server messages:
      { "type": "ping" }
      { "type": "subscribe", "route_id": "<route-uuid>" }
      { "type": "unsubscribe" }
    """
    await websocket.accept()
    ws_manager.connect(websocket)

    try:
        positions = await _fetch_ws_positions()
        await websocket.send_text(json.dumps({"type": "positions", "data": positions}))
    except Exception:
        pass

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "subscribe":
                    route_id = msg.get("route_id") or None
                    ws_manager.subscribe(websocket, route_id)
                    await websocket.send_text(
                        json.dumps({"type": "subscribed", "route_id": route_id})
                    )
                elif msg_type == "unsubscribe":
                    ws_manager.subscribe(websocket, None)
                    await websocket.send_text(json.dumps({"type": "unsubscribed"}))

            except asyncio.TimeoutError:
                # Send keepalive ping
                try:
                    await websocket.send_text(json.dumps({"type": "ping"}))
                except Exception:
                    break

    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket)
