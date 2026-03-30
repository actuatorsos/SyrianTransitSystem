"""
Tests for authentication: JWT tokens, login, password change, role checks.
"""

import pytest
from unittest.mock import patch
from lib.auth import (
    hash_password,
    verify_password,
    create_access_token,
    verify_token,
)


# ============================================================================
# Unit Tests: Password Hashing
# ============================================================================


class TestPasswordHashing:
    def test_hash_password_returns_bcrypt_hash(self):
        hashed = hash_password("MySecurePass123!")
        assert hashed.startswith("$2b$")
        assert len(hashed) > 50

    def test_verify_correct_password(self):
        password = "TestPassword1!"
        hashed = hash_password(password)
        assert verify_password(password, hashed) is True

    def test_verify_wrong_password(self):
        hashed = hash_password("CorrectPassword1!")
        assert verify_password("WrongPassword1!", hashed) is False

    def test_different_hashes_for_same_password(self):
        """Bcrypt should generate different salts each time."""
        h1 = hash_password("SamePassword1!")
        h2 = hash_password("SamePassword1!")
        assert h1 != h2


# ============================================================================
# Unit Tests: JWT Tokens
# ============================================================================


class TestJWTTokens:
    def test_create_and_verify_token(self):
        token = create_access_token(
            user_id="test-uuid", email="test@example.com", role="admin"
        )
        payload = verify_token(token)

        assert payload.user_id == "test-uuid"
        assert payload.email == "test@example.com"
        assert payload.role == "admin"

    def test_token_with_different_roles(self):
        for role in ["admin", "dispatcher", "driver", "viewer"]:
            token = create_access_token(
                user_id="uuid", email="test@test.com", role=role
            )
            payload = verify_token(token)
            assert payload.role == role

    def test_invalid_token_raises_401(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            verify_token("invalid.token.here")
        assert exc_info.value.status_code == 401

    def test_expired_token_raises_401(self):
        from datetime import timedelta
        from fastapi import HTTPException

        token = create_access_token(
            user_id="uuid",
            email="test@test.com",
            role="admin",
            expires_delta=timedelta(seconds=-1),
        )

        with pytest.raises(HTTPException) as exc_info:
            verify_token(token)
        assert exc_info.value.status_code == 401


# ============================================================================
# Integration Tests: Login Endpoint
# ============================================================================


class TestLoginEndpoint:
    def test_login_success(self, client, mock_db, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.post(
            "/api/auth/login",
            json={"email": "admin@test.sy", "password": "TestPass123!"},
        )

        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["role"] == "admin"
        assert data["user_id"] == "user-uuid-001"

    def test_login_wrong_password(self, client, mock_db, sample_user):
        mock_db.set_table("users", data=[sample_user])

        response = client.post(
            "/api/auth/login",
            json={"email": "admin@test.sy", "password": "WrongPassword1!"},
        )

        assert response.status_code == 401

    def test_login_nonexistent_user(self, client, mock_db):
        mock_db.set_table("users", data=[])

        response = client.post(
            "/api/auth/login",
            json={"email": "nobody@test.sy", "password": "SomePassword1!"},
        )

        assert response.status_code == 401

    def test_login_missing_fields(self, client):
        response = client.post("/api/auth/login", json={"email": "admin@test.sy"})
        assert response.status_code == 422  # Validation error

    def test_login_invalid_email_format(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "not-an-email", "password": "TestPass123!"},
        )
        assert response.status_code == 422

    def test_login_password_too_short(self, client):
        response = client.post(
            "/api/auth/login",
            json={"email": "unique-short@test.sy", "password": "short"},
        )
        assert response.status_code in (422, 429)  # 429 if rate limit hit in test sequence
