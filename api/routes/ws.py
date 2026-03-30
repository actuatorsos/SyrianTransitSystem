"""
WebSocket routes: real-time vehicle tracking via persistent WebSocket connections.
Provides sub-second vehicle position updates to connected clients.

Upgrade features:
- ConnectionManager class for thread-safe connection lifecycle management
- Route subscription: clients can subscribe to a specific route_id to receive
  only positions for vehicles on that route (omit route_id for all vehicles)
- /api/ws/stats HTTP endpoint showing active connection count
- Geofence alert broadcasting to all subscribed clients
"""

import asyncio
import json
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from lib.database import get_db

router = APIRouter(tags=["WebSocket"])


# ============================================================================
# Connection Manager
# ============================================================================


class ConnectionManager:
    """
    Manages active WebSocket connections and per-connection subscriptions.

    Each connection may optionally subscribe to a single route_id filter.
    Connections with no filter receive all vehicle positions.
    """

    def __init__(self):
        # Map websocket → subscribed route_id (None means all routes)
        self._connections: dict[WebSocket, Optional[str]] = {}

    def connect(self, ws: WebSocket, route_id: Optional[str] = None) -> None:
        self._connections[ws] = route_id

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    def subscribe(self, ws: WebSocket, route_id: Optional[str]) -> None:
        """Update the route filter for an existing connection."""
        if ws in self._connections:
            self._connections[ws] = route_id

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast_positions(self, positions: list[dict]) -> None:
        """
        Broadcast position data to all connected clients.
        Clients subscribed to a route_id receive only positions for that route.
        Clients with no subscription (route_id=None) receive all positions.
        """
        dead: set[WebSocket] = set()

        for ws, route_filter in list(self._connections.items()):
            if route_filter is not None:
                payload = [p for p in positions if p.get("route_id") == route_filter]
            else:
                payload = positions

            try:
                await ws.send_text(json.dumps({"type": "positions", "data": payload}))
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.disconnect(ws)

    async def broadcast_alert(self, alert: dict) -> None:
        """Push a geofence alert to all connected clients regardless of route filter."""
        dead: set[WebSocket] = set()
        message = json.dumps({"type": "geofence_alert", "data": alert})

        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        for ws in dead:
            self.disconnect(ws)


# Module-level manager instance shared by all routes and the broadcast loop
manager = ConnectionManager()


# ============================================================================
# Public helpers used by other route modules (geofencing, etc.)
# ============================================================================


async def broadcast_geofence_alert(alert: dict) -> None:
    """Push a geofence alert to all connected WebSocket clients."""
    await manager.broadcast_alert(alert)


# ============================================================================
# Internal broadcast loop
# ============================================================================


async def _fetch_positions() -> list[dict]:
    """Fetch the latest vehicle positions from the database."""
    db = get_db()
    result = (
        db.table("vehicle_positions_latest")
        .select(
            "vehicle_id, route_id, latitude, longitude, speed_kmh, "
            "occupancy_pct, recorded_at, vehicles(name, name_ar)"
        )
        .execute()
    )

    positions = []
    for pos in result.data or []:
        vehicle = pos.get("vehicles") or {}
        positions.append(
            {
                "vehicle_id": pos.get("vehicle_id"),
                "route_id": pos.get("route_id"),
                "vehicle_name": vehicle.get("name", ""),
                "vehicle_name_ar": vehicle.get("name_ar", ""),
                "latitude": pos.get("latitude"),
                "longitude": pos.get("longitude"),
                "speed_kmh": pos.get("speed_kmh"),
                "occupancy_pct": pos.get("occupancy_pct"),
                "timestamp": pos.get("recorded_at", datetime.utcnow().isoformat()),
            }
        )
    return positions


async def _broadcast_positions() -> None:
    """Fetch latest positions and broadcast to connected clients."""
    if not manager.count:
        return
    try:
        positions = await _fetch_positions()
        await manager.broadcast_positions(positions)
    except Exception:
        pass


async def _position_broadcast_loop() -> None:
    """Background loop that pushes position updates every second."""
    while True:
        await _broadcast_positions()
        await asyncio.sleep(1)


# ============================================================================
# HTTP stats endpoint
# ============================================================================


@router.get("/api/ws/stats")
async def websocket_stats():
    """
    Returns current WebSocket connection statistics.

    Response:
      { "active_connections": <int> }
    """
    return JSONResponse({"active_connections": manager.count})


# ============================================================================
# WebSocket endpoint
# ============================================================================


@router.websocket("/api/ws/track")
async def websocket_vehicle_tracking(websocket: WebSocket):
    """
    WebSocket endpoint for real-time vehicle position streaming.

    Connect via: ws://<host>/api/ws/track

    Server → client messages:
      { "type": "positions", "data": [ { vehicle_id, route_id, latitude,
        longitude, speed_kmh, occupancy_pct, timestamp,
        vehicle_name, vehicle_name_ar }, ... ] }
      { "type": "geofence_alert", "data": { ... } }
      { "type": "pong" }

    Client → server messages:
      { "type": "ping" }
        → server replies { "type": "pong" }
      { "type": "subscribe", "route_id": "<route-uuid>" }
        → server sends only positions for that route from this point forward
      { "type": "unsubscribe" }
        → server resumes sending all vehicle positions
    """
    await websocket.accept()
    manager.connect(websocket)

    # Push current snapshot immediately on connect
    try:
        positions = await _fetch_positions()
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
                    manager.subscribe(websocket, route_id)
                    await websocket.send_text(
                        json.dumps(
                            {
                                "type": "subscribed",
                                "route_id": route_id,
                            }
                        )
                    )

                elif msg_type == "unsubscribe":
                    manager.subscribe(websocket, None)
                    await websocket.send_text(
                        json.dumps({"type": "unsubscribed"})
                    )

            except asyncio.TimeoutError:
                # Keepalive ping to detect dead connections
                await websocket.send_text(json.dumps({"type": "ping"}))
            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
