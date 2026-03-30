"""
DamascusTransit FastAPI Backend - Production Server (Lightweight Edition)
Handles real-time vehicle tracking, route management, driver dispatch, and fleet analytics.
Deployed on Vercel with Supabase PostgreSQL backend.

LIGHTWEIGHT VERSION: Uses httpx for Supabase REST API, PyJWT for auth, bcrypt directly.
All auth and database code inlined for Vercel Python serverless compatibility.
"""

import os
import json
import time
import asyncio
import hashlib
import hmac
import urllib.parse
import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional, List, Literal

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials as HTTPAuthCredentials
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Redis Cache (Upstash — serverless-compatible, graceful degradation)
# ============================================================================

# Cache TTLs (seconds)
CACHE_TTL_VEHICLES = 5       # vehicle positions — refreshed every 2s by drivers
CACHE_TTL_ROUTES_STOPS = 300  # routes & stops — static reference data
CACHE_TTL_STATS = 30          # fleet stats — lightweight aggregate

# Cache keys
CACHE_KEY_VEHICLES_LIST = "transit:vehicles:list"
CACHE_KEY_VEHICLES_POSITIONS = "transit:vehicles:positions"
CACHE_KEY_ROUTES_LIST = "transit:routes:list"
CACHE_KEY_STATS = "transit:stats"
CACHE_KEY_STOPS_LIST = "transit:stops:list"


def _get_redis_client():
    """Return an Upstash Redis async client, or None if not configured."""
    url = os.getenv("UPSTASH_REDIS_REST_URL", "")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    try:
        from upstash_redis.asyncio import Redis
        return Redis(url=url, token=token)
    except Exception:
        return None


async def _cache_get(key: str):
    """Retrieve a JSON-encoded value from Redis. Returns None on miss or error."""
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set(key: str, value, ttl: int) -> None:
    """Store a JSON-encoded value in Redis with TTL (seconds). Silently fails if unavailable."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        pass


async def _cache_delete(*keys: str) -> None:
    """Invalidate one or more Redis cache keys. Silently fails if unavailable."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.delete(*keys)
    except Exception:
        pass


# ============================================================================
# FastAPI App Initialization
# ============================================================================

app = FastAPI(
    title="DamascusTransit API",
    description="Real-time transit tracking and fleet management",
    version="1.0.0",
)

# CORS: restrict to configured allowed origins; never allow wildcard in production
_cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
if not _allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS env var must be set to a comma-separated list of allowed origins"
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ============================================================================
# JWT Authentication (using PyJWT)
# ============================================================================

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# HTTP Bearer security scheme
security = HTTPBearer()

UserRole = Literal["admin", "dispatcher", "driver", "viewer"]


_PLACEHOLDER_JWT_SECRETS = {"change-me-to-a-random-64-char-string", "secret", ""}


def _get_jwt_secret() -> str:
    """Get JWT secret from environment, enforcing minimum entropy."""
    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret in _PLACEHOLDER_JWT_SECRETS or len(secret) < 32:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not configured or is too weak (minimum 32 characters required)",
        )
    return secret


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    user_id: str
    email: str
    role: UserRole
    exp: datetime
    vehicle_id: Optional[str] = None
    vehicle_route_id: Optional[str] = None


class CurrentUser(BaseModel):
    """Current authenticated user context."""

    user_id: str
    email: str
    role: UserRole
    vehicle_id: Optional[str] = None
    vehicle_route_id: Optional[str] = None


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(plain_password.encode(), hashed_password.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(
    user_id: str,
    email: str,
    role: UserRole,
    expires_delta: Optional[timedelta] = None,
    vehicle_id: Optional[str] = None,
    vehicle_route_id: Optional[str] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User UUID
        email: User email address
        role: User role (admin, dispatcher, driver, viewer)
        expires_delta: Custom expiration time (default: 24 hours)
        vehicle_id: Assigned vehicle UUID (drivers only, cached to avoid DB lookup)
        vehicle_route_id: Assigned route UUID (drivers only, cached to avoid DB lookup)

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    expire = datetime.utcnow() + expires_delta
    to_encode: dict = {"user_id": user_id, "email": email, "role": role, "exp": expire}

    if vehicle_id is not None:
        to_encode["vehicle_id"] = vehicle_id
    if vehicle_route_id is not None:
        to_encode["vehicle_route_id"] = vehicle_route_id

    encoded_jwt = jwt.encode(to_encode, _get_jwt_secret(), algorithm=JWT_ALGORITHM)
    return encoded_jwt


def verify_token(token: str) -> TokenPayload:
    """
    Verify and decode a JWT token.

    Args:
        token: JWT token string

    Returns:
        Decoded token payload

    Raises:
        HTTPException: If token is invalid or expired
    """
    try:
        payload = jwt.decode(token, _get_jwt_secret(), algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("user_id")
        email: str = payload.get("email")
        role: str = payload.get("role")

        if user_id is None or email is None or role is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
            )

        return TokenPayload(
            user_id=user_id,
            email=email,
            role=role,
            exp=payload.get("exp"),
            vehicle_id=payload.get("vehicle_id"),
            vehicle_route_id=payload.get("vehicle_route_id"),
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )


async def get_current_user(
    credentials: HTTPAuthCredentials = Depends(security),
) -> CurrentUser:
    """
    FastAPI dependency: Extract and verify current user from Bearer token.

    Args:
        credentials: HTTP Bearer token from Authorization header

    Returns:
        Current user context

    Raises:
        HTTPException: If token is invalid or missing
    """
    token = credentials.credentials
    token_payload = verify_token(token)
    return CurrentUser(
        user_id=token_payload.user_id,
        email=token_payload.email,
        role=token_payload.role,
        vehicle_id=token_payload.vehicle_id,
        vehicle_route_id=token_payload.vehicle_route_id,
    )


def require_role(*allowed_roles: UserRole):
    """
    FastAPI dependency factory: Require specific user role(s).

    Args:
        allowed_roles: One or more allowed roles

    Returns:
        Dependency function
    """

    async def role_checker(
        current_user: CurrentUser = Depends(get_current_user),
    ) -> CurrentUser:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions. Required roles: {', '.join(allowed_roles)}",
            )
        return current_user

    return role_checker


def optional_auth(
    credentials: Optional[HTTPAuthCredentials] = Depends(security),
) -> Optional[CurrentUser]:
    """
    FastAPI dependency: Optional authentication (returns None if no token).

    Args:
        credentials: Optional HTTP Bearer token

    Returns:
        Current user context or None
    """
    if credentials is None:
        return None
    token_payload = verify_token(credentials.credentials)
    return CurrentUser(
        user_id=token_payload.user_id,
        email=token_payload.email,
        role=token_payload.role,
        vehicle_id=token_payload.vehicle_id,
        vehicle_route_id=token_payload.vehicle_route_id,
    )


# ============================================================================
# Supabase REST API Helpers (using httpx)
# ============================================================================


def _supabase_headers(use_service_key: bool = False) -> dict:
    """Get headers for Supabase REST API requests.

    Args:
        use_service_key: Use the service-role key (bypasses RLS). Only pass True
                         for privileged server-side operations. Public/user-scoped
                         reads must use the anon key so RLS policies are enforced.
    """
    if use_service_key:
        key = os.getenv("SUPABASE_SERVICE_KEY", "")
        if not key:
            raise HTTPException(
                status_code=500, detail="SUPABASE_SERVICE_KEY not configured"
            )
    else:
        key = os.getenv("SUPABASE_ANON_KEY", os.getenv("SUPABASE_KEY", ""))
        if not key:
            raise HTTPException(
                status_code=500, detail="SUPABASE_ANON_KEY not configured"
            )
    return {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }


def _supabase_url(path: str) -> str:
    """Build Supabase REST API URL."""
    base = os.getenv("SUPABASE_URL", "")
    return f"{base}/rest/v1/{path}"


async def _supabase_get(path: str, params: Optional[dict] = None) -> list:
    """Make GET request to Supabase REST API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                _supabase_url(path), headers=_supabase_headers(), params=params or {}
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else [data] if data else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database query failed: {str(e)}")


async def _supabase_post(path: str, data: dict) -> dict:
    """Make POST request to Supabase REST API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                _supabase_url(path), headers=_supabase_headers(), json=data
            )
            resp.raise_for_status()
            return resp.json() if resp.content else {}
    except Exception as e:
        raise HTTPException(
            status_code=500, detail=f"Database operation failed: {str(e)}"
        )


async def _supabase_patch(path: str, data: dict) -> list:
    """Make PATCH request to Supabase REST API (update)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.patch(
                _supabase_url(path), headers=_supabase_headers(), json=data
            )
            resp.raise_for_status()
            result = resp.json()
            return result if isinstance(result, list) else [result] if result else []
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database update failed: {str(e)}")


async def _supabase_delete(path: str) -> None:
    """Make DELETE request to Supabase REST API."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.delete(_supabase_url(path), headers=_supabase_headers())
            resp.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database delete failed: {str(e)}")


async def _supabase_rpc(func_name: str, params: dict) -> any:
    """Call Supabase RPC (PostgreSQL function)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/{func_name}",
                headers=_supabase_headers(),
                json=params,
            )
            resp.raise_for_status()
            return resp.json()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"RPC call failed: {str(e)}")


async def _health_check() -> bool:
    """Check database connectivity."""
    try:
        await _supabase_get("users?select=id&limit=1")
        return True
    except Exception:
        return False


# ============================================================================
# Security Configuration
# ============================================================================

TRACCAR_WEBHOOK_SECRET = os.getenv("TRACCAR_WEBHOOK_SECRET", "")
if not TRACCAR_WEBHOOK_SECRET:
    import warnings

    warnings.warn(
        "TRACCAR_WEBHOOK_SECRET is not set — Traccar webhook endpoints will reject all requests "
        "until this is configured.",
        RuntimeWarning,
        stacklevel=1,
    )

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

    email: str
    password: str


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str


class UserCreate(BaseModel):
    """Create user request (admin only)."""

    email: str
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
    db_healthy = await _health_check()

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
    try:
        users = await _supabase_get(
            f"users?email=eq.{urllib.parse.quote(request.email, safe='')}&select=id,email,password_hash,role"
        )

        if not users:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        user = users[0]

        # Verify password
        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        # For drivers, cache vehicle assignment in the token to avoid a DB
        # lookup on every position update (eliminates the SELECT per POST /api/driver/position)
        vehicle_id = None
        vehicle_route_id = None
        if user["role"] == "driver":
            driver_vehicles = await _supabase_get(
                f"vehicles?assigned_driver_id=eq.{user['id']}&select=id,assigned_route_id"
            )
            if driver_vehicles:
                vehicle_id = driver_vehicles[0]["id"]
                vehicle_route_id = driver_vehicles[0].get("assigned_route_id")

        # Generate token
        token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            role=user["role"],
            vehicle_id=vehicle_id,
            vehicle_route_id=vehicle_route_id,
        )

        return TokenResponse(access_token=token, user_id=user["id"], role=user["role"])

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/routes", response_model=List[RouteResponse])
async def list_routes():
    """
    List all active routes with stop counts.

    Returns:
        List of active routes
    """
    try:
        cached = await _cache_get(CACHE_KEY_ROUTES_LIST)
        if cached is not None:
            return cached

        routes = await _supabase_get("routes?is_active=eq.true&select=*")

        # Get stop counts for each route
        enriched_routes = []
        for route in routes:
            stops = await _supabase_get(
                f"route_stops?route_id=eq.{route['id']}&select=id"
            )
            stop_count = len(stops)

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

        await _cache_set(
            CACHE_KEY_ROUTES_LIST,
            [r.model_dump() for r in enriched_routes],
            CACHE_TTL_ROUTES_STOPS,
        )
        return enriched_routes

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        cache_key = f"transit:routes:{route_id}"
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        routes = await _supabase_get(f"routes?id=eq.{route_id}&select=*")

        if not routes:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Route not found"
            )

        route = routes[0]

        # Get stop count
        stops = await _supabase_get(f"route_stops?route_id=eq.{route_id}&select=id")
        stop_count = len(stops)

        result = RouteResponse(
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

        await _cache_set(cache_key, result.model_dump(), CACHE_TTL_ROUTES_STOPS)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/stops", response_model=List[StopResponse])
async def list_stops():
    """
    List all active stops.

    Returns:
        List of active stops
    """
    try:
        cached = await _cache_get(CACHE_KEY_STOPS_LIST)
        if cached is not None:
            return cached

        stops = await _supabase_get("stops?is_active=eq.true&select=*")

        result = [
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

        await _cache_set(
            CACHE_KEY_STOPS_LIST,
            [r.model_dump() for r in result],
            CACHE_TTL_ROUTES_STOPS,
        )
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/stops/nearest", response_model=List[NearestStop])
async def find_nearest_stops(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: int = Query(1000, ge=100, le=5000),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Find nearest stops using PostGIS RPC.

    Args:
        lat: Latitude
        lon: Longitude
        radius: Search radius in meters (default 1000)
        limit: Maximum results (default 10)

    Returns:
        Nearest stops sorted by distance
    """
    try:
        # Call PostGIS RPC function
        stops = await _supabase_rpc(
            "find_nearest_stops",
            {"p_lat": lat, "p_lon": lon, "p_limit": limit, "p_radius_m": radius},
        )

        stops = stops if isinstance(stops, list) else [stops] if stops else []

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/vehicles", response_model=List[VehicleResponse])
async def list_vehicles():
    """
    List all active vehicles with latest positions.

    Returns:
        List of active vehicles with real-time position data
    """
    try:
        cached = await _cache_get(CACHE_KEY_VEHICLES_LIST)
        if cached is not None:
            return cached

        # Get vehicles with latest positions (join with vehicle_positions_latest)
        positions = await _supabase_get(
            "vehicle_positions_latest?select=*,vehicles(id,vehicle_id,name,name_ar,vehicle_type,capacity,status,assigned_route_id)"
        )

        vehicles_data = positions or []

        result = [
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

        await _cache_set(
            CACHE_KEY_VEHICLES_LIST,
            [r.model_dump() for r in result],
            CACHE_TTL_VEHICLES,
        )
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/vehicles/positions", response_model=List[dict])
async def get_vehicle_positions():
    """
    Get latest vehicle positions only (lightweight endpoint).

    Returns:
        Vehicle ID, location, and basic tracking data
    """
    try:
        cached = await _cache_get(CACHE_KEY_VEHICLES_POSITIONS)
        if cached is not None:
            return cached

        result = await _supabase_get(
            "vehicle_positions_latest?select=vehicle_id,latitude,longitude,speed_kmh,occupancy_pct,recorded_at"
        )

        result = result or []
        await _cache_set(CACHE_KEY_VEHICLES_POSITIONS, result, CACHE_TTL_VEHICLES)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/stream")
async def stream_positions():
    """
    Server-sent events (SSE) stream of vehicle position updates.
    Polls vehicle_positions_latest every 2 seconds for up to 25 seconds (Vercel limit).

    Returns:
        Streaming response with position updates
    """

    async def generate():
        start_time = time.time()
        max_duration = 25  # Vercel hobby timeout

        while time.time() - start_time < max_duration:
            try:
                # Get positions updated since last poll
                positions = await _supabase_get(
                    "vehicle_positions_latest?select=*,vehicles(name,name_ar)"
                )

                positions = positions or []

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
    try:
        cached = await _cache_get(CACHE_KEY_STATS)
        if cached is not None:
            return cached

        # Vehicle counts
        vehicles = await _supabase_get("vehicles?is_active=eq.true&select=id,status")

        active_count = (
            len([v for v in vehicles if v.get("status") == "active"]) if vehicles else 0
        )
        idle_count = (
            len([v for v in vehicles if v.get("status") == "idle"]) if vehicles else 0
        )
        maintenance_count = (
            len([v for v in vehicles if v.get("status") == "maintenance"])
            if vehicles
            else 0
        )

        # Route counts
        routes = await _supabase_get("routes?is_active=eq.true&select=id")

        # Stops count
        stops = await _supabase_get("stops?is_active=eq.true&select=id")

        # Driver counts
        drivers = await _supabase_get("users?role=eq.driver&select=id,is_active")

        active_drivers = (
            len([d for d in drivers if d.get("is_active")]) if drivers else 0
        )

        # Average occupancy
        positions = await _supabase_get("vehicle_positions_latest?select=occupancy_pct")

        occupancy_values = [
            p["occupancy_pct"] for p in positions if p.get("occupancy_pct") is not None
        ]
        avg_occupancy = (
            sum(occupancy_values) / len(occupancy_values) if occupancy_values else None
        )

        result = {
            "total_vehicles": len(vehicles),
            "active_vehicles": active_count,
            "idle_vehicles": idle_count,
            "maintenance_vehicles": maintenance_count,
            "total_routes": len(routes),
            "total_stops": len(stops),
            "total_drivers": len(drivers),
            "active_drivers": active_drivers,
            "avg_occupancy_pct": round(avg_occupancy, 1) if avg_occupancy else None,
            "timestamp": datetime.utcnow().isoformat(),
        }

        await _cache_set(CACHE_KEY_STATS, result, CACHE_TTL_STATS)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/schedules/{route_id}", response_model=List[ScheduleResponse])
async def get_route_schedule(route_id: str):
    """
    Get schedule for a route by day of week.

    Args:
        route_id: Route UUID

    Returns:
        Schedule entries for each day
    """
    try:
        schedules = await _supabase_get(f"schedules?route_id=eq.{route_id}&select=*")

        return [
            ScheduleResponse(
                id=s["id"],
                route_id=s["route_id"],
                day_of_week=s["day_of_week"],
                first_departure=s["first_departure"],
                last_departure=s["last_departure"],
                frequency_min=s["frequency_min"],
            )
            for s in schedules
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/alerts/active", response_model=List[AlertResponse])
async def get_active_alerts():
    """
    Get all unresolved alerts.

    Returns:
        List of active alerts
    """
    try:
        alerts = await _supabase_get(
            "alerts?is_resolved=eq.false&select=*&order=created_at.desc"
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
            for a in alerts
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Prefer the vehicle_id cached in the JWT token (set at login time) to avoid
        # an extra DB SELECT on every position update.  Fall back to a live query only
        # when the token pre-dates this optimisation (vehicle_id absent).
        if current_user.vehicle_id:
            db_vehicle_id = current_user.vehicle_id
            route_id = current_user.vehicle_route_id
        else:
            vehicles = await _supabase_get(
                f"vehicles?assigned_driver_id=eq.{current_user.user_id}&select=id,assigned_route_id"
            )

            if not vehicles:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND, detail="No vehicle assigned"
                )

            db_vehicle_id = vehicles[0]["id"]
            route_id = vehicles[0].get("assigned_route_id")

        # Call RPC to upsert position
        await _supabase_rpc(
            "upsert_vehicle_position",
            {
                "p_vehicle_id": db_vehicle_id,
                "p_lat": position.latitude,
                "p_lon": position.longitude,
                "p_speed": position.speed_kmh or 0,
                "p_heading": position.heading or 0,
                "p_source": "driver_app",
                "p_route_id": route_id,
                "p_occupancy": None,
            },
        )

        # Invalidate vehicle position caches so the next read reflects the new position
        await _cache_delete(CACHE_KEY_VEHICLES_LIST, CACHE_KEY_VEHICLES_POSITIONS)

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Get driver's vehicle and verify route assignment
        vehicles = await _supabase_get(
            f"vehicles?assigned_driver_id=eq.{current_user.user_id}&select=id"
        )

        if not vehicles:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No vehicle assigned"
            )

        vehicle_id = vehicles[0]["id"]

        # Create trip
        trip_data = {
            "vehicle_id": vehicle_id,
            "route_id": trip.route_id,
            "driver_id": current_user.user_id,
            "status": "in_progress",
            "scheduled_start": trip.scheduled_departure,
            "actual_start": datetime.utcnow().isoformat(),
        }

        result = await _supabase_post("trips", trip_data)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create trip",
            )

        return {
            "status": "success",
            "trip_id": result.get("id"),
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Get current trip
        trips = await _supabase_get(
            f"trips?driver_id=eq.{current_user.user_id}&status=eq.in_progress&select=id"
        )

        if not trips:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active trip"
            )

        trip_id = trips[0]["id"]

        # Update trip
        update_data = {
            "status": "completed",
            "actual_end": datetime.utcnow().isoformat(),
            "passenger_count": trip_data.passenger_count,
        }

        await _supabase_patch(f"trips?id=eq.{trip_id}", update_data)

        return {
            "status": "success",
            "trip_id": trip_id,
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Get current trip
        trips = await _supabase_get(
            f"trips?driver_id=eq.{current_user.user_id}&status=eq.in_progress&select=id"
        )

        if not trips:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="No active trip"
            )

        trip_id = trips[0]["id"]

        # Update passenger count
        await _supabase_patch(
            f"trips?id=eq.{trip_id}", {"passenger_count": data.passenger_count}
        )

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        users = await _supabase_get("users?select=*")

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
            for u in users
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Check if email exists
        existing = await _supabase_get(
            f"users?email=eq.{urllib.parse.quote(user_data.email, safe='')}&select=id"
        )

        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="Email already exists"
            )

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

        result = await _supabase_post("users", new_user)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create user",
            )

        created_user = (
            result if isinstance(result, dict) else result[0] if result else {}
        )

        return UserResponse(
            id=created_user.get("id"),
            email=created_user.get("email"),
            full_name=created_user.get("full_name"),
            full_name_ar=created_user.get("full_name_ar"),
            role=created_user.get("role"),
            phone=created_user.get("phone"),
            is_active=created_user.get("is_active"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
            )

        result = await _supabase_patch(f"users?id=eq.{user_id}", update_dict)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        updated_user = result[0] if result else {}

        return UserResponse(
            id=updated_user.get("id"),
            email=updated_user.get("email"),
            full_name=updated_user.get("full_name"),
            full_name_ar=updated_user.get("full_name_ar"),
            role=updated_user.get("role"),
            phone=updated_user.get("phone"),
            is_active=updated_user.get("is_active"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        positions = await _supabase_get("vehicle_positions_latest?select=*,vehicles(*)")

        vehicles_data = positions or []

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
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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

        result = await _supabase_post("vehicles", new_vehicle)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to create vehicle",
            )

        created = result if isinstance(result, dict) else result[0] if result else {}

        return VehicleResponse(
            id=created.get("id"),
            vehicle_id=created.get("vehicle_id"),
            name=created.get("name"),
            name_ar=created.get("name_ar"),
            vehicle_type=created.get("vehicle_type"),
            capacity=created.get("capacity"),
            status=created.get("status"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
                status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
            )

        result = await _supabase_patch(f"vehicles?id=eq.{vehicle_id}", update_dict)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found"
            )

        updated = result[0] if result else {}

        return VehicleResponse(
            id=updated.get("id"),
            vehicle_id=updated.get("vehicle_id"),
            name=updated.get("name"),
            name_ar=updated.get("name_ar"),
            vehicle_type=updated.get("vehicle_type"),
            capacity=updated.get("capacity"),
            status=updated.get("status"),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        update_data = {
            "assigned_route_id": assignment.route_id,
            "assigned_driver_id": assignment.driver_id,
        }

        result = await _supabase_patch(f"vehicles?id=eq.{vehicle_id}", update_data)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle not found"
            )

        # Log to audit
        audit_entry = {
            "admin_id": current_user.user_id,
            "action": "vehicle_assigned",
            "details": f"Vehicle {vehicle_id} assigned to route {assignment.route_id}, driver {assignment.driver_id}",
        }
        await _supabase_post("audit_log", audit_entry)

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        alerts = await _supabase_get("alerts?select=*&order=created_at.desc")

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
            for a in alerts
        ]

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        update_data = {
            "is_resolved": alert_data.resolved,
            "resolved_at": datetime.utcnow().isoformat()
            if alert_data.resolved
            else None,
        }

        result = await _supabase_patch(f"alerts?id=eq.{alert_id}", update_data)

        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found"
            )

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Build query params
        params = []
        if vehicle_id:
            params.append(f"vehicle_id=eq.{vehicle_id}")
        if driver_id:
            params.append(f"driver_id=eq.{driver_id}")
        if status_filter:
            params.append(f"status=eq.{status_filter}")

        query = "trips?select=*&order=created_at.desc"
        if params:
            query = f"trips?{'&'.join(params)}&select=*&order=created_at.desc"

        result = await _supabase_get(query)

        return result or []

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    try:
        # Vehicle counts
        vehicles = await _supabase_get("vehicles?select=status")

        active_vehicles = len([v for v in vehicles if v.get("status") == "active"])
        idle_vehicles = len([v for v in vehicles if v.get("status") == "idle"])
        maintenance_vehicles = len(
            [v for v in vehicles if v.get("status") == "maintenance"]
        )

        # Routes
        routes = await _supabase_get("routes?is_active=eq.true&select=id")

        # Stops
        stops = await _supabase_get("stops?is_active=eq.true&select=id")

        # Drivers
        drivers = await _supabase_get("users?role=eq.driver&select=is_active")

        active_drivers = (
            len([d for d in drivers if d.get("is_active")]) if drivers else 0
        )

        # Average occupancy
        positions = await _supabase_get("vehicle_positions_latest?select=occupancy_pct")

        occupancy_values = [
            p["occupancy_pct"] for p in positions if p.get("occupancy_pct") is not None
        ]
        avg_occupancy = (
            sum(occupancy_values) / len(occupancy_values) if occupancy_values else None
        )

        return AnalyticsOverview(
            total_vehicles=len(vehicles),
            active_vehicles=active_vehicles,
            idle_vehicles=idle_vehicles,
            maintenance_vehicles=maintenance_vehicles,
            total_routes=len(routes),
            active_routes=len(routes),
            total_stops=len(stops),
            total_drivers=len(drivers),
            active_drivers=active_drivers,
            avg_occupancy_pct=round(avg_occupancy, 1) if avg_occupancy else None,
        )

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/admin/analytics/fleet-utilization")
async def get_fleet_utilization(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get fleet utilization over the last 24 hours, bucketed by hour.

    Uses completed trips to infer active vehicle counts per hour.
    Returns hourly active vs idle vehicle counts.
    """
    try:
        from datetime import timezone

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(hours=24)

        # Get all vehicles for total count
        vehicles = await _supabase_get("vehicles?select=id,status")
        total_vehicles = len(vehicles)

        # Get trips in last 24h to compute per-hour active counts
        trips = await _supabase_get(
            f"trips?actual_start=gte.{cutoff.isoformat()}&select=actual_start,actual_end,vehicle_id"
        )

        # Build hourly buckets
        hours = []
        for h in range(23, -1, -1):
            bucket_start = now - timedelta(hours=h + 1)
            bucket_end = now - timedelta(hours=h)
            label = bucket_start.strftime("%H:%M")

            # Count vehicles with an active trip during this hour
            active_ids = set()
            for t in trips:
                t_start_str = t.get("actual_start")
                t_end_str = t.get("actual_end")
                if not t_start_str:
                    continue
                try:
                    t_start = datetime.fromisoformat(t_start_str.replace("Z", "+00:00"))
                    t_end = (
                        datetime.fromisoformat(t_end_str.replace("Z", "+00:00"))
                        if t_end_str
                        else now
                    )
                    # Overlap with bucket
                    if t_start < bucket_end and t_end > bucket_start:
                        active_ids.add(t.get("vehicle_id"))
                except (ValueError, TypeError):
                    continue

            active = len(active_ids)
            idle = max(0, total_vehicles - active)
            hours.append({"hour": label, "active": active, "idle": idle})

        return {"hours": hours, "total": total_vehicles}

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/admin/analytics/route-performance")
async def get_route_performance(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get per-route performance: on-time %, average delay, and trip count
    based on completed trips in the last 7 days.
    """
    try:
        from datetime import timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        routes = await _supabase_get(
            "routes?is_active=eq.true&select=id,name,name_ar,distance_km"
        )
        trips = await _supabase_get(
            f"trips?status=eq.completed&actual_start=gte.{cutoff}"
            "&select=route_id,on_time_pct,scheduled_start,actual_start"
        )

        # Group trips by route
        from collections import defaultdict

        route_trips: dict = defaultdict(list)
        for t in trips:
            route_trips[t["route_id"]].append(t)

        result = []
        for r in routes:
            rt = route_trips.get(r["id"], [])
            trip_count = len(rt)

            on_time_values = [
                t["on_time_pct"] for t in rt if t.get("on_time_pct") is not None
            ]
            avg_on_time = (
                round(sum(on_time_values) / len(on_time_values), 1)
                if on_time_values
                else None
            )

            # Avg delay in minutes: difference between actual_start and scheduled_start
            delays = []
            for t in rt:
                if t.get("scheduled_start") and t.get("actual_start"):
                    try:
                        sched = datetime.fromisoformat(
                            t["scheduled_start"].replace("Z", "+00:00")
                        )
                        actual = datetime.fromisoformat(
                            t["actual_start"].replace("Z", "+00:00")
                        )
                        delay_min = (actual - sched).total_seconds() / 60
                        delays.append(delay_min)
                    except (ValueError, TypeError):
                        pass

            avg_delay = round(sum(delays) / len(delays), 1) if delays else None

            result.append(
                {
                    "route_id": r["id"],
                    "name": r.get("name_ar") or r.get("name"),
                    "trip_count": trip_count,
                    "on_time_pct": avg_on_time,
                    "avg_delay_min": avg_delay,
                    "distance_km": r.get("distance_km"),
                }
            )

        result.sort(key=lambda x: x["trip_count"], reverse=True)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/admin/analytics/driver-scoreboard")
async def get_driver_scoreboard(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get driver scoreboard: trips completed and avg route adherence (on_time_pct)
    based on completed trips in the last 30 days.
    """
    try:
        from datetime import timezone
        from collections import defaultdict

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        drivers = await _supabase_get(
            "users?role=eq.driver&select=id,full_name,full_name_ar,is_active"
        )
        trips = await _supabase_get(
            f"trips?status=eq.completed&actual_start=gte.{cutoff}"
            "&select=driver_id,on_time_pct,distance_km"
        )

        driver_trips: dict = defaultdict(list)
        for t in trips:
            if t.get("driver_id"):
                driver_trips[t["driver_id"]].append(t)

        result = []
        for d in drivers:
            dt = driver_trips.get(d["id"], [])
            trip_count = len(dt)
            on_time_values = [
                t["on_time_pct"] for t in dt if t.get("on_time_pct") is not None
            ]
            avg_adherence = (
                round(sum(on_time_values) / len(on_time_values), 1)
                if on_time_values
                else None
            )
            total_km = round(
                sum(t.get("distance_km") or 0 for t in dt), 1
            )

            result.append(
                {
                    "driver_id": d["id"],
                    "name": d.get("full_name_ar") or d.get("full_name"),
                    "is_active": d.get("is_active", False),
                    "trips_completed": trip_count,
                    "avg_adherence_pct": avg_adherence,
                    "total_km": total_km,
                }
            )

        result.sort(key=lambda x: x["trips_completed"], reverse=True)
        return result

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/admin/analytics/gps-heatmap")
async def get_gps_heatmap(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher")),
):
    """
    Get GPS position data for heatmap visualization.

    Returns recent vehicle positions (last 24h) as GeoJSON FeatureCollection
    suitable for MapLibre heatmap layer.
    """
    try:
        from datetime import timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        # Use ST_AsGeoJSON to get coordinates
        positions = await _supabase_get(
            f"vehicle_positions?recorded_at=gte.{cutoff}"
            "&select=location,speed_kmh&order=recorded_at.desc&limit=2000"
        )

        features = []
        for p in positions:
            loc = p.get("location")
            if not loc:
                continue
            # location is stored as WKT or GeoJSON depending on Supabase config
            # Try to parse coordinates
            try:
                if isinstance(loc, dict):
                    coords = loc.get("coordinates", [])
                    if len(coords) >= 2:
                        features.append(
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [coords[0], coords[1]],
                                },
                                "properties": {"weight": 1},
                            }
                        )
                elif isinstance(loc, str) and loc.startswith("POINT"):
                    # WKT format: POINT(lon lat)
                    inner = loc.replace("POINT(", "").replace(")", "").strip()
                    parts = inner.split()
                    if len(parts) == 2:
                        lon, lat = float(parts[0]), float(parts[1])
                        features.append(
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [lon, lat],
                                },
                                "properties": {"weight": 1},
                            }
                        )
            except (ValueError, TypeError, AttributeError):
                continue

        # Also include current positions from latest table
        latest = await _supabase_get(
            "vehicle_positions_latest?select=location,speed_kmh"
        )
        for p in latest:
            loc = p.get("location")
            if not loc:
                continue
            try:
                if isinstance(loc, dict):
                    coords = loc.get("coordinates", [])
                    if len(coords) >= 2:
                        features.append(
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [coords[0], coords[1]],
                                },
                                "properties": {"weight": 3},  # Higher weight for current
                            }
                        )
                elif isinstance(loc, str) and loc.startswith("POINT"):
                    inner = loc.replace("POINT(", "").replace(")", "").strip()
                    parts = inner.split()
                    if len(parts) == 2:
                        lon, lat = float(parts[0]), float(parts[1])
                        features.append(
                            {
                                "type": "Feature",
                                "geometry": {
                                    "type": "Point",
                                    "coordinates": [lon, lat],
                                },
                                "properties": {"weight": 3},
                            }
                        )
            except (ValueError, TypeError, AttributeError):
                continue

        return {
            "type": "FeatureCollection",
            "features": features,
            "count": len(features),
        }

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
    computed = hmac.new(
        TRACCAR_WEBHOOK_SECRET.encode(), request_body.encode(), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(computed, signature)


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
    # Verify signature — fail-closed: if secret is not set, endpoint is disabled
    if not TRACCAR_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint not configured",
        )
    if not x_traccar_signature or not verify_traccar_signature(
        position.json(), x_traccar_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing signature",
        )

    try:
        # Find vehicle by Traccar device ID
        devices = await _supabase_get(
            f"vehicles?gps_device_id=eq.{position.deviceId}&select=id,vehicle_id"
        )

        if not devices:
            # Device not found - log and ignore gracefully
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle = devices[0]

        # Upsert position via RPC
        await _supabase_rpc(
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
        )

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
    # Verify signature — fail-closed: if secret is not set, endpoint is disabled
    if not TRACCAR_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint not configured",
        )
    if not x_traccar_signature or not verify_traccar_signature(
        event.json(), x_traccar_signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing signature",
        )

    try:
        # Find vehicle by Traccar device ID
        devices = await _supabase_get(
            f"vehicles?gps_device_id=eq.{event.deviceId}&select=id"
        )

        if not devices:
            return {"status": "ignored", "reason": "device_not_found"}

        vehicle_id = devices[0]["id"]

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

            await _supabase_post("alerts", alert_data)

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
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": exc.detail,
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    """Handle unexpected exceptions and return JSON."""
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.get("/")
async def root():
    """Root endpoint - API documentation redirect."""
    return {"message": "DamascusTransit API", "docs": "/docs", "health": "/api/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
