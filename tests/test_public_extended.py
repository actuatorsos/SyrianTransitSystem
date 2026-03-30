"""
Extended tests for public endpoints: active alerts, route schedules, fleet stats.
"""

import pytest


class TestActiveAlerts:
    def test_get_active_alerts_success(self, client, mock_db):
        alerts = [
            {
                "id": "alert-001",
                "vehicle_id": "vehicle-uuid-001",
                "alert_type": "breakdown",
                "severity": "critical",
                "title": "Vehicle breakdown",
                "title_ar": "عطل في المركبة",
                "description": "Engine failure on Route 1",
                "is_resolved": False,
                "created_at": "2026-03-26T09:00:00",
            }
        ]
        mock_db.set_table("alerts", data=alerts)

        response = client.get("/api/alerts/active")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["alert_type"] == "breakdown"
        assert data[0]["is_resolved"] is False

    def test_get_active_alerts_empty(self, client, mock_db):
        mock_db.set_table("alerts", data=[])

        response = client.get("/api/alerts/active")
        assert response.status_code == 200
        assert response.json() == []


class TestRouteSchedules:
    def test_get_route_schedule_success(self, client, mock_db, sample_route):
        schedules = [
            {
                "id": "sched-001",
                "route_id": sample_route["id"],
                "day_of_week": 0,
                "first_departure": "06:00:00",
                "last_departure": "22:00:00",
                "frequency_min": 15,
            }
        ]
        mock_db.set_table("schedules", data=schedules)

        response = client.get(f"/api/schedules/{sample_route['id']}")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["frequency_min"] == 15

    def test_get_route_schedule_empty(self, client, mock_db):
        mock_db.set_table("schedules", data=[])

        response = client.get("/api/schedules/route-uuid-999")
        assert response.status_code == 200
        assert response.json() == []


class TestFleetStats:
    def test_get_fleet_stats_success(self, client, mock_db):
        mock_db.set_table(
            "vehicles",
            data=[
                {"id": "v1", "status": "active"},
                {"id": "v2", "status": "idle"},
                {"id": "v3", "status": "maintenance"},
            ],
            count=3,
        )
        mock_db.set_table("routes", data=[{"id": "r1"}], count=1)
        mock_db.set_table("stops", data=[{"id": "s1"}, {"id": "s2"}], count=2)
        mock_db.set_table(
            "users",
            data=[{"id": "d1", "is_active": True}, {"id": "d2", "is_active": False}],
            count=2,
        )
        mock_db.set_table(
            "vehicle_positions_latest",
            data=[{"occupancy_pct": 50}, {"occupancy_pct": 75}],
        )

        response = client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total_vehicles"] == 3
        assert data["active_vehicles"] == 1
        assert data["idle_vehicles"] == 1
        assert data["maintenance_vehicles"] == 1
        assert data["active_drivers"] == 1
        assert data["avg_occupancy_pct"] == 62.5

    def test_get_fleet_stats_no_occupancy(self, client, mock_db):
        mock_db.set_table("vehicles", data=[], count=0)
        mock_db.set_table("routes", data=[], count=0)
        mock_db.set_table("stops", data=[], count=0)
        mock_db.set_table("users", data=[], count=0)
        mock_db.set_table("vehicle_positions_latest", data=[])

        response = client.get("/api/stats")
        assert response.status_code == 200
        assert response.json()["avg_occupancy_pct"] is None
