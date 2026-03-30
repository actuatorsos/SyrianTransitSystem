"""
GTFS-Realtime feed endpoint.

Returns a valid GTFS-RT protobuf (FeedMessage) containing:
  - VehiclePosition entities for all active vehicles with known positions
  - TripUpdate entities for all in-progress trips

Content-Type: application/x-protobuf
Spec: https://gtfs.org/realtime/reference/
"""

import time
from datetime import datetime

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import Response

from lib.database import get_db

try:
    from google.transit import gtfs_realtime_pb2

    _GTFS_RT_AVAILABLE = True
except ImportError:  # pragma: no cover
    _GTFS_RT_AVAILABLE = False

router = APIRouter(prefix="/api/public", tags=["GTFS-RT"])


def _parse_timestamp(iso_str: str | None) -> int | None:
    """Convert an ISO-8601 string (with optional Z suffix) to a UNIX timestamp."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return None


def _occupancy_status(occupancy_pct: float | None):
    """Map a 0-100 occupancy percentage to a GTFS-RT OccupancyStatus enum value."""
    if occupancy_pct is None:
        return None
    pb = gtfs_realtime_pb2.VehiclePosition
    if occupancy_pct <= 0:
        return pb.EMPTY
    if occupancy_pct <= 25:
        return pb.MANY_SEATS_AVAILABLE
    if occupancy_pct <= 50:
        return pb.FEW_SEATS_AVAILABLE
    if occupancy_pct <= 75:
        return pb.STANDING_ROOM_ONLY
    return pb.FULL


@router.get(
    "/gtfs-rt",
    summary="GTFS-Realtime protobuf feed",
    description=(
        "Returns a binary GTFS-RT FeedMessage containing VehiclePosition "
        "entities for all active vehicles and TripUpdate entities for all "
        "in-progress trips. Suitable for consumption by Google Maps and "
        "other GTFS-RT-compatible trip planners."
    ),
    responses={
        200: {"content": {"application/x-protobuf": {}}},
        503: {"description": "gtfs-realtime-bindings library not installed"},
    },
)
async def gtfs_realtime_feed():
    """GTFS-Realtime feed (VehiclePositions + TripUpdates)."""
    if not _GTFS_RT_AVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="gtfs-realtime-bindings is not installed",
        )

    db = get_db()

    try:
        # ── Fetch raw data ────────────────────────────────────────────────────

        # Latest GPS positions
        positions_result = (
            db.table("vehicle_positions_latest")
            .select(
                "vehicle_id, latitude, longitude, speed_kmh, heading, "
                "occupancy_pct, recorded_at"
            )
            .execute()
        )

        # All vehicles (active + idle) keyed by UUID
        vehicles_result = (
            db.table("vehicles")
            .select("id, vehicle_id, name, assigned_route_id")
            .execute()
        )
        vehicles_by_uuid = {v["id"]: v for v in (vehicles_result.data or [])}

        # Route text IDs (R001, R002, …) keyed by UUID
        routes_result = (
            db.table("routes")
            .select("id, route_id")
            .execute()
        )
        route_id_by_uuid = {r["id"]: r["route_id"] for r in (routes_result.data or [])}

        # In-progress trips keyed by vehicle UUID
        trips_result = (
            db.table("trips")
            .select("id, vehicle_id, route_id, actual_start")
            .eq("status", "in_progress")
            .execute()
        )
        trips_by_vehicle = {t["vehicle_id"]: t for t in (trips_result.data or [])}

        # ── Build FeedMessage ─────────────────────────────────────────────────

        feed = gtfs_realtime_pb2.FeedMessage()
        feed.header.gtfs_realtime_version = "2.0"
        feed.header.incrementality = (
            gtfs_realtime_pb2.FeedHeader.FULL_DATASET
        )
        feed.header.timestamp = int(time.time())

        # ── VehiclePosition entities ──────────────────────────────────────────
        for pos in positions_result.data or []:
            if pos.get("latitude") is None or pos.get("longitude") is None:
                continue

            vehicle = vehicles_by_uuid.get(pos["vehicle_id"])
            if not vehicle:
                continue

            trip = trips_by_vehicle.get(pos["vehicle_id"])
            route_text_id = route_id_by_uuid.get(
                vehicle.get("assigned_route_id", ""), ""
            )

            entity = feed.entity.add()
            entity.id = f"vp_{pos['vehicle_id']}"

            vp = entity.vehicle
            vp.vehicle.id = vehicle["vehicle_id"]
            vp.vehicle.label = vehicle["name"]

            if trip:
                vp.trip.trip_id = trip["id"]
            if route_text_id:
                vp.trip.route_id = route_text_id

            vp.position.latitude = float(pos["latitude"])
            vp.position.longitude = float(pos["longitude"])

            if pos.get("speed_kmh") is not None:
                vp.position.speed = float(pos["speed_kmh"]) / 3.6  # km/h → m/s

            if pos.get("heading") is not None:
                vp.position.bearing = float(pos["heading"])

            ts = _parse_timestamp(pos.get("recorded_at"))
            if ts:
                vp.timestamp = ts

            occ = _occupancy_status(pos.get("occupancy_pct"))
            if occ is not None:
                vp.occupancy_status = occ

        # ── TripUpdate entities ───────────────────────────────────────────────
        for trip in trips_result.data or []:
            vehicle = vehicles_by_uuid.get(trip["vehicle_id"])
            route_text_id = route_id_by_uuid.get(trip.get("route_id", ""), "")

            entity = feed.entity.add()
            entity.id = f"tu_{trip['id']}"

            tu = entity.trip_update
            tu.trip.trip_id = trip["id"]
            if route_text_id:
                tu.trip.route_id = route_text_id

            if vehicle:
                tu.vehicle.id = vehicle["vehicle_id"]
                tu.vehicle.label = vehicle["name"]

            ts = _parse_timestamp(trip.get("actual_start"))
            if ts:
                tu.timestamp = ts

        # ── Serialize and return ──────────────────────────────────────────────
        return Response(
            content=feed.SerializeToString(),
            media_type="application/x-protobuf",
            headers={"X-GTFS-RT-Version": "2.0"},
        )

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate GTFS-RT feed",
        )
