"""
Admin routes: user management, vehicle management, alerts, trips, analytics.
All endpoints require admin or dispatcher role authentication.
"""

from datetime import datetime
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, status

from lib.database import get_db
from lib.auth import require_role, CurrentUser, hash_password
from api.models import (
    UserCreate,
    UserUpdate,
    UserResponse,
    VehicleResponse,
    VehicleCreate,
    VehicleUpdate,
    VehicleAssign,
    AlertResponse,
    AlertResolve,
    AnalyticsOverview,
    GeofenceCreate,
    GeofenceUpdate,
    GeofenceResponse,
)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


# ============================================================================
# User Management
# ============================================================================


@router.get("/users", response_model=List[UserResponse])
async def list_users(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """List all users (admin/dispatcher only)."""
    db = get_db()

    try:
        result = db.table("users").select("*").execute()

        return [
            UserResponse(
                id=u["id"],
                email=u["email"],
                full_name=u["full_name"],
                full_name_ar=u.get("full_name_ar"),
                role=u["role"],
                phone=u.get("phone"),
                is_active=u["is_active"],
                created_at=u.get("created_at"),
            )
            for u in result.data
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch users",
        )


@router.post("/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Create a new user (admin only). New users must change password on first login."""
    db = get_db()

    try:
        existing = (
            db.table("users").select("id").eq("email", user_data.email).execute()
        )

        if existing.data:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already exists",
            )

        hashed_password = hash_password(user_data.password)

        new_user = {
            "email": user_data.email,
            "password_hash": hashed_password,
            "full_name": user_data.full_name,
            "full_name_ar": user_data.full_name_ar,
            "role": user_data.role,
            "phone": user_data.phone,
            "is_active": True,
            "must_change_password": True,  # Force password change on first login
        }

        result = db.table("users").insert([new_user]).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user",
            )

        created_user = result.data[0]

        return UserResponse(
            id=created_user["id"],
            email=created_user["email"],
            full_name=created_user["full_name"],
            full_name_ar=created_user.get("full_name_ar"),
            role=created_user["role"],
            phone=created_user.get("phone"),
            is_active=created_user["is_active"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create user",
        )


@router.put("/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Update user details (admin only)."""
    db = get_db()

    try:
        update_dict = {}
        if user_data.full_name is not None:
            update_dict["full_name"] = user_data.full_name
        if user_data.full_name_ar is not None:
            update_dict["full_name_ar"] = user_data.full_name_ar
        if user_data.phone is not None:
            update_dict["phone"] = user_data.phone
        if user_data.is_active is not None:
            update_dict["is_active"] = user_data.is_active

        if not update_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        result = db.table("users").update(update_dict).eq("id", user_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        updated_user = result.data[0]

        return UserResponse(
            id=updated_user["id"],
            email=updated_user["email"],
            full_name=updated_user["full_name"],
            full_name_ar=updated_user.get("full_name_ar"),
            role=updated_user["role"],
            phone=updated_user.get("phone"),
            is_active=updated_user["is_active"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update user",
        )


# ============================================================================
# Vehicle Management
# ============================================================================


@router.get("/vehicles", response_model=List[VehicleResponse])
async def list_all_vehicles(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """List all vehicles including inactive ones."""
    db = get_db()

    try:
        result = (
            db.table("vehicle_positions_latest").select("*, vehicles(*)").execute()
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


@router.post("/vehicles", response_model=VehicleResponse)
async def create_vehicle(
    vehicle_data: VehicleCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Register a new vehicle (admin only)."""
    db = get_db()

    try:
        new_vehicle = {
            "vehicle_id": vehicle_data.vehicle_id,
            "name": vehicle_data.name,
            "name_ar": vehicle_data.name_ar,
            "vehicle_type": vehicle_data.vehicle_type,
            "capacity": vehicle_data.capacity,
            "status": "idle",
            "gps_device_id": vehicle_data.gps_device_id,
            "is_real_gps": vehicle_data.is_real_gps,
            "is_active": True,
        }

        result = db.table("vehicles").insert([new_vehicle]).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create vehicle",
            )

        created = result.data[0]

        return VehicleResponse(
            id=created["id"],
            vehicle_id=created["vehicle_id"],
            name=created["name"],
            name_ar=created["name_ar"],
            vehicle_type=created["vehicle_type"],
            capacity=created["capacity"],
            status=created["status"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create vehicle",
        )


@router.put("/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: str,
    vehicle_data: VehicleUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Update vehicle details (admin only)."""
    db = get_db()

    try:
        update_dict = {}
        if vehicle_data.name is not None:
            update_dict["name"] = vehicle_data.name
        if vehicle_data.name_ar is not None:
            update_dict["name_ar"] = vehicle_data.name_ar
        if vehicle_data.capacity is not None:
            update_dict["capacity"] = vehicle_data.capacity
        if vehicle_data.status is not None:
            update_dict["status"] = vehicle_data.status

        if not update_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        result = (
            db.table("vehicles").update(update_dict).eq("id", vehicle_id).execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found"
            )

        updated = result.data[0]

        return VehicleResponse(
            id=updated["id"],
            vehicle_id=updated["vehicle_id"],
            name=updated["name"],
            name_ar=updated["name_ar"],
            vehicle_type=updated["vehicle_type"],
            capacity=updated["capacity"],
            status=updated["status"],
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update vehicle",
        )


@router.post("/vehicles/{vehicle_id}/assign")
async def assign_vehicle(
    vehicle_id: str,
    assignment: VehicleAssign,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """Assign vehicle to a route and driver."""
    db = get_db()

    try:
        update_data = {
            "assigned_route_id": assignment.route_id,
            "assigned_driver_id": assignment.driver_id,
        }

        result = (
            db.table("vehicles").update(update_data).eq("id", vehicle_id).execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found"
            )

        # Audit log
        audit_entry = {
            "admin_id": current_user.user_id,
            "action": "vehicle_assigned",
            "details": f"Vehicle {vehicle_id} → route {assignment.route_id}, driver {assignment.driver_id}",
        }
        db.table("audit_log").insert([audit_entry]).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to assign vehicle",
        )


# ============================================================================
# Alerts
# ============================================================================


@router.get("/alerts", response_model=List[AlertResponse])
async def list_all_alerts(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """Get all alerts (resolved and unresolved)."""
    db = get_db()

    try:
        result = (
            db.table("alerts").select("*").order("created_at", desc=True).execute()
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


@router.put("/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    alert_data: AlertResolve,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """Resolve or unresolve an alert."""
    db = get_db()

    try:
        update_data = {
            "is_resolved": alert_data.resolved,
            "resolved_at": datetime.utcnow().isoformat() if alert_data.resolved else None,
        }

        result = db.table("alerts").update(update_data).eq("id", alert_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
            )

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to resolve alert",
        )


# ============================================================================
# Geofences
# ============================================================================


@router.get("/geofences", response_model=List[GeofenceResponse])
async def list_geofences(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """List all geofences with GeoJSON geometry."""
    db = get_db()

    try:
        result = db.rpc("get_geofences", {}).execute()

        return [
            GeofenceResponse(
                id=str(g["id"]),
                name=g["name"],
                name_ar=g.get("name_ar"),
                geometry=g["geometry"] if isinstance(g["geometry"], dict) else __import__("json").loads(g["geometry"]),
                geofence_type=g["geofence_type"],
                speed_limit_kmh=g.get("speed_limit_kmh"),
                is_active=g["is_active"],
                created_at=str(g["created_at"]),
            )
            for g in (result.data or [])
        ]

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch geofences",
        )


@router.post("/geofences", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_geofence(
    data: GeofenceCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Create a new geofence polygon."""
    import json

    db = get_db()

    try:
        geojson_str = json.dumps(data.geojson_polygon)
        result = db.rpc(
            "create_geofence",
            {
                "p_name": data.name,
                "p_name_ar": data.name_ar,
                "p_geojson": geojson_str,
                "p_geofence_type": data.geofence_type,
                "p_speed_limit": data.speed_limit_kmh,
            },
        ).execute()

        return {
            "status": "created",
            "id": result.data,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create geofence",
        )


@router.put("/geofences/{geofence_id}")
async def update_geofence(
    geofence_id: str,
    data: GeofenceUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Update geofence metadata (name, type, speed limit, active status)."""
    db = get_db()

    try:
        update_fields = data.dict(exclude_none=True)
        if not update_fields:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No fields to update",
            )

        result = db.table("geofences").update(update_fields).eq("id", geofence_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Geofence not found",
            )

        return {"status": "updated", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to update geofence",
        )


@router.delete("/geofences/{geofence_id}")
async def delete_geofence(
    geofence_id: str,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """Delete a geofence by ID."""
    db = get_db()

    try:
        result = db.table("geofences").delete().eq("id", geofence_id).execute()

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Geofence not found",
            )

        return {"status": "deleted", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to delete geofence",
        )


# ============================================================================
# Trips & Analytics
# ============================================================================


@router.get("/trips", response_model=List[dict])
async def list_trips(
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """List trips with optional filtering."""
    db = get_db()

    try:
        query = db.table("trips").select("*")

        if vehicle_id:
            query = query.eq("vehicle_id", vehicle_id)
        if driver_id:
            query = query.eq("driver_id", driver_id)
        if status_filter:
            query = query.eq("status", status_filter)

        result = query.order("created_at", desc=True).execute()

        return result.data or []

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch trips",
        )


@router.get("/analytics/overview", response_model=AnalyticsOverview)
async def get_analytics_overview(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """Get fleet analytics overview for the admin dashboard."""
    db = get_db()

    try:
        vehicles_result = (
            db.table("vehicles").select("status", count="exact").execute()
        )
        vehicles = vehicles_result.data or []
        active_vehicles = len([v for v in vehicles if v.get("status") == "active"])
        idle_vehicles = len([v for v in vehicles if v.get("status") == "idle"])
        maintenance_vehicles = len(
            [v for v in vehicles if v.get("status") == "maintenance"]
        )

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
            db.table("users").select("is_active").eq("role", "driver").execute()
        )

        drivers = drivers_result.data or []
        active_drivers = len([d for d in drivers if d.get("is_active")])

        positions_result = (
            db.table("vehicle_positions_latest").select("occupancy_pct").execute()
        )
        positions = positions_result.data or []
        occupancy_values = [
            p["occupancy_pct"]
            for p in positions
            if p.get("occupancy_pct") is not None
        ]
        avg_occupancy = (
            sum(occupancy_values) / len(occupancy_values) if occupancy_values else None
        )

        return AnalyticsOverview(
            total_vehicles=vehicles_result.count or 0,
            active_vehicles=active_vehicles,
            idle_vehicles=idle_vehicles,
            maintenance_vehicles=maintenance_vehicles,
            total_routes=routes_result.count or 0,
            active_routes=routes_result.count or 0,
            total_stops=stops_result.count or 0,
            total_drivers=drivers_result.count or 0,
            active_drivers=active_drivers,
            avg_occupancy_pct=round(avg_occupancy, 1) if avg_occupancy else None,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch analytics",
        )
