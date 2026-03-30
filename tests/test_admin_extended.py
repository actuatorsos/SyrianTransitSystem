"""
Extended tests for admin endpoints: update user, update vehicle, assign vehicle,
list alerts, list trips, analytics overview, and DB error paths.
"""

import pytest


class TestAdminUpdateUser:
    def test_update_user_success(self, client, mock_db, auth_token):
        updated = {
            "id": "user-uuid-001",
            "email": "admin@test.sy",
            "full_name": "Updated Name",
            "full_name_ar": "اسم محدث",
            "role": "admin",
            "phone": "+963912345678",
            "is_active": True,
        }
        mock_db.set_table("users", data=[updated])

        response = client.put(
            "/api/admin/users/user-uuid-001",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"full_name": "Updated Name"},
        )
        assert response.status_code == 200
        assert response.json()["full_name"] == "Updated Name"

    def test_update_user_no_fields(self, client, auth_token):
        response = client.put(
            "/api/admin/users/user-uuid-001",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={},
        )
        assert response.status_code == 400

    def test_update_user_not_found(self, client, mock_db, auth_token):
        mock_db.set_table("users", data=[])

        response = client.put(
            "/api/admin/users/nonexistent",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"full_name": "Ghost"},
        )
        assert response.status_code == 404

    def test_update_user_requires_admin(self, client, driver_token):
        response = client.put(
            "/api/admin/users/user-uuid-001",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"full_name": "Hacker"},
        )
        assert response.status_code == 403

    def test_update_user_deactivate(self, client, mock_db, auth_token):
        updated = {
            "id": "user-uuid-002",
            "email": "driver@test.sy",
            "full_name": "Test Driver",
            "full_name_ar": "سائق اختبار",
            "role": "driver",
            "phone": None,
            "is_active": False,
        }
        mock_db.set_table("users", data=[updated])

        response = client.put(
            "/api/admin/users/user-uuid-002",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"is_active": False},
        )
        assert response.status_code == 200
        assert response.json()["is_active"] is False


class TestAdminListVehicles:
    def test_list_all_vehicles_success(self, client, mock_db, auth_token, sample_vehicle):
        mock_db.set_table(
            "vehicle_positions_latest",
            data=[
                {
                    "vehicles": sample_vehicle,
                    "latitude": 33.51,
                    "longitude": 36.29,
                    "speed_kmh": 30.0,
                    "occupancy_pct": 60,
                    "recorded_at": "2026-03-26T10:00:00",
                }
            ],
        )

        response = client.get(
            "/api/admin/vehicles",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["vehicle_id"] == "V001"
        assert data[0]["latitude"] == 33.51

    def test_list_all_vehicles_empty(self, client, mock_db, auth_token):
        mock_db.set_table("vehicle_positions_latest", data=[])

        response = client.get(
            "/api/admin/vehicles",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_list_vehicles_requires_auth(self, client):
        response = client.get("/api/admin/vehicles")
        assert response.status_code == 403


class TestAdminUpdateVehicle:
    def test_update_vehicle_success(self, client, mock_db, auth_token, sample_vehicle):
        updated = {**sample_vehicle, "capacity": 60}
        mock_db.set_table("vehicles", data=[updated])

        response = client.put(
            f"/api/admin/vehicles/{sample_vehicle['id']}",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"capacity": 60},
        )
        assert response.status_code == 200
        assert response.json()["capacity"] == 60

    def test_update_vehicle_no_fields(self, client, auth_token):
        response = client.put(
            "/api/admin/vehicles/vehicle-uuid-001",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={},
        )
        assert response.status_code == 400

    def test_update_vehicle_not_found(self, client, mock_db, auth_token):
        mock_db.set_table("vehicles", data=[])

        response = client.put(
            "/api/admin/vehicles/nonexistent",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"name": "Ghost Bus"},
        )
        assert response.status_code == 404

    def test_update_vehicle_requires_admin(self, client, driver_token):
        response = client.put(
            "/api/admin/vehicles/vehicle-uuid-001",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"capacity": 10},
        )
        assert response.status_code == 403

    def test_update_vehicle_status(self, client, mock_db, auth_token, sample_vehicle):
        updated = {**sample_vehicle, "status": "maintenance"}
        mock_db.set_table("vehicles", data=[updated])

        response = client.put(
            f"/api/admin/vehicles/{sample_vehicle['id']}",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"status": "maintenance"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "maintenance"


class TestAdminAssignVehicle:
    def test_assign_vehicle_success(self, client, mock_db, auth_token, sample_vehicle):
        mock_db.set_table("vehicles", data=[sample_vehicle])
        mock_db.set_table("audit_log", data=[])

        response = client.post(
            f"/api/admin/vehicles/{sample_vehicle['id']}/assign",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"route_id": "route-uuid-001", "driver_id": "user-uuid-002"},
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_assign_vehicle_not_found(self, client, mock_db, auth_token):
        mock_db.set_table("vehicles", data=[])

        response = client.post(
            "/api/admin/vehicles/nonexistent/assign",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"route_id": "route-uuid-001", "driver_id": "user-uuid-002"},
        )
        assert response.status_code == 404

    def test_assign_vehicle_requires_admin_or_dispatcher(self, client, driver_token):
        response = client.post(
            "/api/admin/vehicles/vehicle-uuid-001/assign",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={"route_id": "r1", "driver_id": "d1"},
        )
        assert response.status_code == 403


class TestAdminListAlerts:
    def test_list_all_alerts_success(self, client, mock_db, auth_token):
        alerts = [
            {
                "id": "alert-001",
                "vehicle_id": "vehicle-uuid-001",
                "alert_type": "speed",
                "severity": "high",
                "title": "Speeding",
                "title_ar": "تجاوز السرعة",
                "description": "Vehicle exceeded speed limit",
                "is_resolved": False,
                "created_at": "2026-03-26T10:00:00",
            }
        ]
        mock_db.set_table("alerts", data=alerts)

        response = client.get(
            "/api/admin/alerts",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["alert_type"] == "speed"

    def test_list_alerts_empty(self, client, mock_db, auth_token):
        mock_db.set_table("alerts", data=[])

        response = client.get(
            "/api/admin/alerts",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_list_alerts_requires_auth(self, client):
        response = client.get("/api/admin/alerts")
        assert response.status_code == 403

    def test_resolve_alert_not_found(self, client, mock_db, auth_token):
        mock_db.set_table("alerts", data=[])

        response = client.put(
            "/api/admin/alerts/nonexistent/resolve",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"resolved": True},
        )
        assert response.status_code == 404

    def test_unresolve_alert(self, client, mock_db, auth_token):
        mock_db.set_table(
            "alerts",
            data=[
                {
                    "id": "alert-001",
                    "is_resolved": False,
                    "resolved_at": None,
                }
            ],
        )

        response = client.put(
            "/api/admin/alerts/alert-001/resolve",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"resolved": False},
        )
        assert response.status_code == 200


class TestAdminListTrips:
    def test_list_trips_success(self, client, mock_db, auth_token):
        trips = [
            {
                "id": "trip-001",
                "vehicle_id": "vehicle-uuid-001",
                "driver_id": "user-uuid-002",
                "route_id": "route-uuid-001",
                "status": "completed",
                "actual_start": "2026-03-26T08:00:00",
                "actual_end": "2026-03-26T08:45:00",
                "created_at": "2026-03-26T08:00:00",
            }
        ]
        mock_db.set_table("trips", data=trips)

        response = client.get(
            "/api/admin/trips",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["status"] == "completed"

    def test_list_trips_empty(self, client, mock_db, auth_token):
        mock_db.set_table("trips", data=[])

        response = client.get(
            "/api/admin/trips",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_list_trips_requires_auth(self, client):
        response = client.get("/api/admin/trips")
        assert response.status_code == 403

    def test_list_trips_driver_cannot_access(self, client, driver_token):
        response = client.get(
            "/api/admin/trips",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 403


class TestAdminAnalytics:
    def test_analytics_overview_success(self, client, mock_db, auth_token):
        vehicles = [
            {"status": "active"},
            {"status": "active"},
            {"status": "idle"},
            {"status": "maintenance"},
        ]
        mock_db.set_table("vehicles", data=vehicles, count=4)
        mock_db.set_table("routes", data=[{"id": "r1"}, {"id": "r2"}], count=2)
        mock_db.set_table("stops", data=[{"id": "s1"}], count=1)
        mock_db.set_table(
            "users",
            data=[{"is_active": True}, {"is_active": True}, {"is_active": False}],
            count=3,
        )
        mock_db.set_table(
            "vehicle_positions_latest",
            data=[{"occupancy_pct": 60}, {"occupancy_pct": 80}],
        )

        response = client.get(
            "/api/admin/analytics/overview",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_vehicles"] == 4
        assert data["active_vehicles"] == 2
        assert data["idle_vehicles"] == 1
        assert data["maintenance_vehicles"] == 1
        assert data["active_drivers"] == 2
        assert data["avg_occupancy_pct"] == 70.0

    def test_analytics_empty_fleet(self, client, mock_db, auth_token):
        mock_db.set_table("vehicles", data=[], count=0)
        mock_db.set_table("routes", data=[], count=0)
        mock_db.set_table("stops", data=[], count=0)
        mock_db.set_table("users", data=[], count=0)
        mock_db.set_table("vehicle_positions_latest", data=[])

        response = client.get(
            "/api/admin/analytics/overview",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total_vehicles"] == 0
        assert data["avg_occupancy_pct"] is None

    def test_analytics_requires_auth(self, client):
        response = client.get("/api/admin/analytics/overview")
        assert response.status_code == 403

    def test_analytics_driver_cannot_access(self, client, driver_token):
        response = client.get(
            "/api/admin/analytics/overview",
            headers={"Authorization": f"Bearer {driver_token}"},
        )
        assert response.status_code == 403
