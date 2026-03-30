"""
Tests for WebSocket real-time vehicle tracking (DAM-66 upgrade).
"""

import json
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from api.routes.ws import manager, ConnectionManager


# ---------------------------------------------------------------------------
# ConnectionManager unit tests
# ---------------------------------------------------------------------------


class TestConnectionManager:
    def test_connect_increments_count(self):
        mgr = ConnectionManager()
        assert mgr.count == 0

        class FakeWS:
            pass

        ws = FakeWS()
        mgr.connect(ws)
        assert mgr.count == 1

    def test_disconnect_removes_connection(self):
        mgr = ConnectionManager()

        class FakeWS:
            pass

        ws = FakeWS()
        mgr.connect(ws)
        mgr.disconnect(ws)
        assert mgr.count == 0

    def test_disconnect_unknown_is_safe(self):
        mgr = ConnectionManager()

        class FakeWS:
            pass

        mgr.disconnect(FakeWS())  # Should not raise

    def test_subscribe_updates_route_filter(self):
        mgr = ConnectionManager()

        class FakeWS:
            pass

        ws = FakeWS()
        mgr.connect(ws)
        mgr.subscribe(ws, "route-123")
        assert mgr._connections[ws] == "route-123"

    def test_subscribe_unknown_ws_is_safe(self):
        mgr = ConnectionManager()

        class FakeWS:
            pass

        mgr.subscribe(FakeWS(), "route-123")  # Should not raise

    @pytest.mark.anyio
    async def test_broadcast_positions_filters_by_route(self):
        mgr = ConnectionManager()
        received_a = []
        received_b = []

        class FakeWS:
            def __init__(self, store):
                self._store = store

            async def send_text(self, text):
                self._store.append(json.loads(text))

        ws_a = FakeWS(received_a)
        ws_b = FakeWS(received_b)
        mgr.connect(ws_a, route_id="route-001")
        mgr.connect(ws_b, route_id=None)  # all routes

        positions = [
            {"vehicle_id": "v1", "route_id": "route-001", "latitude": 33.5},
            {"vehicle_id": "v2", "route_id": "route-002", "latitude": 33.6},
        ]
        await mgr.broadcast_positions(positions)

        # ws_a subscribed to route-001: receives only v1
        assert len(received_a) == 1
        assert received_a[0]["type"] == "positions"
        assert len(received_a[0]["data"]) == 1
        assert received_a[0]["data"][0]["vehicle_id"] == "v1"

        # ws_b has no filter: receives both
        assert len(received_b) == 1
        assert received_b[0]["type"] == "positions"
        assert len(received_b[0]["data"]) == 2

    @pytest.mark.anyio
    async def test_broadcast_removes_dead_connections(self):
        mgr = ConnectionManager()

        class DeadWS:
            async def send_text(self, text):
                raise RuntimeError("connection closed")

        ws = DeadWS()
        mgr.connect(ws)
        assert mgr.count == 1

        await mgr.broadcast_positions([])
        assert mgr.count == 0

    @pytest.mark.anyio
    async def test_broadcast_alert_sends_to_all(self):
        mgr = ConnectionManager()
        received_a = []
        received_b = []

        class FakeWS:
            def __init__(self, store):
                self._store = store

            async def send_text(self, text):
                self._store.append(json.loads(text))

        mgr.connect(FakeWS(received_a), route_id="route-001")
        mgr.connect(FakeWS(received_b), route_id="route-002")

        await mgr.broadcast_alert({"alert_id": "a1", "message": "Geofence exit"})

        assert received_a[0]["type"] == "geofence_alert"
        assert received_b[0]["type"] == "geofence_alert"


# ---------------------------------------------------------------------------
# WebSocket endpoint integration tests
# ---------------------------------------------------------------------------


class TestWebSocketEndpoint:
    def test_stats_endpoint_returns_count(self, client, mock_db):
        response = client.get("/api/ws/stats")
        assert response.status_code == 200
        data = response.json()
        assert "active_connections" in data
        assert isinstance(data["active_connections"], int)

    def test_websocket_connects_and_receives_positions(self, client, mock_db):
        mock_db.set_table(
            "vehicle_positions_latest",
            data=[
                {
                    "vehicle_id": "v-uuid-001",
                    "route_id": "r-uuid-001",
                    "latitude": 33.5138,
                    "longitude": 36.2920,
                    "speed_kmh": 40.0,
                    "occupancy_pct": 60,
                    "recorded_at": "2026-03-30T12:00:00",
                    "vehicles": {"name": "Bus 001", "name_ar": "باص 001"},
                }
            ],
        )

        import api.routes.ws as ws_mod

        with patch.object(ws_mod, "get_db", return_value=mock_db):
            with client.websocket_connect("/api/ws/track") as ws:
                msg = json.loads(ws.receive_text())
                assert msg["type"] == "positions"
                assert len(msg["data"]) == 1
                assert msg["data"][0]["vehicle_id"] == "v-uuid-001"
                assert msg["data"][0]["route_id"] == "r-uuid-001"
                assert msg["data"][0]["vehicle_name"] == "Bus 001"

    def test_websocket_ping_pong(self, client, mock_db):
        mock_db.set_table("vehicle_positions_latest", data=[])

        with client.websocket_connect("/api/ws/track") as ws:
            # Consume initial snapshot
            ws.receive_text()
            # Send ping
            ws.send_text(json.dumps({"type": "ping"}))
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "pong"

    def test_websocket_subscribe_message(self, client, mock_db):
        mock_db.set_table("vehicle_positions_latest", data=[])

        with client.websocket_connect("/api/ws/track") as ws:
            ws.receive_text()  # initial snapshot
            ws.send_text(json.dumps({"type": "subscribe", "route_id": "r-uuid-001"}))
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "subscribed"
            assert reply["route_id"] == "r-uuid-001"

    def test_websocket_unsubscribe_message(self, client, mock_db):
        mock_db.set_table("vehicle_positions_latest", data=[])

        with client.websocket_connect("/api/ws/track") as ws:
            ws.receive_text()  # initial snapshot
            ws.send_text(json.dumps({"type": "subscribe", "route_id": "r-uuid-001"}))
            ws.receive_text()  # subscribed ack
            ws.send_text(json.dumps({"type": "unsubscribe"}))
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "unsubscribed"

    def test_websocket_invalid_json_ignored(self, client, mock_db):
        mock_db.set_table("vehicle_positions_latest", data=[])

        with client.websocket_connect("/api/ws/track") as ws:
            ws.receive_text()  # initial snapshot
            ws.send_text("not valid json {{{")
            # Send a ping to confirm connection is still alive
            ws.send_text(json.dumps({"type": "ping"}))
            reply = json.loads(ws.receive_text())
            assert reply["type"] == "pong"
