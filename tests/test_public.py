"""
Tests for public API endpoints: health, routes, stops, vehicles, stats.
"""

import pytest


class TestHealthEndpoint:
    def test_health_returns_healthy(self, client, mock_db):
        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["database"] is True
        assert "timestamp" in data
        assert data["version"] == "1.1.0"

    def test_health_returns_degraded_when_db_down(self, client, mock_db):
        mock_db.health_check = lambda: False

        response = client.get("/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"
        assert data["database"] is False


class TestRoutesEndpoint:
    def test_list_routes_success(self, client, mock_db, sample_route):
        mock_db.set_table("routes", data=[sample_route])
        mock_db.set_table("route_stops", data=[], count=5)

        response = client.get("/api/routes")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Marjeh → Mezzeh"
        assert data[0]["name_ar"] == "المرجة → المزة"

    def test_list_routes_empty(self, client, mock_db):
        mock_db.set_table("routes", data=[])

        response = client.get("/api/routes")
        assert response.status_code == 200
        assert response.json() == []

    def test_get_single_route(self, client, mock_db, sample_route):
        mock_db.set_table("routes", data=[sample_route])
        mock_db.set_table("route_stops", data=[], count=5)

        response = client.get(f"/api/routes/{sample_route['id']}")
        assert response.status_code == 200
        assert response.json()["route_id"] == "R001"

    def test_get_route_not_found(self, client, mock_db):
        mock_db.set_table("routes", data=[])

        response = client.get("/api/routes/nonexistent-uuid")
        assert response.status_code == 404


class TestStopsEndpoint:
    def test_list_stops(self, client, mock_db, sample_stop):
        mock_db.set_table("stops", data=[sample_stop])

        response = client.get("/api/stops")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Marjeh Square"
        assert data[0]["name_ar"] == "ساحة المرجة"
        assert data[0]["has_shelter"] is True

    def test_nearest_stops(self, client, mock_db, sample_stop):
        sample_stop["distance_m"] = 150.5
        mock_db.set_rpc("find_nearest_stops", data=[sample_stop])

        response = client.get("/api/stops/nearest?lat=33.51&lon=36.29")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

    def test_nearest_stops_invalid_coords(self, client):
        response = client.get("/api/stops/nearest?lat=999&lon=36.29")
        assert response.status_code == 422

    def test_nearest_stops_missing_params(self, client):
        response = client.get("/api/stops/nearest")
        assert response.status_code == 422


class TestVehiclesEndpoint:
    def test_list_vehicles(self, client, mock_db, sample_vehicle):
        position_data = {
            "vehicle_id": sample_vehicle["id"],
            "latitude": 33.5138,
            "longitude": 36.2920,
            "speed_kmh": 25.5,
            "occupancy_pct": 60,
            "recorded_at": "2026-03-26T12:00:00",
            "vehicles": sample_vehicle,
        }
        mock_db.set_table("vehicle_positions_latest", data=[position_data])

        response = client.get("/api/vehicles")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["vehicle_id"] == "V001"
        assert data[0]["latitude"] == 33.5138

    def test_vehicle_positions_lightweight(self, client, mock_db):
        position = {
            "vehicle_id": "vehicle-uuid-001",
            "latitude": 33.5138,
            "longitude": 36.2920,
            "speed_kmh": 30.0,
            "occupancy_pct": 45,
            "recorded_at": "2026-03-26T12:00:00",
        }
        mock_db.set_table("vehicle_positions_latest", data=[position])

        response = client.get("/api/vehicles/positions")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1


class TestStatsEndpoint:
    def test_fleet_stats(self, client, mock_db):
        mock_db.set_table(
            "vehicles",
            data=[
                {"id": "1", "status": "active"},
                {"id": "2", "status": "idle"},
                {"id": "3", "status": "maintenance"},
            ],
            count=3,
        )
        mock_db.set_table("routes", data=[], count=8)
        mock_db.set_table("stops", data=[], count=42)
        mock_db.set_table("users", data=[{"id": "1", "is_active": True}], count=1)
        mock_db.set_table(
            "vehicle_positions_latest",
            data=[{"occupancy_pct": 50}, {"occupancy_pct": 70}],
        )

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["active_vehicles"] == 1
        assert data["idle_vehicles"] == 1
        assert data["maintenance_vehicles"] == 1
        assert "timestamp" in data


class TestAlertsEndpoint:
    def test_active_alerts(self, client, mock_db):
        alert = {
            "id": "alert-001",
            "vehicle_id": "vehicle-001",
            "alert_type": "speeding",
            "severity": "high",
            "title": "Speeding Alert",
            "title_ar": "تنبيه السرعة",
            "description": "Vehicle exceeded 80 km/h",
            "is_resolved": False,
            "created_at": "2026-03-26T12:00:00",
        }
        mock_db.set_table("alerts", data=[alert])

        response = client.get("/api/alerts/active")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["severity"] == "high"


class TestRootEndpoint:
    def test_root(self, client):
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["version"] == "1.1.0"
        assert "docs" in data
