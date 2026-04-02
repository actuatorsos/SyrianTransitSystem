import io
import os
import time
import zipfile
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse, Response

from api.core.database import _supabase_get
from api.core.geo import parse_location

router = APIRouter()

GTFS_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "db", "gtfs")


def _gtfs_rt_occupancy_status(occupancy_pct, pb_cls):
    """Map 0-100 occupancy percentage to GTFS-RT OccupancyStatus enum."""
    if occupancy_pct is None:
        return None
    if occupancy_pct <= 0:
        return pb_cls.EMPTY
    if occupancy_pct <= 25:
        return pb_cls.MANY_SEATS_AVAILABLE
    if occupancy_pct <= 50:
        return pb_cls.FEW_SEATS_AVAILABLE
    if occupancy_pct <= 75:
        return pb_cls.STANDING_ROOM_ONLY
    return pb_cls.FULL


def _parse_iso_timestamp(iso_str: Optional[str]) -> Optional[int]:
    """Convert ISO-8601 string to UNIX timestamp."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        return None


@router.get("/api/gtfs/static/{filename}", tags=["gtfs"])
async def get_gtfs_static_file(filename: str):
    """Serve individual GTFS static feed files."""
    allowed = {
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "feed_info.txt",
    }
    if filename not in allowed:
        raise HTTPException(status_code=404, detail="File not found")

    filepath = os.path.join(GTFS_DIR, filename)
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        return Response(content=content, media_type="text/plain; charset=utf-8")
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"{filename} not found")


@router.get("/api/gtfs/feed.zip", tags=["gtfs"])
async def get_gtfs_zip():
    """Download full GTFS static feed as a ZIP archive (Google Maps compatible)."""
    files = [
        "agency.txt",
        "stops.txt",
        "routes.txt",
        "trips.txt",
        "stop_times.txt",
        "calendar.txt",
        "feed_info.txt",
    ]
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name in files:
            filepath = os.path.join(GTFS_DIR, name)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    zf.writestr(name, f.read())
            except FileNotFoundError:
                raise HTTPException(
                    status_code=500, detail=f"GTFS file missing: {name}"
                )
    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={"Content-Disposition": "attachment; filename=gtfs_feed.zip"},
    )


@router.get("/api/gtfs/realtime", tags=["gtfs"])
@router.get("/api/public/gtfs-rt", tags=["gtfs"])
async def get_gtfs_realtime():
    """GTFS-Realtime feed (VehiclePositions + TripUpdates).

    Returns a binary protobuf FeedMessage (GTFS-RT 2.0).
    Falls back to JSON when gtfs-realtime-bindings is not installed.
    """
    try:
        positions = await _supabase_get(
            "vehicle_positions_latest"
            "?select=vehicle_id,location,speed_kmh,heading,"
            "occupancy_pct,recorded_at"
        )
        positions = positions or []

        vehicles_raw = await _supabase_get(
            "vehicles?select=id,vehicle_id,name,assigned_route_id"
        )
        vehicles_by_uuid = {v["id"]: v for v in (vehicles_raw or [])}

        routes_raw = await _supabase_get("routes?select=id,route_id")
        route_id_by_uuid = {r["id"]: r["route_id"] for r in (routes_raw or [])}

        trips_raw = await _supabase_get(
            "trips?select=id,vehicle_id,route_id,actual_start&status=eq.in_progress"
        )
        trips_by_vehicle = {t["vehicle_id"]: t for t in (trips_raw or [])}

        try:
            from google.transit import gtfs_realtime_pb2  # type: ignore

            feed = gtfs_realtime_pb2.FeedMessage()
            feed.header.gtfs_realtime_version = "2.0"
            feed.header.incrementality = gtfs_realtime_pb2.FeedHeader.FULL_DATASET
            feed.header.timestamp = int(time.time())

            for pos in positions:
                lat, lon = parse_location(pos.get("location"))
                if lat is None or lon is None:
                    continue

                vehicle = vehicles_by_uuid.get(pos.get("vehicle_id"))
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
                vp.vehicle.label = vehicle.get("name", "")

                if trip:
                    vp.trip.trip_id = trip["id"]
                if route_text_id:
                    vp.trip.route_id = route_text_id

                vp.position.latitude = float(lat)
                vp.position.longitude = float(lon)

                if pos.get("speed_kmh") is not None:
                    vp.position.speed = float(pos["speed_kmh"]) / 3.6
                if pos.get("heading") is not None:
                    vp.position.bearing = float(pos["heading"])

                ts = _parse_iso_timestamp(pos.get("recorded_at"))
                if ts:
                    vp.timestamp = ts

                occ = _gtfs_rt_occupancy_status(
                    pos.get("occupancy_pct"), gtfs_realtime_pb2.VehiclePosition
                )
                if occ is not None:
                    vp.occupancy_status = occ

            for trip in trips_raw or []:
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
                    tu.vehicle.label = vehicle.get("name", "")

                ts = _parse_iso_timestamp(trip.get("actual_start"))
                if ts:
                    tu.timestamp = ts

            return Response(
                content=feed.SerializeToString(),
                media_type="application/x-protobuf",
                headers={"X-GTFS-RT-Version": "2.0"},
            )

        except ImportError:
            feed_json = {
                "header": {
                    "gtfs_realtime_version": "2.0",
                    "incrementality": "FULL_DATASET",
                    "timestamp": int(time.time()),
                },
                "entity": [],
            }
            for p in positions:
                p_lat, p_lon = parse_location(p.get("location"))
                if p_lat is None or p_lon is None:
                    continue
                vehicle = vehicles_by_uuid.get(p.get("vehicle_id"))
                if not vehicle:
                    continue
                route_text_id = route_id_by_uuid.get(
                    vehicle.get("assigned_route_id", ""), ""
                )
                feed_json["entity"].append(
                    {
                        "id": f"vp_{p['vehicle_id']}",
                        "vehicle": {
                            "vehicle": {
                                "id": vehicle["vehicle_id"],
                                "label": vehicle.get("name", ""),
                            },
                            "trip": {"route_id": route_text_id},
                            "position": {
                                "latitude": p_lat,
                                "longitude": p_lon,
                                "speed": (p.get("speed_kmh") or 0.0) / 3.6,
                            },
                            "timestamp": int(time.time()),
                        },
                    }
                )
            return JSONResponse(content=feed_json)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
