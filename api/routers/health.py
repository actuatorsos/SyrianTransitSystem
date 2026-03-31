import asyncio
from datetime import datetime

from fastapi import APIRouter

from api.core.cache import _redis_health_check
from api.core.database import _active_vehicle_count, _health_check, _last_position_update
from api.models.schemas import HealthResponse

router = APIRouter()


@router.get("/api/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
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
