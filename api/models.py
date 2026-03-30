"""
Pydantic models for request/response validation.
All API data contracts are defined here for consistency and reuse.
"""

from datetime import datetime
from typing import Optional, List, Literal
from pydantic import BaseModel, EmailStr, Field, validator
import re


# ============================================================================
# Auth Models
# ============================================================================


class LoginRequest(BaseModel):
    """Login request with credentials."""

    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class TokenResponse(BaseModel):
    """JWT token response."""

    access_token: str
    token_type: str = "bearer"
    user_id: str
    role: str
    must_change_password: bool = False


class PasswordChange(BaseModel):
    """Password change request."""

    current_password: str = Field(..., min_length=8, max_length=128)
    new_password: str = Field(..., min_length=10, max_length=128)

    @validator("new_password")
    def validate_password_strength(cls, v):
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", v):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", v):
            raise ValueError("Password must contain at least one digit")
        return v


# ============================================================================
# Health Models
# ============================================================================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    timestamp: str
    database: bool
    version: str = "1.1.0"


# ============================================================================
# User Models
# ============================================================================


class UserCreate(BaseModel):
    """Create user request (admin only)."""

    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)
    full_name: str = Field(..., min_length=2, max_length=100)
    full_name_ar: Optional[str] = Field(None, max_length=100)
    role: Literal["admin", "dispatcher", "driver", "viewer"] = "viewer"
    phone: Optional[str] = Field(None, max_length=20)

    @validator("phone")
    def validate_phone(cls, v):
        if v and not re.match(r"^\+?[0-9\-\s]{7,20}$", v):
            raise ValueError("Invalid phone number format")
        return v

    @validator("full_name")
    def validate_name(cls, v):
        if not re.match(r"^[\w\s\u0600-\u06FF\-\.]+$", v):
            raise ValueError("Name contains invalid characters")
        return v.strip()


class UserUpdate(BaseModel):
    """Update user request."""

    full_name: Optional[str] = Field(None, min_length=2, max_length=100)
    full_name_ar: Optional[str] = Field(None, max_length=100)
    phone: Optional[str] = Field(None, max_length=20)
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


# ============================================================================
# Route & Stop Models
# ============================================================================


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
# Vehicle Models
# ============================================================================


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


class VehicleCreate(BaseModel):
    """Create vehicle request."""

    vehicle_id: str = Field(..., min_length=1, max_length=50)
    name: str = Field(..., min_length=2, max_length=100)
    name_ar: str = Field(..., min_length=2, max_length=100)
    vehicle_type: Literal["bus", "microbus", "taxi"]
    capacity: int = Field(..., ge=1, le=200)
    gps_device_id: Optional[str] = None
    is_real_gps: bool = True


class VehicleUpdate(BaseModel):
    """Update vehicle request."""

    name: Optional[str] = Field(None, min_length=2, max_length=100)
    name_ar: Optional[str] = Field(None, min_length=2, max_length=100)
    capacity: Optional[int] = Field(None, ge=1, le=200)
    status: Optional[Literal["active", "idle", "maintenance", "decommissioned"]] = None


class VehicleAssign(BaseModel):
    """Assign vehicle to route and driver."""

    route_id: str
    driver_id: str


# ============================================================================
# Position & Trip Models
# ============================================================================


class PositionUpdate(BaseModel):
    """Driver position update."""

    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    speed_kmh: Optional[float] = Field(None, ge=0, le=300)
    heading: Optional[int] = Field(None, ge=0, le=360)


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


class TripStart(BaseModel):
    """Start trip request."""

    route_id: str
    scheduled_departure: Optional[datetime] = None


class TripEnd(BaseModel):
    """End trip request."""

    passenger_count: Optional[int] = Field(None, ge=0, le=500)


class PassengerCountUpdate(BaseModel):
    """Update passenger count in trip."""

    passenger_count: int = Field(..., ge=0, le=500)


# ============================================================================
# Alert & Schedule Models
# ============================================================================


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


# ============================================================================
# Analytics Models
# ============================================================================


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


# ============================================================================
# Geofence Models
# ============================================================================


class GeofenceCreate(BaseModel):
    """Create geofence request."""

    name: str = Field(..., min_length=1, max_length=100)
    name_ar: Optional[str] = Field(None, max_length=100)
    geojson_polygon: dict  # GeoJSON Polygon geometry {"type":"Polygon","coordinates":[...]}
    geofence_type: Literal["zone", "depot", "terminal"] = "zone"
    speed_limit_kmh: Optional[int] = Field(None, ge=0, le=300)


class GeofenceUpdate(BaseModel):
    """Update geofence request."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    name_ar: Optional[str] = Field(None, max_length=100)
    geofence_type: Optional[Literal["zone", "depot", "terminal"]] = None
    speed_limit_kmh: Optional[int] = Field(None, ge=0, le=300)
    is_active: Optional[bool] = None


class GeofenceResponse(BaseModel):
    """Geofence response with GeoJSON geometry."""

    id: str
    name: str
    name_ar: Optional[str] = None
    geometry: dict  # GeoJSON Polygon
    geofence_type: str
    speed_limit_kmh: Optional[int] = None
    is_active: bool
    created_at: str


# ============================================================================
# Traccar Models
# ============================================================================


class TraccarPosition(BaseModel):
    """Traccar position webhook payload."""

    deviceId: int
    latitude: float = Field(..., ge=-90, le=90)
    longitude: float = Field(..., ge=-180, le=180)
    altitude: Optional[float] = None
    speed: Optional[float] = Field(None, ge=0)
    heading: Optional[float] = Field(None, ge=0, le=360)
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
