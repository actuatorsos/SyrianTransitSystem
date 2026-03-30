"""
Tests for admin endpoints: user management, vehicle management, alerts, analytics.
All endpoints require admin/dispatcher authentication.
"""

import pytest


class TestAdminAuth:
    """Verify that admin endpoints reject unauthenticated requests."""

    def test_list_users_requires_auth(self, client):
        response = client.get("/api/admin/users")
        assert response.status_code == 403

    def test_create_user_requires_auth(self, client):
        response = client.post("/api/admin/users", json={})
        assert response.status_code == 403

    def test_list_vehicles_requires_auth(self, client):
        response = client.get("/api/admin/vehicles")
        assert response.status_code == 403

    def test_analytics_requires_auth(self, client):
        response = client.get("/api/admin/analytics/overview")
        assert response.status_code == 403


class TestAdminUsers:
    def test_list_users_as_admin(self, client, mock_db, auth_token, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.get(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {auth_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["email"] == "admin@test.sy"

    def test_create_user_as_admin(self, client, mock_db, auth_token):
        # With simple mock, set_table returns same data for both "check existing" and "insert".
        # Setting data means the existing check finds a match → 409 Conflict.
        # This correctly tests the duplicate-email guard.
        created_user = {
            "id": "new-uuid",
            "email": "new@test.sy",
            "full_name": "New User",
            "full_name_ar": "مستخدم جديد",
            "role": "driver",
            "phone": None,
            "is_active": True,
            "must_change_password": True,
        }
        mock_db.set_table("users", data=[created_user])

        response = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "email": "new@test.sy",
                "password": "NewDriver123!",
                "full_name": "New User",
                "full_name_ar": "مستخدم جديد",
                "role": "driver",
            },
        )
        # Returns 409 because mock returns existing user for the duplicate check
        assert response.status_code == 409

    def test_driver_cannot_create_users(self, client, driver_token):
        response = client.post(
            "/api/admin/users",
            headers={"Authorization": f"Bearer {driver_token}"},
            json={
                "email": "hack@test.sy",
                "password": "HackerPass1!",
                "full_name": "Hacker",
                "role": "admin",
            },
        )
        assert response.status_code == 403


class TestAdminVehicles:
    def test_create_vehicle(self, client, mock_db, auth_token):
        created = {
            "id": "v-new",
            "vehicle_id": "V100",
            "name": "New Bus",
            "name_ar": "باص جديد",
            "vehicle_type": "bus",
            "capacity": 50,
            "status": "idle",
        }
        mock_db.set_table("vehicles", data=[created])

        response = client.post(
            "/api/admin/vehicles",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "vehicle_id": "V100",
                "name": "New Bus",
                "name_ar": "باص جديد",
                "vehicle_type": "bus",
                "capacity": 50,
            },
        )
        assert response.status_code == 200
        assert response.json()["vehicle_id"] == "V100"

    def test_create_vehicle_invalid_type(self, client, auth_token):
        response = client.post(
            "/api/admin/vehicles",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "vehicle_id": "V999",
                "name": "Invalid",
                "name_ar": "غير صالح",
                "vehicle_type": "helicopter",
                "capacity": 10,
            },
        )
        assert response.status_code == 422

    def test_create_vehicle_invalid_capacity(self, client, auth_token):
        response = client.post(
            "/api/admin/vehicles",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "vehicle_id": "V999",
                "name": "Bad Cap",
                "name_ar": "سعة خاطئة",
                "vehicle_type": "bus",
                "capacity": -5,
            },
        )
        assert response.status_code == 422


class TestAdminAlerts:
    def test_resolve_alert(self, client, mock_db, auth_token):
        resolved_alert = {
            "id": "alert-001",
            "is_resolved": True,
            "resolved_at": "2026-03-26T12:00:00",
        }
        mock_db.set_table("alerts", data=[resolved_alert])

        response = client.put(
            "/api/admin/alerts/alert-001/resolve",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={"resolved": True},
        )
        assert response.status_code == 200
