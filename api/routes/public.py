"""
Public routes: health, routes, stops, vehicles, stream, stats, schedules, alerts, gtfs.
No authentication required.
"""

import io
import os
import time
import asyncio
import zipfile
from datetime import datetime
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import StreamingResponse, Response

from lib.database import get_db
from api.models import (
    HealthResponse,
    RouteResponse,
    StopResponse,
    NearestStop,
    VehicleResponse,
    PositionData,
    ScheduleResponse,
    AlertResponse,
)

router = APIRouter(prefix="/api", tags=["Public"])


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint with real database connectivity test.
    """
    db = get_db()
    db_healthy = db.health_check()

    return HealthResponse(
        status="healthy" if db_healthy else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        database=db_healthy,
    )


@router.get("/routes", response_model=List[RouteResponse])
async def list_routes():
    """List all active routes with stop counts."""
    db = get_db()

    try:
        result = db.table("routes").select("*").eq("is_active", True).execute()
        routes = result.data

        enriched_routes = []
        for route in routes:
            stops_result = (
                db.table("route_stops")
                .select("id", count="exact")
                .eq("route_id", route["id"])
                .execute()
            )
            stop_count = stops_result.count or 0

            enriched_routes.append(
                RouteResponse(
                    id=route["id"],
                    route_id=route["route_id"],
                    name=route["name"],
                    name_ar=route["name_ar"],
                    route_type=route["route_type"],
                    color=route.get("color"),
                    distance_km=route.get("distance_km"),
                    avg_duration_min=route.get("avg_duration_min"),
                    fare_syp=route.get("fare_syp"),
                    stop_count=stop_count,
                )
            )

        return enriched_routes

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch routes",
        )


@router.get("/routes/{route_id}", response_model=RouteResponse)
async def get_route(route_id: str):
    """Get single route details with stop count."""
    db = get_db()

    try:
        result = db.table("routes").select("*").eq("id", route_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
            )

        route = result.data[0]

        stops_result = (
            db.table("route_stops")
            .select("id", count="exact")
            .eq("route_id", route_id)
            .execute()
        )
        stop_count = stops_result.count or 0

        return RouteResponse(
            id=route["id"],
            route_id=route["route_id"],
            name=route["name"],
            name_ar=route["name_ar"],
            route_type=route["route_type"],
            color=route.get("color"),
            distance_km=route.get("distance_km"),
            avg_duration_min=route.get("avg_duration_min"),
            fare_syp=route.get("fare_syp"),
            stop_count=stop_count,
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch route",
        )


@router.get("/stops", response_model=List[StopResponse])
async def list_stops():
    """List all active stops."""
    db = get_db()

    try:
        result = db.table("stops").select("*").eq("is_active", True).execute()

        return [
            StopResponse(
                id=stop["id"],
                stop_id=stop["stop_id"],
                name=stop["name"],
                name_ar=stop["name_ar"],
                latitude=stop.get("latitude"),
                longitude=stop.get("longitude"),
                has_shelter=stop.get("has_shelter", False),
                is_active=stop["is_active"],
            )
            for stop in result.data
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch stops",
        )


@router.get("/stops/nearest", response_model=List[NearestStop])
async def find_nearest_stops(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: int = Query(1000, ge=100, le=5000),
    limit: int = Query(10, ge=1, le=50),
):
    """Find nearest stops using PostGIS spatial query."""
    db = get_db()

    try:
        result = db.rpc(
            "find_nearest_stops",
            {"p_lat": lat, "p_lon": lon, "p_limit": limit, "p_radius_m": radius},
        ).execute()

        return [
            NearestStop(
                id=stop["id"],
                stop_id=stop["stop_id"],
                name=stop["name"],
                name_ar=stop["name_ar"],
                latitude=stop.get("latitude"),
                longitude=stop.get("longitude"),
                distance_m=stop.get("distance_m"),
                has_shelter=stop.get("has_shelter", False),
            )
            for stop in (result.data or [])
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to find nearest stops",
        )


@router.get("/vehicles", response_model=List[VehicleResponse])
async def list_vehicles():
    """List all active vehicles with latest positions."""
    db = get_db()

    try:
        result = (
            db.table("vehicle_positions_latest")
            .select(
                "*, vehicles(id, vehicle_id, name, name_ar, vehicle_type, capacity, status, assigned_route_id)"
            )
            .eq("vehicles.is_active", True)
            .execute()
        )

        return [
            VehicleResponse(
                id=v["vehicles"]["id"],
                vehicle_id=v["vehicles"]["vehicle_id"],
                name=v["vehicles"]["name"],
                name_ar=v["vehicles"]["name_ar"],
                vehicle_type=v["vehicles"]["vehicle_type"],
                capacity=v["vehicles"]["capacity"],
                status=v["vehicles"]["status"],
                assigned_route_id=v["vehicles"].get("assigned_route_id"),
                latitude=v.get("latitude"),
                longitude=v.get("longitude"),
                speed_kmh=v.get("speed_kmh"),
                occupancy_pct=v.get("occupancy_pct"),
                recorded_at=v.get("recorded_at"),
            )
            for v in (result.data or [])
            if v.get("vehicles")
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch vehicles",
        )


@router.get("/vehicles/positions", response_model=List[dict])
async def get_vehicle_positions():
    """Get latest vehicle positions (lightweight endpoint for map updates)."""
    db = get_db()

    try:
        result = (
            db.table("vehicle_positions_latest")
            .select(
                "vehicle_id, latitude, longitude, speed_kmh, occupancy_pct, recorded_at"
            )
            .execute()
        )

        return result.data or []

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch positions",
        )


@router.get("/stream")
async def stream_positions():
    """
    Server-sent events (SSE) stream of vehicle position updates.
    Polls every 2 seconds for up to 25 seconds (Vercel hobby timeout).
    """
    db = get_db()

    async def generate():
        start_time = time.time()
        max_duration = 25

        while time.time() - start_time < max_duration:
            try:
                result = (
                    db.table("vehicle_positions_latest")
                    .select("*, vehicles(name, name_ar)")
                    .execute()
                )

                for pos in (result.data or []):
                    vehicle = pos.get("vehicles", {})
                    data = PositionData(
                        vehicle_id=pos.get("vehicle_id"),
                        vehicle_name=vehicle.get("name", ""),
                        vehicle_name_ar=vehicle.get("name_ar", ""),
                        latitude=pos.get("latitude", 0),
                        longitude=pos.get("longitude", 0),
                        speed_kmh=pos.get("speed_kmh"),
                        occupancy_pct=pos.get("occupancy_pct"),
                        timestamp=pos.get(
                            "recorded_at", datetime.utcnow().isoformat()
                        ),
                    )
                    yield f"data: {data.json()}\n\n"

                await asyncio.sleep(2)

            except Exception as e:
                yield f"data: {{\"error\": \"stream_error\"}}\n\n"
                await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@router.get("/stats", response_model=dict)
async def get_fleet_stats():
    """Get fleet statistics and real-time metrics."""
    db = get_db()

    try:
        vehicles_result = (
            db.table("vehicles")
            .select("id, status", count="exact")
            .eq("is_active", True)
            .execute()
        )

        vehicles = vehicles_result.data or []
        active_count = len([v for v in vehicles if v["status"] == "active"])
        idle_count = len([v for v in vehicles if v["status"] == "idle"])
        maintenance_count = len([v for v in vehicles if v["status"] == "maintenance"])

        routes_result = (
            db.table("routes")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )
        stops_result = (
            db.table("stops")
            .select("id", count="exact")
            .eq("is_active", True)
            .execute()
        )
        drivers_result = (
            db.table("users").select("id, is_active").eq("role", "driver").execute()
        )

        active_drivers = (
            len([d for d in drivers_result.data if d["is_active"]])
            if drivers_result.data
            else 0
        )

        positions_result = (
            db.table("vehicle_positions_latest").select("occupancy_pct").execute()
        )
        occupancy_values = [
            p["occupancy_pct"]
            for p in positions_result.data
            if p.get("occupancy_pct") is not None
        ]
        avg_occupancy = (
            sum(occupancy_values) / len(occupancy_values) if occupancy_values else None
        )

        return {
            "total_vehicles": vehicles_result.count or 0,
            "active_vehicles": active_count,
            "idle_vehicles": idle_count,
            "maintenance_vehicles": maintenance_count,
            "total_routes": routes_result.count or 0,
            "total_stops": stops_result.count or 0,
            "total_drivers": drivers_result.count or 0,
            "active_drivers": active_drivers,
            "avg_occupancy_pct": round(avg_occupancy, 1) if avg_occupancy else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch stats",
        )


@router.get("/schedules/{route_id}", response_model=List[ScheduleResponse])
async def get_route_schedule(route_id: str):
    """Get schedule for a route by day of week."""
    db = get_db()

    try:
        result = (
            db.table("schedules").select("*").eq("route_id", route_id).execute()
        )

        return [
            ScheduleResponse(
                id=s["id"],
                route_id=s["route_id"],
                day_of_week=s["day_of_week"],
                first_departure=s["first_departure"],
                last_departure=s["last_departure"],
                frequency_min=s["frequency_min"],
            )
            for s in result.data
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch schedule",
        )


_GTFS_DIR = Path(__file__).parent.parent.parent / "db" / "gtfs"

_GTFS_FILES = [
    "agency.txt",
    "stops.txt",
    "routes.txt",
    "trips.txt",
    "stop_times.txt",
    "calendar.txt",
    "calendar_dates.txt",
    "shapes.txt",
    "feed_info.txt",
]


@router.get(
    "/gtfs/static",
    summary="GTFS Static feed download",
    description=(
        "Returns a ZIP archive of the GTFS static feed conforming to the "
        "General Transit Feed Specification. Suitable for submission to "
        "Google Maps, Apple Maps, and other GTFS-compatible trip planners."
    ),
    responses={
        200: {
            "content": {"application/zip": {}},
            "description": "GTFS static feed ZIP archive",
        }
    },
)
async def gtfs_static_feed():
    """Download the GTFS static feed as a ZIP file."""
    buf = io.BytesIO()
    missing = []

    with zipfile.ZipFile(buf, mode="w", compression=zipfile.ZIP_DEFLATED) as zf:
        for filename in _GTFS_FILES:
            filepath = _GTFS_DIR / filename
            if filepath.exists():
                zf.write(filepath, arcname=filename)
            else:
                missing.append(filename)

    if missing and len(missing) == len(_GTFS_FILES):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GTFS static files not found on server",
        )

    buf.seek(0)
    return Response(
        content=buf.read(),
        media_type="application/zip",
        headers={
            "Content-Disposition": "attachment; filename=damascus-transit-gtfs.zip",
            "X-GTFS-Version": "1.0",
            "X-Missing-Files": ",".join(missing) if missing else "",
        },
    )


@router.get("/alerts/active", response_model=List[AlertResponse])
async def get_active_alerts():
    """Get all unresolved alerts."""
    db = get_db()

    try:
        result = (
            db.table("alerts")
            .select("*")
            .eq("is_resolved", False)
            .order("created_at", desc=True)
            .execute()
        )

        return [
            AlertResponse(
                id=a["id"],
                vehicle_id=a["vehicle_id"],
                alert_type=a["alert_type"],
                severity=a["severity"],
                title=a["title"],
                title_ar=a["title_ar"],
                description=a.get("description"),
                is_resolved=a["is_resolved"],
                created_at=a["created_at"],
            )
            for a in result.data
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch alerts",
        )
