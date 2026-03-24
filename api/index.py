"""
DamascusTransit FastAPI Backend - Production Server
Handles real-time vehicle tracking, route management, driver dispatch, and fleet analytics.
Deployed on Vercel with Supabase PostgreSQL backend.
"""

import os
import time
import asyncio
from datetime import datetime, timedelta
from typing import Optional, List, Literal
from decimal import Decimal

from fastapi import FastAPI, Depends, HTTPException, status, Query, Response
from fastapi.security import HTTPBearer
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, EmailStr, Field, validator
from dotenv import load_dotenv

from lib.database import get_db, SupabaseDB
from lib.auth import (
    get_current_user,
    require_role,
    create_access_token,
    hash_password,
    verify_password,
    CurrentUser,
)

load_dotenv()

# Initialize FastAPI app
app = FastAPI(
    title="DamascusTransit API",
    description="Real-time transit tracking and fleet management",
    version="1.0.0",
)

# Security
TRACCAR_WEBHOOK_SECRET = os.getenv("TRACCAR_WEBHOOK_SECRET", "")

# ============================================================================
# Pydantic Models
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str
    database: bool


class LoginRequest(BaseModel):
    """Login request with credentials."""

    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


class UserCreate(BaseModel):
    """Create user request (admin only)."""

    email: EmailStr
    password: str
    full_name: str
    full_name_ar: Optional[str] = None
    role: Literal["admin", "dispatcher", "driver", "viewer"] = "viewer"
    phone: Optional[str] = None


class UserUpdate(BaseModel):
    """Update user request."""

    full_name: Optional[str] = None
    full_name_ar: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(BaseModel):
    """User response model."""

    id: str
    email: str
    full_name: str
    full_name_ar: Optional[str] = None
    role: str
    phone: Optional[str] = None
    is_active: bool
    created_at: Optional[str] = None


class RouteResponse(BaseModel):
    """Route response with basic info."""

    id: str
    route_id: str
    name: str
    name_ar: str
    route_type: str
    color: Optional[str] = None
    distance_km: Optional[float] = None
    avg_duration_min: Optional[int] = None
    fare_syp: Optional[float] = None
    stop_count: Optional[int] = 0


class StopResponse(BaseModel):
    """Stop response model."""

    id: str
    stop_id: str
    name: str
    name_ar: str
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    has_shelter: bool
    is_active: bool


class VehicleResponse(BaseModel):
    """Vehicle response with latest position."""

    id: str
    vehicle_id: str
    name: str
    name_ar: str
    vehicle_type: str
    capacity: int
    status: str
    assigned_route_id: Optional[str] = None
    assigned_driver_id: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    speed_kmh: Optional[float] = None
    occupancy_pct: Optional[int] = None
    recorded_at: Optional[str] = None


class PositionUpdate(BaseModel):
    """Driver position update."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed_kmh: Optional[float] = Field(None, ge=0)
    heading: Optional[int] = Field(None, ge=0, le=360)


class TripStart(BaseModel):
    """Start trip request."""

    route_id: str
    scheduled_departure: Optional[datetime] = None


class TripEnd(BaseModel):
    """End trip request."""

    passenger_count: Optional[int] = Field(None, ge=0)


class PassengerCountUpdate(BaseModel):
    """Update passenger count in trip."""

    passenger_count: int = Field(..., ge=0)


class VehicleCreate(BaseModel):
    """Create vehicle request."""

    vehicle_id: str
    name: str
    name_ar: str
    vehicle_type: Literal["bus", "microbus", "taxi"]
    capacity: int = Field(..., ge=1)
    gps_device_id: Optional[str] = None
    is_real_gps: bool = True


class VehicleUpdate(BaseModel):
    """Update vehicle request."""

    name: Optional[str] = None
    name_ar: Optional[str] = None
    capacity: Optional[int] = None
    status: Optional[Literal["active", "idle", "maintenance", "decommissioned"]] = None


class VehicleAssign(BaseModel):
    """Assign vehicle to route and driver."""

    route_id: str
    driver_id: str


class AlertResponse(BaseModel):
    """Alert response model."""

    id: str
    vehicle_id: str
    alert_type: str
    severity: str
    title: str
    title_ar: str
    description: Optional[str] = None
    is_resolved: bool
    created_at: str


class AlertResolve(BaseModel):
    """Resolve alert request."""

    resolved: bool = True


class ScheduleResponse(BaseModel):
    """Route schedule response."""

    id: str
    route_id: str
    day_of_week: int
    first_departure: str
    last_departure: str
    frequency_min: int


class AnalyticsOverview(BaseModel):
    """Fleet analytics overview."""

    total_vehicles: int
    active_vehicles: int
    idle_vehicles: int
    maintenance_vehicles: int
    total_routes: int
    active_routes: int
    total_stops: int
    total_drivers: int
    active_drivers: int
    avg_occupancy_pct: Optional[float] = None


class PositionData(BaseModel):
    """Vehicle position for streaming."""

    vehicle_id: str
    vehicle_name: str
    vehicle_name_ar: str
    latitude: float
    longitude: float
    speed_kmh: Optional[float]
    occupancy_pct: Optional[int]
    timestamp: str


class NearestStop(BaseModel):
    """Nearest stop result."""

    id: str
    stop_id: str
    name: str
    name_ar: str
    latitude: float
    longitude: float
    distance_m: Optional[float] = None
    has_shelter: bool


# ============================================================================
# Public Endpoints (No Auth)
# ============================================================================


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint.

    Returns:
        Health status including database connectivity
    """
    db = get_db()
    db_healthy = db.health_check()

    return HealthResponse(
        status="healthy" if db_healthy else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        database=db_healthy,
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Authenticate user and return JWT token.

    Args:
        request: Email and password credentials

    Returns:
        JWT access token and user info

    Raises:
        HTTPException: Invalid credentials
    """
    db = get_db()

    try:
        result = db.table("users").select("id, email, password_hash, role").eq("email", request.email).execute()
        users = result.data

        if not users:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        user = users[0]

        # Verify password
        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

        # Generate token
        token = create_access_token(user_id=user["id"], email=user["email"], role=user["role"])

        return TokenResponse(access_token=token, user_id=user["id"], role=user["role"])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/routes", response_model=List[RouteResponse])
async def list_routes():
    """
    List all active routes with stop counts.

    Returns:
        List of active routes
    """
    db = get_db()

    try:
        result = db.table("routes").select("*").eq("is_active", True).execute()
        routes = result.data

        # Get stop counts for each route
        enriched_routes = []
        for route in routes:
            stops_result = db.table("route_stops").select("id", count="exact").eq("route_id", route["id"]).execute()
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/routes/{route_id}", response_model=RouteResponse)
async def get_route(route_id: str):
    """
    Get single route details with stops.

    Args:
        route_id: Route UUID

    Returns:
        Route details with associated stops

    Raises:
        HTTPException: Route not found
    """
    db = get_db()

    try:
        result = db.table("routes").select("*").eq("id", route_id).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Route not found")

        route = result.data[0]

        # Get stop count
        stops_result = db.table("route_stops").select("id", count="exact").eq("route_id", route_id).execute()
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/stops", response_model=List[StopResponse])
async def list_stops():
    """
    List all active stops.

    Returns:
        List of active stops
    """
    db = get_db()

    try:
        result = db.table("stops").select("*").eq("is_active", True).execute()
        stops = result.data

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
            for stop in stops
        ]

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/stops/nearest", response_model=List[NearestStop])
async def find_nearest_stops(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: int = Query(1000, ge=100, le=5000),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Find nearest stops using PostGIS.

    Args:
        lat: Latitude
        lon: Longitude
        radius: Search radius in meters (default 1000)
        limit: Maximum results (default 10)

    Returns:
        Nearest stops sorted by distance
    """
    db = get_db()

    try:
        # Call PostGIS RPC function
        result = db.rpc(
            "find_nearest_stops", {"p_lat": lat, "p_lon": lon, "p_limit": limit, "p_radius_m": radius}
        ).execute()

        stops = result.data or []

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
            for stop in stops
        ]

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/vehicles", response_model=List[VehicleResponse])
async def list_vehicles():
    """
    List all active vehicles with latest positions.

    Returns:
        List of active vehicles with real-time position data
    """
    db = get_db()

    try:
        # Get vehicles with latest positions
        result = db.table("vehicle_positions_latest").select("*, vehicles(id, vehicle_id, name, name_ar, vehicle_type, capacity, status, assigned_route_id)").eq("vehicles.is_active", True).execute()

        vehicles_data = result.data or []

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
            for v in vehicles_data
            if v.get("vehicles")
        ]

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/vehicles/positions", response_model=List[dict])
async def get_vehicle_positions():
    """
    Get latest vehicle positions only (lightweight endpoint).

    Returns:
        Vehicle ID, location, and basic tracking data
    """
    db = get_db()

    try:
        result = db.table("vehicle_positions_latest").select("vehicle_id, latitude, longitude, speed_kmh, occupancy_pct, recorded_at").execute()

        return result.data or []

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/stream")
async def stream_positions():
    """
    Server-sent events (SSE) stream of vehicle position updates.
    Polls vehicle_positions_latest every 2 seconds for up to 25 seconds (Vercel limit).

    Returns:
        Streaming response with position updates
    """
    db = get_db()
    last_timestamp = datetime.utcnow().isoformat()

    async def generate():
        start_time = time.time()
        max_duration = 25  # Vercel hobby timeout

        while time.time() - start_time < max_duration:
            try:
                # Get positions updated since last poll
                result = db.table("vehicle_positions_latest").select("*, vehicles(name, name_ar)").execute()

                positions = result.data or []

                for pos in positions:
                    vehicle = pos.get("vehicles", {})
                    data = PositionData(
                        vehicle_id=pos.get("vehicle_id"),
                        vehicle_name=vehicle.get("name", ""),
                        vehicle_name_ar=vehicle.get("name_ar", ""),
                        latitude=pos.get("latitude", 0),
                        longitude=pos.get("longitude", 0),
                        speed_kmh=pos.get("speed_kmh"),
                        occupancy_pct=pos.get("occupancy_pct"),
                        timestamp=pos.get("recorded_at", datetime.utcnow().isoformat()),
                    )

                    yield f"data: {data.json()}\n\n"

                # Wait 2 seconds before next poll
                await asyncio.sleep(2)

            except Exception as e:
                yield f"data: {{'error': '{str(e)}'}}\n\n"
                await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


@app.get("/api/stats", response_model=dict)
async def get_fleet_stats():
    """
    Get fleet statistics and real-time metrics.

    Returns:
        Fleet overview stats
    """
    db = get_db()

    try:
        # Vehicle counts
        vehicles_result = db.table("vehicles").select("id, status", count="exact").eq("is_active", True).execute()

        active_count = len([v for v in vehicles_result.data if v["status"] == "active"]) if vehicles_result.data else 0
        idle_count = len([v for v in vehicles_result.data if v["status"] == "idle"]) if vehicles_result.data else 0
        maintenance_count = len([v for v in vehicles_result.data if v["status"] == "maintenance"]) if vehicles_result.data else 0

        # Route counts
        routes_result = db.table("routes").select("id", count="exact").eq("is_active", True).execute()

        # Stops count
        stops_result = db.table("stops").select("id", count="exact").eq("is_active", True).execute()

        # Driver counts
        drivers_result = db.table("users").select("id, is_active").eq("role", "driver").execute()

        active_drivers = len([d for d in drivers_result.data if d["is_active"]]) if drivers_result.data else 0

        # Average occupancy
        positions_result = db.table("vehicle_positions_latest").select("occupancy_pct").execute()

        occupancy_values = [p["occupancy_pct"] for p in positions_result.data if p.get("occupancy_pct") is not None]
        avg_occupancy = sum(occupancy_values) / len(occupancy_values) if occupancy_values else None

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/schedules/{route_id}", response_model=List[ScheduleResponse])
async def get_route_schedule(route_id: str):
    """
    Get schedule for a route by day of week.

    Args:
        route_id: Route UUID

    Returns:
        Schedule entries for each day
    """
    db = get_db()

    try:
        result = db.table("schedules").select("*").eq("route_id", route_id).execute()

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/alerts/active", response_model=List[AlertResponse])
async def get_active_alerts():
    """
    Get all unresolved alerts.

    Returns:
        List of active alerts
    """
    db = get_db()

    try:
        result = db.table("alerts").select("*").eq("is_resolved", False).order("created_at", desc=True).execute()

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# Driver Endpoints (Auth: driver role)
# ============================================================================


@app.post("/api/driver/position")
async def report_driver_position(
    position: PositionUpdate,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """
    Report driver's current position.

    Args:
        position: GPS coordinates, speed, heading
        current_user: Authenticated driver

    Returns:
        Success confirmation
    """
    db = get_db()

    try:
        # Get driver's assigned vehicle
        driver_result = db.table("vehicles").select("id, vehicle_id").eq("assigned_driver_id", current_user.user_id).execute()

        if not driver_result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No vehicle assigned")

        vehicle = driver_result.data[0]

        # Call RPC to upsert position
        result = db.rpc(
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/driver/trip/start")
async def start_trip(
    trip: TripStart,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """
    Start a new trip for the driver.

    Args:
        trip: Route and optional scheduled start time
        current_user: Authenticated driver

    Returns:
        Trip ID and confirmation
    """
    db = get_db()

    try:
        # Get driver's vehicle and verify route assignment
        vehicle_result = db.table("vehicles").select("id").eq("assigned_driver_id", current_user.user_id).execute()

        if not vehicle_result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No vehicle assigned")

        vehicle_id = vehicle_result.data[0]["id"]

        # Create trip
        trip_data = {
            "vehicle_id": vehicle_id,
            "route_id": trip.route_id,
            "driver_id": current_user.user_id,
            "status": "in_progress",
            "scheduled_start": trip.scheduled_departure,
            "actual_start": datetime.utcnow().isoformat(),
        }

        result = db.table("trips").insert([trip_data]).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create trip")

        return {"status": "success", "trip_id": result.data[0]["id"], "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/driver/trip/end")
async def end_trip(
    trip_data: TripEnd,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """
    End the driver's current trip.

    Args:
        trip_data: Final passenger count
        current_user: Authenticated driver

    Returns:
        Success confirmation
    """
    db = get_db()

    try:
        # Get current trip
        trip_result = db.table("trips").select("id").eq("driver_id", current_user.user_id).eq("status", "in_progress").execute()

        if not trip_result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active trip")

        trip_id = trip_result.data[0]["id"]

        # Update trip
        update_data = {
            "status": "completed",
            "actual_end": datetime.utcnow().isoformat(),
            "passenger_count": trip_data.passenger_count,
        }

        db.table("trips").update(update_data).eq("id", trip_id).execute()

        return {"status": "success", "trip_id": trip_id, "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/driver/trip/passenger-count")
async def update_passenger_count(
    data: PassengerCountUpdate,
    current_user: CurrentUser = Depends(require_role("driver")),
):
    """
    Update passenger count for current trip.

    Args:
        data: New passenger count
        current_user: Authenticated driver

    Returns:
        Success confirmation
    """
    db = get_db()

    try:
        # Get current trip
        trip_result = db.table("trips").select("id").eq("driver_id", current_user.user_id).eq("status", "in_progress").execute()

        if not trip_result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active trip")

        trip_id = trip_result.data[0]["id"]

        # Update passenger count
        db.table("trips").update({"passenger_count": data.passenger_count}).eq("id", trip_id).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# Admin Endpoints (Auth: admin, dispatcher role)
# ============================================================================


@app.get("/api/admin/users", response_model=List[UserResponse])
async def list_users(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    List all users.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        List of users
    """
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/admin/users", response_model=UserResponse)
async def create_user(
    user_data: UserCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Create a new user (admin only).

    Args:
        user_data: User details
        current_user: Authenticated admin

    Returns:
        Created user
    """
    db = get_db()

    try:
        # Check if email exists
        existing = db.table("users").select("id").eq("email", user_data.email).execute()

        if existing.data:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

        # Create user
        hashed_password = hash_password(user_data.password)

        new_user = {
            "email": user_data.email,
            "password_hash": hashed_password,
            "full_name": user_data.full_name,
            "full_name_ar": user_data.full_name_ar,
            "role": user_data.role,
            "phone": user_data.phone,
            "is_active": True,
        }

        result = db.table("users").insert([new_user]).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/admin/users/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: str,
    user_data: UserUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Update user details.

    Args:
        user_id: User UUID
        user_data: Fields to update
        current_user: Authenticated admin

    Returns:
        Updated user
    """
    db = get_db()

    try:
        # Build update dict
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

        result = db.table("users").update(update_dict).eq("id", user_id).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/admin/vehicles", response_model=List[VehicleResponse])
async def list_all_vehicles(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    List all vehicles including inactive ones.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        All vehicles
    """
    db = get_db()

    try:
        result = db.table("vehicle_positions_latest").select("*, vehicles(*)").execute()

        vehicles_data = result.data or []

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
            for v in vehicles_data
            if v.get("vehicles")
        ]

    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/admin/vehicles", response_model=VehicleResponse)
async def create_vehicle(
    vehicle_data: VehicleCreate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Create a new vehicle.

    Args:
        vehicle_data: Vehicle details
        current_user: Authenticated admin

    Returns:
        Created vehicle
    """
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
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create vehicle")

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/admin/vehicles/{vehicle_id}", response_model=VehicleResponse)
async def update_vehicle(
    vehicle_id: str,
    vehicle_data: VehicleUpdate,
    current_user: CurrentUser = Depends(require_role("admin")),
):
    """
    Update vehicle details.

    Args:
        vehicle_id: Vehicle UUID
        vehicle_data: Fields to update
        current_user: Authenticated admin

    Returns:
        Updated vehicle
    """
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
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update")

        result = db.table("vehicles").update(update_dict).eq("id", vehicle_id).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.post("/api/admin/vehicles/{vehicle_id}/assign")
async def assign_vehicle(
    vehicle_id: str,
    assignment: VehicleAssign,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Assign vehicle to route and driver.

    Args:
        vehicle_id: Vehicle UUID
        assignment: Route and driver IDs
        current_user: Authenticated admin/dispatcher

    Returns:
        Success confirmation
    """
    db = get_db()

    try:
        update_data = {
            "assigned_route_id": assignment.route_id,
            "assigned_driver_id": assignment.driver_id,
        }

        result = db.table("vehicles").update(update_data).eq("id", vehicle_id).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found")

        # Log to audit
        audit_entry = {
            "admin_id": current_user.user_id,
            "action": "vehicle_assigned",
            "details": f"Vehicle {vehicle_id} assigned to route {assignment.route_id}, driver {assignment.driver_id}",
        }
        db.table("audit_log").insert([audit_entry]).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/admin/alerts", response_model=List[AlertResponse])
async def list_all_alerts(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get all alerts (resolved and unresolved).

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        All alerts
    """
    db = get_db()

    try:
        result = db.table("alerts").select("*").order("created_at", desc=True).execute()

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.put("/api/admin/alerts/{alert_id}/resolve")
async def resolve_alert(
    alert_id: str,
    alert_data: AlertResolve,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Resolve or unresolve an alert.

    Args:
        alert_id: Alert UUID
        alert_data: Resolved status
        current_user: Authenticated admin/dispatcher

    Returns:
        Success confirmation
    """
    db = get_db()

    try:
        update_data = {"is_resolved": alert_data.resolved, "resolved_at": datetime.utcnow().isoformat() if alert_data.resolved else None}

        result = db.table("alerts").update(update_data).eq("id", alert_id).execute()

        if not result.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/admin/trips", response_model=List[dict])
async def list_trips(
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    List trips with optional filtering.

    Args:
        vehicle_id: Filter by vehicle
        driver_id: Filter by driver
        status_filter: Filter by trip status
        current_user: Authenticated admin/dispatcher

    Returns:
        List of trips
    """
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@app.get("/api/admin/analytics/overview", response_model=AnalyticsOverview)
async def get_analytics_overview(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get fleet analytics overview for dashboard.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        Fleet analytics
    """
    db = get_db()

    try:
        # Vehicle counts
        vehicles_result = db.table("vehicles").select("status", count="exact").execute()

        vehicles = vehicles_result.data or []
        active_vehicles = len([v for v in vehicles if v.get("status") == "active"])
        idle_vehicles = len([v for v in vehicles if v.get("status") == "idle"])
        maintenance_vehicles = len([v for v in vehicles if v.get("status") == "maintenance"])

        # Routes
        routes_result = db.table("routes").select("id", count="exact").eq("is_active", True).execute()

        # Stops
        stops_result = db.table("stops").select("id", count="exact").eq("is_active", True).execute()

        # Drivers
        drivers_result = db.table("users").select("is_active").eq("role", "driver").execute()

        drivers = drivers_result.data or []
        active_drivers = len([d for d in drivers if d.get("is_active")])

        # Average occupancy
        positions_result = db.table("vehicle_positions_latest").select("occupancy_pct").execute()

        positions = positions_result.data or []
        occupancy_values = [p["occupancy_pct"] for p in positions if p.get("occupancy_pct") is not None]
        avg_occupancy = sum(occupancy_values) / len(occupancy_values) if occupancy_values else None

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


# ============================================================================
# Traccar Webhook Endpoints (Secured by TRACCAR_WEBHOOK_SECRET)
# ============================================================================


def verify_traccar_signature(request_body: str, signature: str) -> bool:
    """
    Verify Traccar webhook signature using HMAC.

    Args:
        request_body: Request body string
        signature: X-Traccar-Signature header value

    Returns:
        True if signature is valid
    """
    import hashlib
    import hmac

    computed = hmac.new(TRACCAR_WEBHOOK_SECRET.encode(), request_body.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(computed, signature)


class TraccarPosition(BaseModel):
    """Traccar position webhook payload."""

    deviceId: int
    latitude: float
    longitude: float
    altitude: Optional[float] = None
    speed: Optional[float] = None
    heading: Optional[float] = None
    accuracy: Optional[float] = None
    timestamp: int


class TraccarEvent(BaseModel):
    """Traccar event webhook payload."""

    eventId: Optional[int] = None
    type: str
    serverTime: int
    deviceId: int
    deviceName: str
    data: dict


@app.post("/api/traccar/position")
async def traccar_position_webhook(
    position: TraccarPosition,
    x_traccar_signature: Optional[str] = None,
):
    """
    Webhook for Traccar GPS position updates.
    Secured by X-Traccar-Signature HMAC header.

    Args:
        position: Position data from Traccar
        x_traccar_signature: HMAC-SHA256 signature

    Returns:
        Success confirmation
    """
    # Verify signature if configured
    if TRACCAR_WEBHOOK_SECRET and x_traccar_signature:
        if not verify_traccar_signature(position.json(), x_traccar_signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    db = get_db()

    try:
        # Find vehicle by Traccar device ID
        device_result = db.table("vehicles").select("id, vehicle_id").eq("gps_device_id", str(position.deviceId)).execute()

        if not device_result.data:
            # Device not found - log and ignore gracefully
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle = device_result.data[0]

        # Upsert position via RPC
        db.rpc(
            "upsert_vehicle_position",
            {
                "p_vehicle_id": vehicle["id"],
                "p_lat": position.latitude,
                "p_lon": position.longitude,
                "p_speed": position.speed or 0,
                "p_heading": position.heading or 0,
                "p_source": "traccar",
                "p_route_id": None,
                "p_occupancy": None,
            },
        ).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except Exception as e:
        # Log but don't fail the webhook
        print(f"Traccar position webhook error: {e}")
        return {"status": "error", "detail": str(e)}


@app.post("/api/traccar/event")
async def traccar_event_webhook(
    event: TraccarEvent,
    x_traccar_signature: Optional[str] = None,
):
    """
    Webhook for Traccar events (engine on/off, speeding, etc).
    Secured by X-Traccar-Signature HMAC header.

    Args:
        event: Event data from Traccar
        x_traccar_signature: HMAC-SHA256 signature

    Returns:
        Success confirmation
    """
    # Verify signature if configured
    if TRACCAR_WEBHOOK_SECRET and x_traccar_signature:
        if not verify_traccar_signature(event.json(), x_traccar_signature):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid signature")

    db = get_db()

    try:
        # Find vehicle by Traccar device ID
        device_result = db.table("vehicles").select("id").eq("gps_device_id", str(event.deviceId)).execute()

        if not device_result.data:
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle_id = device_result.data[0]["id"]

        # Map Traccar event types to alert types
        event_type_map = {
            "motion": "speeding",
            "overspeed": "speeding",
            "geofenceEnter": "geofence_enter",
            "geofenceExit": "geofence_exit",
            "deviceOffline": "offline",
            "deviceOnline": "online",
        }

        alert_type = event_type_map.get(event.type, event.type)

        # Create alert if critical event
        critical_events = ["overspeed", "geofenceExit", "deviceOffline"]

        if event.type in critical_events:
            alert_data = {
                "vehicle_id": vehicle_id,
                "alert_type": alert_type,
                "severity": "high" if event.type == "overspeed" else "medium",
                "title": f"Alert: {event.type}",
                "title_ar": f"تنبيه: {event.type}",
                "description": f"Event from Traccar: {event.data}",
                "is_resolved": False,
            }

            db.table("alerts").insert([alert_data]).execute()

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except Exception as e:
        print(f"Traccar event webhook error: {e}")
        return {"status": "error", "detail": str(e)}


# ============================================================================
# Error Handlers and Middleware
# ============================================================================


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    """Handle HTTP exceptions with standard response format."""
    return {
        "error": exc.detail,
        "status_code": exc.status_code,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.get("/")
async def root():
    """Root endpoint - API documentation redirect."""
    return {"message": "DamascusTransit API", "docs": "/docs", "health": "/api/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
