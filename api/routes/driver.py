"""
Driver routes: position reporting, trip management, passenger counts.
All endpoints require driver role authentication.
"""

import asyncio
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status

from lib.database import get_db
from lib.auth import require_role, CurrentUser
from api.models import PositionUpdate, TripStart, TripEnd, PassengerCountUpdate

router = APIRouter(prefix="/api/driver", tags=["Driver"])


async def _handle_geofence_exits(db, vehicle_id: str, lat: float, lon: float):
    """Check for geofence exits and create alerts + broadcast via WebSocket."""
    try:
        from api.routes.ws import broadcast_geofence_alert

        exited = db.rpc(
            "check_geofence_exit",
            {"p_vehicle_id": vehicle_id, "p_new_lat": lat, "p_new_lon": lon},
        ).execute()

        for gf in exited.data or []:
            alert_data = {
                "vehicle_id": vehicle_id,
                "alert_type": "geofence_exit",
                "severity": "warning",
                "title": f"Vehicle exited geofence: {gf['geofence_name']}",
                "title_ar": f"المركبة خرجت من المنطقة: {gf.get('geofence_name_ar') or gf['geofence_name']}",
                "description": f"Vehicle exited geofence boundary '{gf['geofence_name']}'",
                "is_resolved": False,
                "created_at": datetime.utcnow().isoformat(),
            }

            result = db.table("alerts").insert([alert_data]).execute()

            if result.data:
                alert_data["id"] = result.data[0]["id"]
                alert_data["geofence_id"] = str(gf["geofence_id"])
                alert_data["geofence_name"] = gf["geofence_name"]
                await broadcast_geofence_alert(alert_data)

    except Exception:
        pass  # Non-critical: don't fail the position update


@router.post("/position")
async def report_driver_position(
    position: PositionUpdate,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """Report driver's current GPS position."""
    db = get_db()

    try:
        driver_result = (
            db.table("vehicles")
            .select("id, vehicle_id")
            .eq("assigned_driver_id", current_user.user_id)
            .execute()
        )

        if not driver_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No vehicle assigned to this driver",
            )

        vehicle = driver_result.data[0]

        db.rpc(
            "upsert_vehicle_position",
            {
                "p_vehicle_id": vehicle["id"],
                "p_lat": position.latitude,
                "p_lon": position.longitude,
                "p_speed": position.speed_kmh or 0,
                "p_heading": position.heading or 0,
                "p_source": "driver_app",
                "p_route_id": None,
                "p_occupancy": None,
            },
        ).execute()

        # Check for geofence exits and create alerts
        asyncio.create_task(
            _handle_geofence_exits(db, vehicle["id"], position.latitude, position.longitude)
        )

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update position",
        )


@router.post("/trip/start")
async def start_trip(
    trip: TripStart,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """Start a new trip for the authenticated driver."""
    db = get_db()

    try:
        vehicle_result = (
            db.table("vehicles")
            .select("id")
            .eq("assigned_driver_id", current_user.user_id)
            .execute()
        )

        if not vehicle_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No vehicle assigned to this driver",
            )

        vehicle_id = vehicle_result.data[0]["id"]

        # Check for existing active trip
        active_trip = (
            db.table("trips")
            .select("id")
            .eq("driver_id", current_user.user_id)
            .eq("status", "in_progress")
            .execute()
        )

        if active_trip.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="You already have an active trip. End it before starting a new one.",
            )

        trip_data = {
            "vehicle_id": vehicle_id,
            "route_id": trip.route_id,
            "driver_id": current_user.user_id,
            "status": "in_progress",
            "scheduled_start": trip.scheduled_departure.isoformat() if trip.scheduled_departure else None,
            "actual_start": datetime.utcnow().isoformat(),
        }

        result = db.table("trips").insert([trip_data]).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create trip",
            )

        return {
            "status": "success",
            "trip_id": result.data[0]["id"],
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to start trip",
        )


@router.post("/trip/end")
async def end_trip(
    trip_data: TripEnd,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """End the driver's current active trip."""
    db = get_db()

    try:
        trip_result = (
            db.table("trips")
            .select("id")
            .eq("driver_id", current_user.user_id)
            .eq("status", "in_progress")
            .execute()
        )

        if not trip_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active trip found",
            )

        trip_id = trip_result.data[0]["id"]

        update_data = {
            "status": "completed",
            "actual_end": datetime.utcnow().isoformat(),
            "passenger_count": trip_data.passenger_count,
        }

        db.table("trips").update(update_data).eq("id", trip_id).execute()

        return {
            "status": "success",
            "trip_id": trip_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to end trip",
        )


@router.post("/trip/passenger-count")
async def update_passenger_count(
    data: PassengerCountUpdate,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """Update passenger count for the current active trip."""
    db = get_db()

    try:
        trip_result = (
            db.table("trips")
            .select("id")
            .eq("driver_id", current_user.user_id)
            .eq("status", "in_progress")
            .execute()
        )

        if not trip_result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No active trip found",
            )

        trip_id = trip_result.data[0]["id"]

        db.table("trips").update({"passenger_count": data.passenger_count}).eq(
            "id", trip_id
        ).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update passenger count",
        )
