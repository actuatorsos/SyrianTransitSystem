"""
Tests for the GTFS-Realtime feed endpoint: GET /api/public/gtfs-rt

Validates:
- Correct Content-Type header (application/x-protobuf)
- Valid GTFS-RT FeedMessage structure (parseable protobuf)
- VehiclePosition entities present for active vehicles with positions
- TripUpdate entities present for in-progress trips
- Graceful empty-data response (no entities, still valid feed)
- Missing/null coordinates are skipped
"""

import pytest
from fastapi.testclient import TestClient

try:
    from google.transit import gtfs_realtime_pb2

    GTFS_RT_AVAILABLE = True
except ImportError:
    GTFS_RT_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not GTFS_RT_AVAILABLE, reason="gtfs-realtime-bindings not installed"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_feed(content: bytes) -> "gtfs_realtime_pb2.FeedMessage":
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(content)
    return feed


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

VEHICLE_UUID = "vehicle-uuid-001"
ROUTE_UUID = "route-uuid-001"
TRIP_UUID = "trip-uuid-001"

SAMPLE_POSITIONS = [
    {
        "vehicle_id": VEHICLE_UUID,
        "latitude": 33.5138,
        "longitude": 36.2920,
        "speed_kmh": 36.0,
        "heading": 90.0,
        "occupancy_pct": 60.0,
        "recorded_at": "2026-03-30T09:00:00Z",
    }
]

SAMPLE_VEHICLES = [
    {
        "id": VEHICLE_UUID,
        "vehicle_id": "V001",
        "name": "Bus 001",
        "assigned_route_id": ROUTE_UUID,
    }
]

SAMPLE_ROUTES = [
    {
        "id": ROUTE_UUID,
        "route_id": "R001",
    }
]

SAMPLE_TRIPS = [
    {
        "id": TRIP_UUID,
        "vehicle_id": VEHICLE_UUID,
        "route_id": ROUTE_UUID,
        "actual_start": "2026-03-30T08:00:00Z",
        "status": "in_progress",
    }
]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_gtfs_rt_returns_protobuf(client, mock_db):
    """Endpoint returns binary protobuf with the correct Content-Type."""
    mock_db.set_table("vehicle_positions_latest", data=SAMPLE_POSITIONS)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=SAMPLE_TRIPS)

    resp = client.get("/api/public/gtfs-rt")

    assert resp.status_code == 200
    assert "application/x-protobuf" in resp.headers["content-type"]
    assert resp.headers.get("x-gtfs-rt-version") == "2.0"


def test_gtfs_rt_valid_feed_message(client, mock_db):
    """Response body is a parseable GTFS-RT FeedMessage."""
    mock_db.set_table("vehicle_positions_latest", data=SAMPLE_POSITIONS)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=SAMPLE_TRIPS)

    resp = client.get("/api/public/gtfs-rt")
    feed = _parse_feed(resp.content)

    assert feed.header.gtfs_realtime_version == "2.0"
    assert feed.header.timestamp > 0


def test_gtfs_rt_vehicle_position_entity(client, mock_db):
    """A VehiclePosition entity is present for the active vehicle."""
    mock_db.set_table("vehicle_positions_latest", data=SAMPLE_POSITIONS)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=SAMPLE_TRIPS)

    feed = _parse_feed(client.get("/api/public/gtfs-rt").content)

    vp_entities = [e for e in feed.entity if e.HasField("vehicle")]
    assert len(vp_entities) == 1

    vp = vp_entities[0].vehicle
    assert vp.vehicle.id == "V001"
    assert vp.vehicle.label == "Bus 001"
    assert vp.trip.route_id == "R001"
    assert vp.trip.trip_id == TRIP_UUID
    assert abs(vp.position.latitude - 33.5138) < 0.0001
    assert abs(vp.position.longitude - 36.2920) < 0.0001
    # 36 km/h → 10 m/s
    assert abs(vp.position.speed - 10.0) < 0.01
    assert vp.position.bearing == 90.0
    # 60 % → STANDING_ROOM_ONLY (value 3)
    assert vp.occupancy_status == gtfs_realtime_pb2.VehiclePosition.STANDING_ROOM_ONLY


def test_gtfs_rt_trip_update_entity(client, mock_db):
    """A TripUpdate entity is present for the in-progress trip."""
    mock_db.set_table("vehicle_positions_latest", data=SAMPLE_POSITIONS)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=SAMPLE_TRIPS)

    feed = _parse_feed(client.get("/api/public/gtfs-rt").content)

    tu_entities = [e for e in feed.entity if e.HasField("trip_update")]
    assert len(tu_entities) == 1

    tu = tu_entities[0].trip_update
    assert tu.trip.trip_id == TRIP_UUID
    assert tu.trip.route_id == "R001"
    assert tu.vehicle.id == "V001"
    assert tu.timestamp > 0


def test_gtfs_rt_empty_data_returns_valid_feed(client, mock_db):
    """With no vehicles or trips the feed is still a valid, parseable protobuf."""
    mock_db.set_table("vehicle_positions_latest", data=[])
    mock_db.set_table("vehicles", data=[])
    mock_db.set_table("routes", data=[])
    mock_db.set_table("trips", data=[])

    resp = client.get("/api/public/gtfs-rt")
    assert resp.status_code == 200

    feed = _parse_feed(resp.content)
    assert feed.header.gtfs_realtime_version == "2.0"
    assert len(feed.entity) == 0


def test_gtfs_rt_skips_positions_with_null_coords(client, mock_db):
    """Positions missing latitude or longitude are excluded from the feed."""
    bad_positions = [
        {
            "vehicle_id": VEHICLE_UUID,
            "latitude": None,
            "longitude": 36.2920,
            "speed_kmh": None,
            "heading": None,
            "occupancy_pct": None,
            "recorded_at": None,
        }
    ]
    mock_db.set_table("vehicle_positions_latest", data=bad_positions)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=[])

    feed = _parse_feed(client.get("/api/public/gtfs-rt").content)
    vp_entities = [e for e in feed.entity if e.HasField("vehicle")]
    assert len(vp_entities) == 0


def test_gtfs_rt_no_trip_when_vehicle_not_on_trip(client, mock_db):
    """A vehicle with a position but no active trip still emits a VehiclePosition."""
    mock_db.set_table("vehicle_positions_latest", data=SAMPLE_POSITIONS)
    mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
    mock_db.set_table("routes", data=SAMPLE_ROUTES)
    mock_db.set_table("trips", data=[])  # no active trips

    feed = _parse_feed(client.get("/api/public/gtfs-rt").content)

    vp_entities = [e for e in feed.entity if e.HasField("vehicle")]
    assert len(vp_entities) == 1
    # trip_id should not be set when there is no active trip
    assert vp_entities[0].vehicle.trip.trip_id == ""


def test_gtfs_rt_occupancy_boundaries(client, mock_db):
    """Occupancy percentage is mapped to the correct GTFS-RT OccupancyStatus enum."""
    pb = gtfs_realtime_pb2.VehiclePosition

    cases = [
        (0.0, pb.EMPTY),
        (15.0, pb.MANY_SEATS_AVAILABLE),
        (40.0, pb.FEW_SEATS_AVAILABLE),
        (65.0, pb.STANDING_ROOM_ONLY),
        (90.0, pb.FULL),
    ]

    for pct, expected_status in cases:
        pos = [{**SAMPLE_POSITIONS[0], "occupancy_pct": pct}]
        mock_db.set_table("vehicle_positions_latest", data=pos)
        mock_db.set_table("vehicles", data=SAMPLE_VEHICLES)
        mock_db.set_table("routes", data=SAMPLE_ROUTES)
        mock_db.set_table("trips", data=[])

        feed = _parse_feed(client.get("/api/public/gtfs-rt").content)
        vp_entities = [e for e in feed.entity if e.HasField("vehicle")]
        assert len(vp_entities) == 1, f"No VehiclePosition for occupancy={pct}"
        assert vp_entities[0].vehicle.occupancy_status == expected_status, (
            f"occupancy={pct} expected {expected_status}, "
            f"got {vp_entities[0].vehicle.occupancy_status}"
        )
