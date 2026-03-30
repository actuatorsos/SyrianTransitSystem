"""
Driver routes: position reporting, trip management, passenger counts.
All endpoints require driver role authentication.
"""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status

from lib.database import get_db
from lib.auth import require_role, CurrentUser
from api.models import PositionUpdate, TripStart, TripEnd, PassengerCountUpdate

router = APIRouter(prefix="/api/driver", tags=["Driver"])


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
