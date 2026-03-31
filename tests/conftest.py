"""Pytest fixtures for Damascus Transit API tests."""

import os
import pytest
from fastapi.testclient import TestClient

# Set env vars before importing the app
os.environ.setdefault("SUPABASE_URL", "http://mock-supabase.local")
os.environ.setdefault("SUPABASE_KEY", "mock-key")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "mock-service-key")
os.environ.setdefault("SUPABASE_ANON_KEY", "mock-anon-key")
os.environ.setdefault("JWT_SECRET", "test-secret-for-ci-only-xxxxxxxxxxxxxxxxx")
os.environ.setdefault("ALLOWED_ORIGINS", "http://localhost:3000")


@pytest.fixture(scope="session")
def client():
    """TestClient for the FastAPI app."""
    from api.index import app

    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


@pytest.fixture(scope="session")
def auth_token(client):
    """Obtain a JWT token via login (requires seeded DB — skipped in unit mode)."""
    return None
