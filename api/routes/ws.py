"""
WebSocket routes: real-time vehicle tracking via persistent WebSocket connections.
Provides sub-second vehicle position updates to connected clients.
"""

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from lib.database import get_db

router = APIRouter(tags=["WebSocket"])

# Active WebSocket connections
_connections: set[WebSocket] = set()


async def broadcast_geofence_alert(alert: dict):
    """Push a geofence alert to all connected WebSocket clients."""
    if not _connections:
        return

    message = json.dumps({"type": "geofence_alert", "data": alert})
    dead = set()
    for ws in list(_connections):
        try:
            await ws.send_text(message)
        except Exception:
            dead.add(ws)
    _connections.difference_update(dead)


async def _broadcast_positions():
    """Fetch latest positions and broadcast to all connected clients."""
    if not _connections:
        return

    db = get_db()
    try:
        result = (
            db.table("vehicle_positions_latest")
            .select("vehicle_id, latitude, longitude, speed_kmh, occupancy_pct, recorded_at, vehicles(name, name_ar)")
            .execute()
        )

        positions = []
        for pos in result.data or []:
            vehicle = pos.get("vehicles") or {}
            positions.append({
                "vehicle_id": pos.get("vehicle_id"),
                "vehicle_name": vehicle.get("name", ""),
                "vehicle_name_ar": vehicle.get("name_ar", ""),
                "latitude": pos.get("latitude"),
                "longitude": pos.get("longitude"),
                "speed_kmh": pos.get("speed_kmh"),
                "occupancy_pct": pos.get("occupancy_pct"),
                "timestamp": pos.get("recorded_at", datetime.utcnow().isoformat()),
            })

        message = json.dumps({"type": "positions", "data": positions})
        dead = set()
        for ws in list(_connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)

        _connections.difference_update(dead)

    except Exception:
        pass


async def _position_broadcast_loop():
    """Background loop that pushes position updates every second."""
    while True:
        await _broadcast_positions()
        await asyncio.sleep(1)


@router.websocket("/api/ws/track")
async def websocket_vehicle_tracking(websocket: WebSocket):
    """
    WebSocket endpoint for real-time vehicle position streaming.

    Connect via: ws://<host>/api/ws/track

    Message format (server → client):
      { "type": "positions", "data": [ { vehicle_id, latitude, longitude,
        speed_kmh, occupancy_pct, timestamp, vehicle_name, vehicle_name_ar }, ... ] }

    Client can send { "type": "ping" } and will receive { "type": "pong" }.
    """
    await websocket.accept()
    _connections.add(websocket)

    # Send current positions immediately on connect
    await _broadcast_positions()

    try:
        while True:
            # Keep the connection alive; handle client messages
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(raw)
                if msg.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                # Send a keepalive ping to detect dead connections
                await websocket.send_text(json.dumps({"type": "ping"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        _connections.discard(websocket)
