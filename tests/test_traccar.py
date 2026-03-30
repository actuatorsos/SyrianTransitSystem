"""
Tests for Traccar GPS webhook endpoints.
"""

import pytest
import time


class TestTraccarPosition:
    def test_position_webhook(self, client, mock_db, sample_vehicle):
        mock_db.set_table("vehicles", data=[sample_vehicle])
        mock_db.set_rpc("upsert_vehicle_position", data=[])

        response = client.post(
            "/api/traccar/position",
            json={
                "deviceId": 12345,
                "latitude": 33.5138,
                "longitude": 36.2920,
                "speed": 30.5,
                "heading": 90.0,
                "timestamp": int(time.time()),
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_position_unknown_device(self, client, mock_db):
        mock_db.set_table("vehicles", data=[])

        response = client.post(
            "/api/traccar/position",
            json={
                "deviceId": 99999,
                "latitude": 33.5,
                "longitude": 36.3,
                "timestamp": int(time.time()),
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "ignored"

    def test_position_invalid_coords(self, client):
        response = client.post(
            "/api/traccar/position",
            json={
                "deviceId": 12345,
                "latitude": 999,
                "longitude": 36.3,
                "timestamp": int(time.time()),
            },
        )
        assert response.status_code == 422


class TestTraccarEvent:
    def test_critical_event_creates_alert(self, client, mock_db, sample_vehicle):
        mock_db.set_table("vehicles", data=[sample_vehicle])
        mock_db.set_table("alerts", data=[])

        response = client.post(
            "/api/traccar/event",
            json={
                "type": "overspeed",
                "serverTime": int(time.time()),
                "deviceId": 12345,
                "deviceName": "Bus 001 GPS",
                "data": {"speed": 95.0, "limit": 60.0},
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_noncritical_event(self, client, mock_db, sample_vehicle):
        mock_db.set_table("vehicles", data=[sample_vehicle])

        response = client.post(
            "/api/traccar/event",
            json={
                "type": "deviceOnline",
                "serverTime": int(time.time()),
                "deviceId": 12345,
                "deviceName": "Bus 001 GPS",
                "data": {},
            },
        )
        assert response.status_code == 200
