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
import uuid
import logging
import asyncio
import hashlib
import hmac
import urllib.parse
import bcrypt
import jwt
from datetime import datetime, timedelta
from typing import Optional, List, Literal

import httpx
from fastapi import FastAPI, Depends, HTTPException, status, Query, Header, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials as HTTPAuthCredentials
from fastapi.responses import JSONResponse, StreamingResponse, Response
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()

# ============================================================================
# Structured Logging (JSON format for Vercel / cloud log aggregators)
# ============================================================================

class _JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON for structured log ingestion."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        # Merge any extra fields attached to the record
        for key, val in record.__dict__.items():
            if key not in {
                "name", "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "processName", "process", "message",
            }:
                payload[key] = val
        return json.dumps(payload, default=str, ensure_ascii=False)


def _setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Quieten noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


_setup_logging()
logger = logging.getLogger("transit.api")

# ============================================================================
# Sentry Error Tracking (optional — graceful degradation when DSN not set)
# ============================================================================

_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[FastApiIntegration(), HttpxIntegration()],
        traces_sample_rate=0.1,   # 10 % of requests for performance tracing
        profiles_sample_rate=0.0,
        environment=os.getenv("VERCEL_ENV", "development"),
        send_default_pii=False,
    )
    logger.info("Sentry error tracking initialised")
else:
    logger.info("SENTRY_DSN not set — error tracking disabled")

# ============================================================================
# Redis Cache (Upstash — serverless-compatible, graceful degradation)
# ============================================================================

# Cache TTLs (seconds)
CACHE_TTL_VEHICLES = 5       # vehicle positions — refreshed every 2s by drivers
CACHE_TTL_ROUTES_STOPS = 300  # routes & stops — static reference data
CACHE_TTL_STATS = 30          # fleet stats — lightweight aggregate

# Cache key prefixes — append :{operator_id} to namespace per tenant
CACHE_KEY_VEHICLES_LIST = "transit:vehicles:list"
CACHE_KEY_VEHICLES_POSITIONS = "transit:vehicles:positions"
CACHE_KEY_ROUTES_LIST = "transit:routes:list"
CACHE_KEY_STATS = "transit:stats"
CACHE_KEY_STOPS_LIST = "transit:stops:list"


def _tenant_cache_key(base: str, operator_id: str) -> str:
    """Namespace a cache key by operator so tenants never share cached data."""
    return f"{base}:{operator_id}"


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
# Rate Limiter (Redis-backed — survives Vercel cold starts)
# ============================================================================

RATE_LIMIT_LOGIN = (10, 60)        # 10 attempts per 60s per IP
RATE_LIMIT_DRIVER_POS = (12, 60)   # 12 updates per 60s per driver (~1 per 5s)
RATE_LIMIT_GLOBAL = (200, 60)      # 200 req/60s per IP — general flood protection
RATE_LIMIT_PUSH_SUB = (5, 60)      # 5 subscribe requests/60s per IP


async def _rate_limit_check(identifier: str, max_requests: int, window_seconds: int) -> bool:
    """Fixed-window rate limiter backed by Upstash Redis. Returns True if allowed."""
    client = _get_redis_client()
    if client is None:
        return True  # graceful degradation when Redis is unavailable
    try:
        window = int(time.time()) // window_seconds
        key = f"rl:{identifier}:{window}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds + 1)
        return count <= max_requests
    except Exception:
        return True


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, honoring Vercel's X-Forwarded-For proxy header."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        # X-Forwarded-For may be a comma-separated list; first entry is the originating client
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"


# ============================================================================
# FastAPI App Initialization
# ============================================================================

_OPENAPI_TAGS = [
    {"name": "health",    "description": "Service health and status checks. No authentication required."},
    {"name": "auth",      "description": "User authentication. Returns a JWT bearer token."},
    {"name": "routes",    "description": "Transit route data. Public read access; no authentication required."},
    {"name": "stops",     "description": "Bus stop locations and nearest-stop lookup. Public read access."},
    {"name": "vehicles",  "description": "Real-time vehicle positions and fleet list. Public read access."},
    {"name": "stream",    "description": "Server-Sent Events (SSE) stream for live vehicle updates. Public."},
    {"name": "websocket", "description": "WebSocket real-time vehicle tracking with route subscriptions."},
    {"name": "stats",     "description": "Aggregate fleet statistics. Public read access."},
    {"name": "schedules", "description": "Route schedules and timetables. Public read access."},
    {"name": "alerts",    "description": "Passenger-facing service alerts. Public read access."},
    {"name": "driver",    "description": "Driver-only endpoints. Requires `driver` role JWT."},
    {"name": "admin",     "description": "Admin and dispatcher endpoints. Requires `admin` or `dispatcher` role JWT."},
    {"name": "traccar",   "description": "Traccar GPS device webhooks. Secured by HMAC signature header."},
    {"name": "gtfs",      "description": "GTFS static and realtime feeds for Google Maps / transit apps."},
    {"name": "operators", "description": "Fleet operator (tenant) management. super_admin role required for most operations."},
]

app = FastAPI(
    title="DamascusTransit API",
    description=(
        "Real-time transit tracking and fleet management — multi-tenant SaaS edition.\n\n"
        "## Authentication\n\n"
        "Most read endpoints are public but require an `?operator=<slug>` query parameter to scope data to a tenant.\n"
        "Authenticated users are automatically scoped to their operator.\n\n"
        "1. **POST /api/auth/login** — exchange email/password for a JWT token\n"
        "2. Include the token as `Authorization: Bearer <token>` on protected endpoints\n\n"
        "Roles: `super_admin` (platform-wide) · `admin` (tenant admin) · `dispatcher` (fleet ops) · `driver` (own vehicle) · `viewer` (read-only)\n\n"
        "Tokens expire after 24 hours."
    ),
    version="1.0.0",
    openapi_tags=_OPENAPI_TAGS,
)

# CORS: restrict to configured allowed origins; never allow wildcard in production
_cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
if not _allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS env var must be set to a comma-separated list of allowed origins"
    )
# Strip localhost/127.0.0.1 origins in production to prevent dev origins leaking
_is_production = os.getenv("VERCEL_ENV", "").lower() == "production"
if _is_production:
    _allowed_origins = [
        o for o in _allowed_origins
        if "localhost" not in o and "127.0.0.1" not in o
    ]
    if not _allowed_origins:
        raise RuntimeError(
            "All ALLOWED_ORIGINS are localhost — no valid origins remain for production"
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)


# Paths exempt from global IP rate limiting (lightweight infra/docs endpoints)
_GLOBAL_RATE_LIMIT_SKIP = frozenset({"/api/health", "/", "/docs", "/openapi.json", "/redoc"})


@app.middleware("http")
async def _global_rate_limit_middleware(request: Request, call_next):
    """Global IP-based rate limit (200 req/60s). Blocks flood attacks on all endpoints."""
    if request.url.path not in _GLOBAL_RATE_LIMIT_SKIP:
        client_ip = _get_client_ip(request)
        max_req, window = RATE_LIMIT_GLOBAL
        if not await _rate_limit_check(f"global:{client_ip}", max_req, window):
            logger.warning(
                "global_rate_limit_exceeded",
                extra={"client_ip": client_ip, "path": request.url.path},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                headers={"Retry-After": str(window)},
            )
    return await call_next(request)


@app.middleware("http")
async def _request_logging_middleware(request: Request, call_next):
    """Attach a request ID to every request and emit a structured access log."""
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    response.headers["X-Request-Id"] = request_id
    return response


# ============================================================================
# JWT Authentication (using PyJWT)
# ============================================================================

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# HTTP Bearer security scheme
security = HTTPBearer()

UserRole = Literal["admin", "dispatcher", "driver", "viewer", "super_admin"]


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
    operator_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_route_id: Optional[str] = None


class CurrentUser(BaseModel):
    """Current authenticated user context."""

    user_id: str
    email: str
    role: UserRole
    operator_id: Optional[str] = None
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
    operator_id: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    vehicle_route_id: Optional[str] = None,
) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User UUID
        email: User email address
        role: User role (admin, dispatcher, driver, viewer, super_admin)
        expires_delta: Custom expiration time (default: 24 hours)
        operator_id: Tenant operator UUID (all non-super_admin users)
        vehicle_id: Assigned vehicle UUID (drivers only, cached to avoid DB lookup)
        vehicle_route_id: Assigned route UUID (drivers only, cached to avoid DB lookup)

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    expire = datetime.utcnow() + expires_delta
    to_encode: dict = {"user_id": user_id, "email": email, "role": role, "exp": expire}

    if operator_id is not None:
        to_encode["operator_id"] = operator_id
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
            operator_id=payload.get("operator_id"),
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
        operator_id=token_payload.operator_id,
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
        operator_id=token_payload.operator_id,
        vehicle_id=token_payload.vehicle_id,
        vehicle_route_id=token_payload.vehicle_route_id,
    )


# ============================================================================
# Multi-tenancy helpers
# ============================================================================

async def _resolve_operator_id(operator_slug: Optional[str]) -> str:
    """
    Resolve an operator UUID from its slug.

    Used by public (unauthenticated) endpoints that accept an `operator` query param
    to identify which tenant's data to serve.

    Args:
        operator_slug: URL-safe operator identifier (e.g. "damascus")

    Returns:
        Operator UUID string

    Raises:
        HTTPException 400 if slug is missing, 404 if not found / inactive
    """
    if not operator_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="operator query parameter is required",
        )
    operators = await _supabase_get(
        f"operators?slug=eq.{urllib.parse.quote(operator_slug, safe='')}&is_active=eq.true&select=id"
    )
    if not operators:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Operator '{operator_slug}' not found",
        )
    return operators[0]["id"]


def _op_filter(operator_id: str) -> str:
    """Return a Supabase query string fragment that filters by operator_id."""
    return f"operator_id=eq.{operator_id}"


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


async def _redis_health_check() -> bool:
    """Check Redis connectivity (returns True when Redis is not configured)."""
    client = _get_redis_client()
    if client is None:
        return True  # graceful — no Redis configured
    try:
        await client.ping()
        return True
    except Exception:
        return False


async def _last_position_update() -> Optional[str]:
    """Return the most recent recorded_at timestamp from vehicle_positions_latest."""
    try:
        rows = await _supabase_get(
            "vehicle_positions_latest?select=recorded_at&order=recorded_at.desc&limit=1"
        )
        if rows:
            return rows[0].get("recorded_at")
        return None
    except Exception:
        return None


async def _active_vehicle_count() -> Optional[int]:
    """Return the number of vehicles with status = 'active'."""
    try:
        rows = await _supabase_get("vehicles?is_active=eq.true&status=eq.active&select=id")
        return len(rows) if rows is not None else None
    except Exception:
        return None


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
    redis: bool
    last_position_update: Optional[str] = None
    active_vehicles: Optional[int] = None


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


@app.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """
    Health check endpoint.

    Returns:
        Health status including database connectivity, Redis status,
        last position update timestamp, and active vehicle count.
    """
    db_healthy, redis_healthy, last_pos, active_count = await asyncio.gather(
        _health_check(),
        _redis_health_check(),
        _last_position_update(),
        _active_vehicle_count(),
    )

    overall = "healthy" if (db_healthy and redis_healthy) else "degraded"

    return HealthResponse(
        status=overall,
        timestamp=datetime.utcnow().isoformat(),
        database=db_healthy,
        redis=redis_healthy,
        last_position_update=last_pos,
        active_vehicles=active_count,
    )


@app.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(request: LoginRequest, raw_request: Request):
    """
    Authenticate user and return JWT token.

    Args:
        request: Email and password credentials

    Returns:
        JWT access token and user info

    Raises:
        HTTPException: Invalid credentials or rate limited
    """
    # Rate limit login attempts by IP
    client_ip = raw_request.client.host if raw_request.client else "unknown"
    max_req, window = RATE_LIMIT_LOGIN
    if not await _rate_limit_check(f"login:{client_ip}", max_req, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
        )
    try:
        users = await _supabase_get(
            f"users?email=eq.{urllib.parse.quote(request.email, safe='')}&select=id,email,password_hash,role,operator_id"
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

        operator_id: Optional[str] = user.get("operator_id")

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

        # Generate token (operator_id baked in — avoids a DB lookup on every request)
        token = create_access_token(
            user_id=user["id"],
            email=user["email"],
            role=user["role"],
            operator_id=operator_id,
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


@app.get("/api/routes", response_model=List[RouteResponse], tags=["routes"])
async def list_routes(
    operator: Optional[str] = Query(None, description="Operator slug (e.g. 'damascus')"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    List all active routes with stop counts.

    Pass `?operator=<slug>` when calling without authentication.
    Authenticated users are automatically scoped to their operator.

    Returns:
        List of active routes
    """
    try:
        if current_user and current_user.role == "super_admin":
            # super_admin can request any operator or get all
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = _tenant_cache_key(CACHE_KEY_ROUTES_LIST, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        query = "routes?is_active=eq.true&select=*"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        routes = await _supabase_get(query)

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
            cache_key,
            [r.model_dump() for r in enriched_routes],
            CACHE_TTL_ROUTES_STOPS,
        )
        return enriched_routes

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/routes/{route_id}", response_model=RouteResponse, tags=["routes"])
async def get_route(
    route_id: str,
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
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
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = f"transit:routes:{route_id}:{op_id or 'all'}"
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        query = f"routes?id=eq.{route_id}&select=*"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        routes = await _supabase_get(query)

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


@app.get("/api/stops", response_model=List[StopResponse], tags=["stops"])
async def list_stops(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    List all active stops.

    Returns:
        List of active stops
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = _tenant_cache_key(CACHE_KEY_STOPS_LIST, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        query = "stops?is_active=eq.true&select=*"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        stops = await _supabase_get(query)

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
            cache_key,
            [r.model_dump() for r in result],
            CACHE_TTL_ROUTES_STOPS,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/stops/nearest", response_model=List[NearestStop], tags=["stops"])
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


@app.get("/api/vehicles", response_model=List[VehicleResponse], tags=["vehicles"])
async def list_vehicles(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    List all active vehicles with latest positions.

    Returns:
        List of active vehicles with real-time position data
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = _tenant_cache_key(CACHE_KEY_VEHICLES_LIST, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        query = "vehicle_positions_latest?select=*,vehicles(id,vehicle_id,name,name_ar,vehicle_type,capacity,status,assigned_route_id)"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        positions = await _supabase_get(query)

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
            cache_key,
            [r.model_dump() for r in result],
            CACHE_TTL_VEHICLES,
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/vehicles/positions", response_model=List[dict], tags=["vehicles"])
async def get_vehicle_positions(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    Get latest vehicle positions only (lightweight endpoint).

    Returns:
        Vehicle ID, location, and basic tracking data
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = _tenant_cache_key(CACHE_KEY_VEHICLES_POSITIONS, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        query = "vehicle_positions_latest?select=vehicle_id,latitude,longitude,speed_kmh,occupancy_pct,recorded_at"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        result = await _supabase_get(query)

        result = result or []
        await _cache_set(cache_key, result, CACHE_TTL_VEHICLES)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/stream", tags=["stream"])
async def stream_positions(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    Server-sent events (SSE) stream of vehicle position updates.
    Polls vehicle_positions_latest every 2 seconds for up to 25 seconds (Vercel limit).

    Returns:
        Streaming response with position updates
    """
    # Resolve operator before streaming (no async inside generator)
    if current_user and current_user.role == "super_admin":
        op_id = await _resolve_operator_id(operator) if operator else None
    elif current_user and current_user.operator_id:
        op_id = current_user.operator_id
    else:
        op_id = await _resolve_operator_id(operator)

    async def generate():
        start_time = time.time()
        max_duration = 25  # Vercel hobby timeout

        while time.time() - start_time < max_duration:
            try:
                query = "vehicle_positions_latest?select=*,vehicles(name,name_ar)"
                if op_id:
                    query += f"&{_op_filter(op_id)}"
                positions = await _supabase_get(query)

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

                await asyncio.sleep(2)

            except Exception as e:
                yield f"data: {{'error': '{str(e)}'}}\n\n"
                await asyncio.sleep(2)

    return StreamingResponse(generate(), media_type="text/event-stream")


# ============================================================================
# WebSocket — Real-time Vehicle Tracking with ConnectionManager
# ============================================================================


class ConnectionManager:
    """
    Manages active WebSocket connections and per-connection route subscriptions.

    Each connection may optionally subscribe to a single route_id filter.
    Connections with no filter receive all vehicle positions.
    """

    def __init__(self):
        self._connections: dict[WebSocket, Optional[str]] = {}

    def connect(self, ws: WebSocket, route_id: Optional[str] = None) -> None:
        self._connections[ws] = route_id

    def disconnect(self, ws: WebSocket) -> None:
        self._connections.pop(ws, None)

    def subscribe(self, ws: WebSocket, route_id: Optional[str]) -> None:
        if ws in self._connections:
            self._connections[ws] = route_id

    @property
    def count(self) -> int:
        return len(self._connections)

    async def broadcast_positions(self, positions: list) -> None:
        dead: set = set()
        for ws, route_filter in list(self._connections.items()):
            payload = (
                [p for p in positions if p.get("route_id") == route_filter]
                if route_filter is not None
                else positions
            )
            try:
                await ws.send_text(json.dumps({"type": "positions", "data": payload}))
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)

    async def broadcast_alert(self, alert: dict) -> None:
        dead: set = set()
        message = json.dumps({"type": "geofence_alert", "data": alert})
        for ws in list(self._connections):
            try:
                await ws.send_text(message)
            except Exception:
                dead.add(ws)
        for ws in dead:
            self.disconnect(ws)


ws_manager = ConnectionManager()


async def _fetch_ws_positions() -> list:
    """Fetch latest vehicle positions for WebSocket broadcast."""
    try:
        query = "vehicle_positions_latest?select=vehicle_id,latitude,longitude,speed_kmh,occupancy_pct,recorded_at,vehicles(name,name_ar,assigned_route_id)"
        positions = await _supabase_get(query)
        result = []
        for pos in positions or []:
            vehicle = pos.get("vehicles") or {}
            result.append({
                "vehicle_id": pos.get("vehicle_id"),
                "route_id": vehicle.get("assigned_route_id"),
                "vehicle_name": vehicle.get("name", ""),
                "vehicle_name_ar": vehicle.get("name_ar", ""),
                "latitude": pos.get("latitude"),
                "longitude": pos.get("longitude"),
                "speed_kmh": pos.get("speed_kmh"),
                "occupancy_pct": pos.get("occupancy_pct"),
                "timestamp": pos.get("recorded_at", datetime.utcnow().isoformat()),
            })
        return result
    except Exception:
        return []


async def _ws_broadcast_loop() -> None:
    """Background loop that pushes position updates to WebSocket clients every second."""
    while True:
        if ws_manager.count > 0:
            positions = await _fetch_ws_positions()
            await ws_manager.broadcast_positions(positions)
        await asyncio.sleep(1)


@app.on_event("startup")
async def _start_ws_broadcast():
    asyncio.create_task(_ws_broadcast_loop())


@app.get("/api/ws/stats", tags=["websocket"])
async def websocket_stats():
    """Returns current WebSocket connection statistics."""
    return JSONResponse({"active_connections": ws_manager.count})


@app.websocket("/api/ws/track")
async def websocket_vehicle_tracking(websocket: WebSocket):
    """
    WebSocket endpoint for real-time vehicle position streaming.

    Connect via: ws://<host>/api/ws/track

    Server → client messages:
      { "type": "positions", "data": [...] }
      { "type": "geofence_alert", "data": {...} }
      { "type": "pong" }
      { "type": "subscribed", "route_id": "<uuid>" }
      { "type": "unsubscribed" }

    Client → server messages:
      { "type": "ping" }
      { "type": "subscribe", "route_id": "<route-uuid>" }
      { "type": "unsubscribe" }
    """
    await websocket.accept()
    ws_manager.connect(websocket)

    # Push current snapshot immediately
    try:
        positions = await _fetch_ws_positions()
        await websocket.send_text(json.dumps({"type": "positions", "data": positions}))
    except Exception:
        pass

    try:
        while True:
            try:
                raw = await asyncio.wait_for(websocket.receive_text(), timeout=30)
                msg = json.loads(raw)
                msg_type = msg.get("type")

                if msg_type == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                elif msg_type == "subscribe":
                    route_id = msg.get("route_id") or None
                    ws_manager.subscribe(websocket, route_id)
                    await websocket.send_text(json.dumps({"type": "subscribed", "route_id": route_id}))
                elif msg_type == "unsubscribe":
                    ws_manager.subscribe(websocket, None)
                    await websocket.send_text(json.dumps({"type": "unsubscribed"}))

            except asyncio.TimeoutError:
                await websocket.send_text(json.dumps({"type": "ping"}))
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(websocket)


@app.get("/api/stats", response_model=dict, tags=["stats"])
async def get_fleet_stats(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    Get fleet statistics and real-time metrics.

    Returns:
        Fleet overview stats
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        cache_key = _tenant_cache_key(CACHE_KEY_STATS, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        op_suffix = f"&{_op_filter(op_id)}" if op_id else ""

        # Vehicle counts
        vehicles = await _supabase_get(f"vehicles?is_active=eq.true&select=id,status{op_suffix}")

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
        routes = await _supabase_get(f"routes?is_active=eq.true&select=id{op_suffix}")

        # Stops count
        stops = await _supabase_get(f"stops?is_active=eq.true&select=id{op_suffix}")

        # Driver counts
        drivers = await _supabase_get(f"users?role=eq.driver&select=id,is_active{op_suffix}")

        active_drivers = (
            len([d for d in drivers if d.get("is_active")]) if drivers else 0
        )

        # Average occupancy
        positions = await _supabase_get(f"vehicle_positions_latest?select=occupancy_pct{op_suffix}")

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

        await _cache_set(cache_key, result, CACHE_TTL_STATS)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/schedules/{route_id}", response_model=List[ScheduleResponse], tags=["schedules"])
async def get_route_schedule(
    route_id: str,
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    Get schedule for a route by day of week.

    Args:
        route_id: Route UUID

    Returns:
        Schedule entries for each day
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        query = f"schedules?route_id=eq.{route_id}&select=*"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        schedules = await _supabase_get(query)

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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/alerts/active", response_model=List[AlertResponse], tags=["alerts"])
async def get_active_alerts(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """
    Get all unresolved alerts.

    Returns:
        List of active alerts
    """
    try:
        if current_user and current_user.role == "super_admin":
            op_id = await _resolve_operator_id(operator) if operator else None
        elif current_user and current_user.operator_id:
            op_id = current_user.operator_id
        else:
            op_id = await _resolve_operator_id(operator)

        query = "alerts?is_resolved=eq.false&select=*&order=created_at.desc"
        if op_id:
            query += f"&{_op_filter(op_id)}"
        alerts = await _supabase_get(query)

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

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


# ============================================================================
# Driver Endpoints (Auth: driver role)
# ============================================================================


@app.post("/api/driver/position", tags=["driver"])
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
    # Rate limit position updates per driver
    max_req, window = RATE_LIMIT_DRIVER_POS
    if not await _rate_limit_check(f"drvpos:{current_user.user_id}", max_req, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Position update rate limit exceeded.",
        )
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

        # Call RPC to upsert position.
        # If the JWT vehicle_id is stale (vehicle deleted after login), the
        # upsert will fail with a PostgreSQL FK violation (error code 23503).
        # Detect that and return 401 so the driver re-authenticates and gets a
        # fresh token with the correct vehicle assignment.
        try:
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
        except HTTPException as rpc_err:
            detail = str(rpc_err.detail)
            if current_user.vehicle_id and (
                "23503" in detail or "foreign key" in detail.lower()
            ):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Vehicle assignment has changed. Please log in again to refresh your session.",
                )
            raise

        # Invalidate tenant-scoped vehicle position caches
        if current_user.operator_id:
            await _cache_delete(
                _tenant_cache_key(CACHE_KEY_VEHICLES_LIST, current_user.operator_id),
                _tenant_cache_key(CACHE_KEY_VEHICLES_POSITIONS, current_user.operator_id),
            )
        else:
            await _cache_delete(CACHE_KEY_VEHICLES_LIST, CACHE_KEY_VEHICLES_POSITIONS)

        return {"status": "success", "timestamp": datetime.utcnow().isoformat()}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.post("/api/driver/trip/start", tags=["driver"])
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
            "operator_id": current_user.operator_id,
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


@app.post("/api/driver/trip/end", tags=["driver"])
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


@app.post("/api/driver/trip/passenger-count", tags=["driver"])
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


@app.get("/api/admin/users", response_model=List[UserResponse], tags=["admin"])
async def list_users(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    List all users scoped to the current operator.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        List of users
    """
    try:
        query = "users?select=*"
        if current_user.role != "super_admin" and current_user.operator_id:
            query += f"&{_op_filter(current_user.operator_id)}"
        users = await _supabase_get(query)

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


@app.post("/api/admin/users", response_model=UserResponse, tags=["admin"])
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
            "operator_id": current_user.operator_id,
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


@app.put("/api/admin/users/{user_id}", response_model=UserResponse, tags=["admin"])
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


@app.get("/api/admin/vehicles", response_model=List[VehicleResponse], tags=["admin"])
async def list_all_vehicles(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    List all vehicles including inactive ones, scoped to current operator.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        All vehicles
    """
    try:
        query = "vehicle_positions_latest?select=*,vehicles(*)"
        if current_user.role != "super_admin" and current_user.operator_id:
            query += f"&{_op_filter(current_user.operator_id)}"
        positions = await _supabase_get(query)

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


@app.post("/api/admin/vehicles", response_model=VehicleResponse, tags=["admin"])
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
            "operator_id": current_user.operator_id,
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


@app.put("/api/admin/vehicles/{vehicle_id}", response_model=VehicleResponse, tags=["admin"])
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


@app.post("/api/admin/vehicles/{vehicle_id}/assign", tags=["admin"])
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


@app.get("/api/admin/alerts", response_model=List[AlertResponse], tags=["admin"])
async def list_all_alerts(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    Get all alerts (resolved and unresolved), scoped to current operator.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        All alerts
    """
    try:
        query = "alerts?select=*&order=created_at.desc"
        if current_user.role != "super_admin" and current_user.operator_id:
            query += f"&{_op_filter(current_user.operator_id)}"
        alerts = await _supabase_get(query)

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


@app.put("/api/admin/alerts/{alert_id}/resolve", tags=["admin"])
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


@app.get("/api/admin/trips", response_model=List[dict], tags=["admin"])
async def list_trips(
    vehicle_id: Optional[str] = None,
    driver_id: Optional[str] = None,
    status_filter: Optional[str] = None,
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    List trips with optional filtering, scoped to current operator.

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
        if current_user.role != "super_admin" and current_user.operator_id:
            params.append(_op_filter(current_user.operator_id))

        query = "trips?select=*&order=created_at.desc"
        if params:
            query = f"trips?{'&'.join(params)}&select=*&order=created_at.desc"

        result = await _supabase_get(query)

        return result or []

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/admin/analytics/overview", response_model=AnalyticsOverview, tags=["admin"])
async def get_analytics_overview(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    Get fleet analytics overview for dashboard, scoped to current operator.

    Args:
        current_user: Authenticated admin/dispatcher

    Returns:
        Fleet analytics
    """
    try:
        op_suffix = (
            f"&{_op_filter(current_user.operator_id)}"
            if current_user.role != "super_admin" and current_user.operator_id
            else ""
        )

        # Vehicle counts
        vehicles = await _supabase_get(f"vehicles?select=status{op_suffix}")

        active_vehicles = len([v for v in vehicles if v.get("status") == "active"])
        idle_vehicles = len([v for v in vehicles if v.get("status") == "idle"])
        maintenance_vehicles = len(
            [v for v in vehicles if v.get("status") == "maintenance"]
        )

        # Routes
        routes = await _supabase_get(f"routes?is_active=eq.true&select=id{op_suffix}")

        # Stops
        stops = await _supabase_get(f"stops?is_active=eq.true&select=id{op_suffix}")

        # Drivers
        drivers = await _supabase_get(f"users?role=eq.driver&select=is_active{op_suffix}")

        active_drivers = (
            len([d for d in drivers if d.get("is_active")]) if drivers else 0
        )

        # Average occupancy
        positions = await _supabase_get(f"vehicle_positions_latest?select=occupancy_pct{op_suffix}")

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


@app.get("/api/admin/analytics/fleet-utilization", tags=["admin"])
async def get_fleet_utilization(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
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

        op_suffix = (
            f"&{_op_filter(current_user.operator_id)}"
            if current_user.role != "super_admin" and current_user.operator_id
            else ""
        )

        # Get all vehicles for total count
        vehicles = await _supabase_get(f"vehicles?select=id,status{op_suffix}")
        total_vehicles = len(vehicles)

        # Get trips in last 24h to compute per-hour active counts
        trips = await _supabase_get(
            f"trips?actual_start=gte.{cutoff.isoformat()}&select=actual_start,actual_end,vehicle_id{op_suffix}"
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


@app.get("/api/admin/analytics/route-performance", tags=["admin"])
async def get_route_performance(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    Get per-route performance: on-time %, average delay, and trip count
    based on completed trips in the last 7 days.
    """
    try:
        from datetime import timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()

        op_suffix = (
            f"&{_op_filter(current_user.operator_id)}"
            if current_user.role != "super_admin" and current_user.operator_id
            else ""
        )

        routes = await _supabase_get(
            f"routes?is_active=eq.true&select=id,name,name_ar,distance_km{op_suffix}"
        )
        trips = await _supabase_get(
            f"trips?status=eq.completed&actual_start=gte.{cutoff}"
            f"&select=route_id,on_time_pct,scheduled_start,actual_start{op_suffix}"
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


@app.get("/api/admin/analytics/driver-scoreboard", tags=["admin"])
async def get_driver_scoreboard(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    Get driver scoreboard: trips completed and avg route adherence (on_time_pct)
    based on completed trips in the last 30 days.
    """
    try:
        from datetime import timezone
        from collections import defaultdict

        cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        op_suffix = (
            f"&{_op_filter(current_user.operator_id)}"
            if current_user.role != "super_admin" and current_user.operator_id
            else ""
        )

        drivers = await _supabase_get(
            f"users?role=eq.driver&select=id,full_name,full_name_ar,is_active{op_suffix}"
        )
        trips = await _supabase_get(
            f"trips?status=eq.completed&actual_start=gte.{cutoff}"
            f"&select=driver_id,on_time_pct,distance_km{op_suffix}"
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


@app.get("/api/admin/analytics/gps-heatmap", tags=["admin"])
async def get_gps_heatmap(
    current_user: CurrentUser = Depends(require_role("admin", "dispatcher", "super_admin")),
):
    """
    Get GPS position data for heatmap visualization.

    Returns recent vehicle positions (last 24h) as GeoJSON FeatureCollection
    suitable for MapLibre heatmap layer.
    """
    try:
        from datetime import timezone

        cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()

        op_suffix = (
            f"&{_op_filter(current_user.operator_id)}"
            if current_user.role != "super_admin" and current_user.operator_id
            else ""
        )

        # Use ST_AsGeoJSON to get coordinates
        positions = await _supabase_get(
            f"vehicle_positions?recorded_at=gte.{cutoff}"
            f"&select=location,speed_kmh&order=recorded_at.desc&limit=2000{op_suffix}"
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
            f"vehicle_positions_latest?select=location,speed_kmh{op_suffix}"
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
# GPS Position Simulator (Admin-only, for demos & development)
# ============================================================================

import math
import random


def _interpolate_position(
    stops: list[dict], progress: float
) -> tuple[float, float, float]:
    """Interpolate lat/lon/heading along a sequence of stop coordinates.

    Args:
        stops: List of dicts with 'lat' and 'lon' keys, ordered by stop_sequence.
        progress: 0.0 (start) to 1.0 (end of route). Values > 1.0 wrap for
                  round-trip simulation.

    Returns:
        (latitude, longitude, heading_degrees)
    """
    if not stops or len(stops) < 2:
        return (33.5105, 36.3025, 0)  # Damascus fallback

    # Round-trip: 0→1 = outbound, 1→2 = return
    if progress > 1.0:
        progress = 2.0 - progress
        stops = list(reversed(stops))

    n_segments = len(stops) - 1
    seg_progress = progress * n_segments
    seg_idx = min(int(seg_progress), n_segments - 1)
    t = seg_progress - seg_idx

    a, b = stops[seg_idx], stops[seg_idx + 1]
    lat = a["lat"] + (b["lat"] - a["lat"]) * t
    lon = a["lon"] + (b["lon"] - a["lon"]) * t

    # Add small jitter to simulate GPS noise (±~15m)
    lat += random.uniform(-0.00015, 0.00015)
    lon += random.uniform(-0.00015, 0.00015)

    # Heading from a → b
    d_lon = b["lon"] - a["lon"]
    d_lat = b["lat"] - a["lat"]
    heading = math.degrees(math.atan2(d_lon, d_lat)) % 360

    return (round(lat, 6), round(lon, 6), round(heading, 1))


CRON_SECRET = os.getenv("CRON_SECRET", "")


async def _service_get(path: str) -> list:
    """Supabase GET with service key (bypasses RLS)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(
            _supabase_url(path), headers=_supabase_headers(use_service_key=True)
        )
        resp.raise_for_status()
        if not resp.content:
            return []
        data = resp.json()
        return data if isinstance(data, list) else [data] if data else []


async def _service_rpc(func_name: str, params: dict) -> any:
    """Supabase RPC with service key (bypasses RLS)."""
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.post(
            f"{os.getenv('SUPABASE_URL')}/rest/v1/rpc/{func_name}",
            headers=_supabase_headers(use_service_key=True),
            json=params,
        )
        resp.raise_for_status()
        return resp.json() if resp.content else None


async def _run_simulation() -> dict:
    """Core simulation logic — generates positions for all active vehicles."""
    # Use service key to bypass RLS (this is a privileged server-side operation)
    vehicles = await _service_get(
        "vehicles?status=eq.active&assigned_route_id=not.is.null"
        "&select=id,vehicle_id,assigned_route_id,vehicle_type"
    )

    if not vehicles:
        return {"status": "no_vehicles", "updated": 0}

    # Collect unique route IDs
    route_ids = list({v["assigned_route_id"] for v in vehicles})

    # Fetch route stops with coordinates for each route
    route_stops_map: dict[str, list[dict]] = {}
    for rid in route_ids:
        rows = await _service_get(
            f"route_stops?route_id=eq.{rid}"
            f"&select=stop_sequence,stops(stop_id,location)"
            f"&order=stop_sequence.asc"
        )
        stops = []
        for row in rows:
            stop_data = row.get("stops")
            if not stop_data:
                continue
            loc = stop_data.get("location")
            if not loc:
                continue
            lat, lon = None, None
            if isinstance(loc, dict):
                coords = loc.get("coordinates", [])
                if len(coords) >= 2:
                    lon, lat = coords[0], coords[1]
            elif isinstance(loc, str) and "POINT" in loc:
                inner = loc.replace("POINT(", "").replace(")", "").strip()
                parts = inner.split()
                if len(parts) == 2:
                    lon, lat = float(parts[0]), float(parts[1])
            if lat is not None and lon is not None:
                stops.append({"lat": lat, "lon": lon})
        route_stops_map[rid] = stops

    # Simulate positions based on current time
    now = time.time()
    cycle_seconds = 1800  # 30-minute round-trip cycle
    updated = []

    for i, vehicle in enumerate(vehicles):
        rid = vehicle["assigned_route_id"]
        stops = route_stops_map.get(rid, [])
        if len(stops) < 2:
            continue

        # Each vehicle has a phase offset so they're distributed along the route
        phase = (i * 137) % cycle_seconds
        progress = ((now + phase) % cycle_seconds) / (cycle_seconds / 2)
        progress = progress % 2.0  # 0→2 for round trip

        lat, lon, heading = _interpolate_position(stops, progress)

        base_speed = {"bus": 30, "microbus": 25, "taxi": 40}.get(
            vehicle.get("vehicle_type", "bus"), 30
        )
        speed = round(base_speed + random.uniform(-5, 5), 1)
        occupancy = random.randint(15, 85)

        await _service_rpc(
            "upsert_vehicle_position",
            {
                "p_vehicle_id": vehicle["id"],
                "p_lat": lat,
                "p_lon": lon,
                "p_speed": speed,
                "p_heading": heading,
                "p_source": "simulator",
                "p_route_id": rid,
                "p_occupancy": occupancy,
            },
        )

        updated.append(
            {
                "vehicle_id": vehicle["vehicle_id"],
                "lat": lat,
                "lon": lon,
                "speed_kmh": speed,
                "heading": heading,
            }
        )

    return {
        "status": "success",
        "updated": len(updated),
        "vehicles": updated,
        "timestamp": datetime.utcnow().isoformat(),
    }


@app.post("/api/admin/simulate", tags=["admin"])
async def simulate_vehicle_positions(
    current_user: CurrentUser = Depends(require_role("admin", "super_admin")),
):
    """Generate simulated GPS positions (admin JWT auth)."""
    return await _run_simulation()


@app.get("/api/cron/simulate", tags=["cron"])
async def cron_simulate_positions(request: Request):
    """Vercel Cron endpoint — generates simulated GPS positions on schedule.

    Secured by CRON_SECRET env var. Add to vercel.json crons config.
    """
    auth = request.headers.get("authorization", "")
    if not CRON_SECRET or auth != f"Bearer {CRON_SECRET}":
        raise HTTPException(status_code=401, detail="Invalid cron secret")
    try:
        return await _run_simulation()
    except Exception as e:
        logger.error("Simulation failed", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail=f"Simulation error: {str(e)}")


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


@app.post("/api/traccar/position", tags=["traccar"])
async def traccar_position_webhook(
    position: TraccarPosition,
    x_traccar_signature: str = Header(..., description="HMAC-SHA256 signature"),
):
    """
    Webhook for Traccar GPS position updates.
    Secured by mandatory X-Traccar-Signature HMAC header.

    Args:
        position: Position data from Traccar
        x_traccar_signature: HMAC-SHA256 signature (required)

    Returns:
        Success confirmation
    """
    # Verify signature — fail-closed: if secret is not set, endpoint is disabled
    if not TRACCAR_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint not configured",
        )
    if not verify_traccar_signature(position.json(), x_traccar_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
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
        logger.error("Traccar position webhook error", extra={"error": str(e)})
        return {"status": "error", "detail": str(e)}


@app.post("/api/traccar/event", tags=["traccar"])
async def traccar_event_webhook(
    event: TraccarEvent,
    x_traccar_signature: str = Header(..., description="HMAC-SHA256 signature"),
):
    """
    Webhook for Traccar events (engine on/off, speeding, etc).
    Secured by mandatory X-Traccar-Signature HMAC header.

    Args:
        event: Event data from Traccar
        x_traccar_signature: HMAC-SHA256 signature (required)

    Returns:
        Success confirmation
    """
    # Verify signature — fail-closed: if secret is not set, endpoint is disabled
    if not TRACCAR_WEBHOOK_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Webhook endpoint not configured",
        )
    if not verify_traccar_signature(event.json(), x_traccar_signature):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid signature",
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
        logger.error("Traccar event webhook error", extra={"error": str(e)})
        return {"status": "error", "detail": str(e)}


# ============================================================================
# GTFS Static Feed
# ============================================================================

GTFS_DIR = os.path.join(os.path.dirname(__file__), "..", "db", "gtfs")


@app.get("/api/gtfs/static/{filename}", tags=["gtfs"])
async def get_gtfs_static_file(filename: str):
    """
    Serve individual GTFS static feed files.

    Returns the raw CSV content of agency.txt, stops.txt, routes.txt,
    trips.txt, stop_times.txt, calendar.txt, or feed_info.txt.
    """
    allowed = {
        "agency.txt", "stops.txt", "routes.txt", "trips.txt",
        "stop_times.txt", "calendar.txt", "feed_info.txt",
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


# ============================================================================
# GTFS Realtime Feed
# ============================================================================


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


@app.get("/api/gtfs/realtime", tags=["gtfs"])
@app.get("/api/public/gtfs-rt", tags=["gtfs"])
async def get_gtfs_realtime():
    """
    GTFS-Realtime feed (VehiclePositions + TripUpdates).

    Returns a binary protobuf FeedMessage (GTFS-RT 2.0) with:
    - VehiclePosition entities for all vehicles with known positions
      (includes speed in m/s, bearing, occupancy status)
    - TripUpdate entities for all in-progress trips

    Suitable for consumption by Google Maps and other GTFS-RT-compatible
    trip planners. No authentication required.

    Falls back to JSON when gtfs-realtime-bindings is not installed.
    """
    try:
        # Fetch all data sources in parallel-safe manner
        positions = await _supabase_get(
            "vehicle_positions_latest"
            "?select=vehicle_id,latitude,longitude,speed_kmh,heading,"
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
            feed.header.incrementality = (
                gtfs_realtime_pb2.FeedHeader.FULL_DATASET
            )
            feed.header.timestamp = int(time.time())

            # ── VehiclePosition entities ──────────────────────────────────
            for pos in positions:
                lat = pos.get("latitude")
                lon = pos.get("longitude")
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
                    pos.get("occupancy_pct"),
                    gtfs_realtime_pb2.VehiclePosition,
                )
                if occ is not None:
                    vp.occupancy_status = occ

            # ── TripUpdate entities ───────────────────────────────────────
            for trip in (trips_raw or []):
                vehicle = vehicles_by_uuid.get(trip["vehicle_id"])
                route_text_id = route_id_by_uuid.get(
                    trip.get("route_id", ""), ""
                )

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
            # gtfs-realtime-bindings not available — return JSON fallback
            feed_json = {
                "header": {
                    "gtfs_realtime_version": "2.0",
                    "incrementality": "FULL_DATASET",
                    "timestamp": int(time.time()),
                },
                "entity": [],
            }
            for p in positions:
                if p.get("latitude") is None or p.get("longitude") is None:
                    continue
                vehicle = vehicles_by_uuid.get(p.get("vehicle_id"))
                if not vehicle:
                    continue
                route_text_id = route_id_by_uuid.get(
                    vehicle.get("assigned_route_id", ""), ""
                )
                feed_json["entity"].append({
                    "id": f"vp_{p['vehicle_id']}",
                    "vehicle": {
                        "vehicle": {
                            "id": vehicle["vehicle_id"],
                            "label": vehicle.get("name", ""),
                        },
                        "trip": {"route_id": route_text_id},
                        "position": {
                            "latitude": p.get("latitude"),
                            "longitude": p.get("longitude"),
                            "speed": (p.get("speed_kmh") or 0.0) / 3.6,
                        },
                        "timestamp": int(time.time()),
                    },
                })
            return JSONResponse(content=feed_json)

    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


# ============================================================================
# Push Notifications
# ============================================================================

# In-memory push subscription store (keyed by endpoint URL).
# For production, migrate to Redis or Supabase push_subscriptions table.
_push_subscriptions: dict = {}


class PushSubscriptionKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushSubscriptionKeys


class PushSubscribeRequest(BaseModel):
    subscription: PushSubscription
    stopIds: List[str] = []


@app.get("/api/push/vapid-public-key", tags=["push"])
async def get_vapid_public_key():
    """Return the VAPID public key for Web Push subscription setup."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    return {"publicKey": key, "enabled": bool(key)}


@app.post("/api/push/subscribe", tags=["push"])
async def subscribe_push(req: PushSubscribeRequest, raw_request: Request):
    """Store a Web Push subscription and associate it with watched stop IDs."""
    # Rate-limit push subscription to prevent endpoint spam (no auth required)
    client_ip = _get_client_ip(raw_request)
    max_req, window = RATE_LIMIT_PUSH_SUB
    if not await _rate_limit_check(f"pushsub:{client_ip}", max_req, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many subscription requests. Try again later.",
        )
    endpoint = req.subscription.endpoint
    _push_subscriptions[endpoint] = {
        "subscription": req.subscription.model_dump(),
        "stopIds": req.stopIds,
        "createdAt": datetime.utcnow().isoformat(),
    }
    redis = _get_redis_client()
    if redis:
        try:
            await _cache_set(
                f"push_sub:{endpoint}",
                _push_subscriptions[endpoint],
                ttl=60 * 60 * 24 * 30,
            )
        except Exception:
            pass
    return {"status": "subscribed", "endpoint": endpoint}


@app.delete("/api/push/subscribe", tags=["push"])
async def unsubscribe_push(req: dict):
    """Remove a Web Push subscription by endpoint URL."""
    endpoint = req.get("endpoint", "")
    _push_subscriptions.pop(endpoint, None)
    redis = _get_redis_client()
    if redis:
        try:
            await _cache_delete(f"push_sub:{endpoint}")
        except Exception:
            pass
    return {"status": "unsubscribed"}


# ============================================================================
# Operator Management Endpoints (multi-tenancy)
# ============================================================================


class OperatorCreate(BaseModel):
    """Create operator (fleet tenant) request — super_admin only."""

    slug: str = Field(..., min_length=2, max_length=64, pattern=r"^[a-z0-9-]+$")
    name: str
    name_ar: Optional[str] = None
    plan: Literal["free", "pro", "enterprise"] = "free"
    settings: Optional[dict] = None


class OperatorUpdate(BaseModel):
    """Update operator request."""

    name: Optional[str] = None
    name_ar: Optional[str] = None
    plan: Optional[Literal["free", "pro", "enterprise"]] = None
    is_active: Optional[bool] = None
    settings: Optional[dict] = None


class OperatorResponse(BaseModel):
    """Operator response model."""

    id: str
    slug: str
    name: str
    name_ar: Optional[str] = None
    plan: str
    is_active: bool
    settings: Optional[dict] = None
    created_at: Optional[str] = None


@app.get("/api/operators", response_model=List[OperatorResponse], tags=["operators"])
async def list_operators(
    current_user: CurrentUser = Depends(require_role("super_admin")),
):
    """
    List all fleet operators (super_admin only).

    Returns:
        All registered operators
    """
    try:
        operators = await _supabase_get("operators?select=*&order=created_at.asc")
        return [
            OperatorResponse(
                id=o["id"],
                slug=o["slug"],
                name=o["name"],
                name_ar=o.get("name_ar"),
                plan=o["plan"],
                is_active=o["is_active"],
                settings=o.get("settings"),
                created_at=o.get("created_at"),
            )
            for o in operators
        ]
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.get("/api/operators/me", response_model=OperatorResponse, tags=["operators"])
async def get_my_operator(
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Get the current user's operator profile.

    Returns:
        Operator details for the authenticated user's tenant
    """
    try:
        if not current_user.operator_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="No operator associated with this account",
            )
        operators = await _supabase_get(
            f"operators?id=eq.{current_user.operator_id}&select=*"
        )
        if not operators:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found"
            )
        o = operators[0]
        return OperatorResponse(
            id=o["id"],
            slug=o["slug"],
            name=o["name"],
            name_ar=o.get("name_ar"),
            plan=o["plan"],
            is_active=o["is_active"],
            settings=o.get("settings"),
            created_at=o.get("created_at"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.post("/api/operators", response_model=OperatorResponse, tags=["operators"])
async def create_operator(
    data: OperatorCreate,
    current_user: CurrentUser = Depends(require_role("super_admin")),
):
    """
    Register a new fleet operator (super_admin only).

    Returns:
        Created operator
    """
    try:
        existing = await _supabase_get(
            f"operators?slug=eq.{urllib.parse.quote(data.slug, safe='')}&select=id"
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Operator slug '{data.slug}' already exists",
            )

        payload: dict = {
            "slug": data.slug,
            "name": data.name,
            "name_ar": data.name_ar,
            "plan": data.plan,
            "is_active": True,
        }
        if data.settings is not None:
            payload["settings"] = data.settings

        result = await _supabase_post("operators", payload)
        created = result if isinstance(result, dict) else result[0] if result else {}

        return OperatorResponse(
            id=created["id"],
            slug=created["slug"],
            name=created["name"],
            name_ar=created.get("name_ar"),
            plan=created["plan"],
            is_active=created["is_active"],
            settings=created.get("settings"),
            created_at=created.get("created_at"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


@app.put("/api/operators/{operator_id}", response_model=OperatorResponse, tags=["operators"])
async def update_operator(
    operator_id: str,
    data: OperatorUpdate,
    current_user: CurrentUser = Depends(require_role("super_admin")),
):
    """
    Update an operator's details (super_admin only).

    Returns:
        Updated operator
    """
    try:
        update_dict: dict = {}
        if data.name is not None:
            update_dict["name"] = data.name
        if data.name_ar is not None:
            update_dict["name_ar"] = data.name_ar
        if data.plan is not None:
            update_dict["plan"] = data.plan
        if data.is_active is not None:
            update_dict["is_active"] = data.is_active
        if data.settings is not None:
            update_dict["settings"] = data.settings

        if not update_dict:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="No fields to update"
            )

        result = await _supabase_patch(f"operators?id=eq.{operator_id}", update_dict)
        if not result:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Operator not found"
            )

        o = result[0]
        return OperatorResponse(
            id=o["id"],
            slug=o["slug"],
            name=o["name"],
            name_ar=o.get("name_ar"),
            plan=o["plan"],
            is_active=o["is_active"],
            settings=o.get("settings"),
            created_at=o.get("created_at"),
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
