"""
Shared test fixtures and mock setup.
Patches the database module before app imports to avoid Supabase connection.
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime
from types import ModuleType

# Set required env vars BEFORE any app imports
os.environ["SUPABASE_URL"] = "https://test.supabase.co"
os.environ["SUPABASE_KEY"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoiYW5vbiIsImlhdCI6MTcwMDAwMDAwMCwiZXhwIjoxODAwMDAwMDAwfQ.fake_signature_for_testing"
os.environ["SUPABASE_SERVICE_KEY"] = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRlc3QiLCJyb2xlIjoic2VydmljZV9yb2xlIiwiaWF0IjoxNzAwMDAwMDAwLCJleHAiOjE4MDAwMDAwMDB9.fake_service_signature"
os.environ["JWT_SECRET"] = "test-jwt-secret-must-be-at-least-32-chars-long-for-hs256"
os.environ["ALLOWED_ORIGINS"] = "http://localhost:3000"
os.environ["LOG_LEVEL"] = "WARNING"
os.environ["TRACCAR_WEBHOOK_SECRET"] = ""


# ============================================================================
# Mock Database Classes
# ============================================================================


class MockQueryResult:
    """Simulates a Supabase query result."""

    def __init__(self, data=None, count=None):
        self.data = data or []
        self.count = count if count is not None else len(self.data)


class MockQueryBuilder:
    """Chainable mock for Supabase query builder."""

    def __init__(self, data=None, count=None):
        self._data = data or []
        self._count = count

    def select(self, *args, **kwargs):
        return self

    def insert(self, data):
        return self

    def update(self, data):
        return self

    def delete(self):
        return self

    def eq(self, *args):
        return self

    def neq(self, *args):
        return self

    def order(self, *args, **kwargs):
        return self

    def limit(self, *args):
        return self

    def execute(self):
        return MockQueryResult(data=self._data, count=self._count)


class MockSupabaseDB:
    """Mock SupabaseDB for testing without a real database."""

    def __init__(self):
        self._tables = {}
        self._rpcs = {}

    def table(self, name):
        return self._tables.get(name, MockQueryBuilder())

    def rpc(self, func_name, params=None):
        return self._rpcs.get(func_name, MockQueryBuilder())

    def health_check(self):
        return True

    def set_table(self, name, data=None, count=None):
        """Configure mock data for a table."""
        self._tables[name] = MockQueryBuilder(data=data, count=count)

    def set_rpc(self, name, data=None):
        """Configure mock data for an RPC call."""
        self._rpcs[name] = MockQueryBuilder(data=data)


# ============================================================================
# Patch database module BEFORE importing the app
# ============================================================================

# Create a mock database module to prevent Supabase from connecting
_mock_db_instance = MockSupabaseDB()

mock_database_module = ModuleType("lib.database")
mock_database_module.SupabaseDB = MockSupabaseDB
mock_database_module.get_db = lambda: _mock_db_instance
mock_database_module.get_supabase_client = lambda: MagicMock()

# Inject mock into sys.modules before any app code imports it
sys.modules["lib.database"] = mock_database_module

# Now safe to import app
from fastapi.testclient import TestClient
from api.index import app as _app


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def mock_db():
    """Provide a fresh MockSupabaseDB for each test."""
    db = MockSupabaseDB()
    mock_database_module.get_db = lambda: db

    # Also patch in route modules
    import api.routes.public as pub
    import api.routes.auth as auth_mod
    import api.routes.driver as drv
    import api.routes.admin as adm
    import api.routes.traccar as trc

    original_fns = {
        "pub": pub.get_db,
        "auth": auth_mod.get_db,
        "drv": drv.get_db,
        "adm": adm.get_db,
        "trc": trc.get_db,
    }

    pub.get_db = lambda: db
    auth_mod.get_db = lambda: db
    drv.get_db = lambda: db
    adm.get_db = lambda: db
    trc.get_db = lambda: db

    yield db

    # Restore
    pub.get_db = original_fns["pub"]
    auth_mod.get_db = original_fns["auth"]
    drv.get_db = original_fns["drv"]
    adm.get_db = original_fns["adm"]
    trc.get_db = original_fns["trc"]


@pytest.fixture
def client(mock_db):
    """Create a test client with mocked database."""
    return TestClient(_app)


# ============================================================================
# Sample Data Fixtures
# ============================================================================


@pytest.fixture
def sample_user():
    """A sample admin user record."""
    from lib.auth import hash_password

    return {
        "id": "user-uuid-001",
        "email": "admin@test.sy",
        "password_hash": hash_password("TestPass123!"),
        "full_name": "Test Admin",
        "full_name_ar": "مدير اختبار",
        "role": "admin",
        "phone": "+963912345678",
        "is_active": True,
        "must_change_password": False,
        "created_at": datetime.utcnow().isoformat(),
    }


@pytest.fixture
def sample_driver():
    """A sample driver user record."""
    from lib.auth import hash_password

    return {
        "id": "user-uuid-002",
        "email": "driver@test.sy",
        "password_hash": hash_password("DriverPass1!"),
        "full_name": "Test Driver",
        "full_name_ar": "سائق اختبار",
        "role": "driver",
        "phone": "+963911111111",
        "is_active": True,
        "must_change_password": False,
    }


@pytest.fixture
def sample_route():
    """A sample route record."""
    return {
        "id": "route-uuid-001",
        "route_id": "R001",
        "name": "Marjeh → Mezzeh",
        "name_ar": "المرجة → المزة",
        "route_type": "bus",
        "color": "#428177",
        "distance_km": 8.5,
        "avg_duration_min": 35,
        "fare_syp": 2500,
        "is_active": True,
    }


@pytest.fixture
def sample_vehicle():
    """A sample vehicle record."""
    return {
        "id": "vehicle-uuid-001",
        "vehicle_id": "V001",
        "name": "Bus 001",
        "name_ar": "باص 001",
        "vehicle_type": "bus",
        "capacity": 45,
        "status": "active",
        "assigned_route_id": "route-uuid-001",
        "assigned_driver_id": "user-uuid-002",
        "gps_device_id": "12345",
        "is_real_gps": False,
        "is_active": True,
    }


@pytest.fixture
def sample_stop():
    """A sample stop record."""
    return {
        "id": "stop-uuid-001",
        "stop_id": "S001",
        "name": "Marjeh Square",
        "name_ar": "ساحة المرجة",
        "latitude": 33.5138,
        "longitude": 36.2920,
        "has_shelter": True,
        "is_active": True,
    }


@pytest.fixture
def auth_token(sample_user):
    """Generate a valid JWT token for the sample admin user."""
    from lib.auth import create_access_token

    return create_access_token(
        user_id=sample_user["id"],
        email=sample_user["email"],
        role=sample_user["role"],
    )


@pytest.fixture
def driver_token(sample_driver):
    """Generate a valid JWT token for the sample driver."""
    from lib.auth import create_access_token

    return create_access_token(
        user_id=sample_driver["id"],
        email=sample_driver["email"],
        role=sample_driver["role"],
    )
