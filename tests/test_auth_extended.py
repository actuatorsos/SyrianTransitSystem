"""
Extended tests for auth endpoints: change password.
"""

import pytest


class TestChangePassword:
    def test_change_password_success(self, client, mock_db, auth_token, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_change_password_wrong_current(self, client, mock_db, auth_token, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "current_password": "WrongPassword1!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 401

    def test_change_password_user_not_found(self, client, mock_db, auth_token):
        mock_db.set_table("users", data=[])

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 404

    def test_change_password_requires_auth(self, client):
        response = client.post(
            "/api/auth/change-password",
            json={
                "current_password": "TestPass123!",
                "new_password": "NewPass456!",
            },
        )
        assert response.status_code == 403

    def test_change_password_weak_new_password(self, client, mock_db, auth_token, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.post(
            "/api/auth/change-password",
            headers={"Authorization": f"Bearer {auth_token}"},
            json={
                "current_password": "TestPass123!",
                "new_password": "short",
            },
        )
        assert response.status_code == 422
