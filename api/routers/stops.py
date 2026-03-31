from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.auth import CurrentUser, optional_auth
from api.core.cache import (
    CACHE_KEY_STOPS_LIST,
    CACHE_TTL_ROUTES_STOPS,
    _cache_get,
    _cache_set,
    _tenant_cache_key,
)
from api.core.database import _supabase_get, _supabase_rpc
from api.core.tenancy import _op_filter, _resolve_operator_id
from api.models.schemas import NearestStop, StopResponse

router = APIRouter()


@router.get("/api/stops", response_model=List[StopResponse], tags=["stops"])
async def list_stops(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """List all active stops."""
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

        await _cache_set(cache_key, [r.model_dump() for r in result], CACHE_TTL_ROUTES_STOPS)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/api/stops/nearest", response_model=List[NearestStop], tags=["stops"])
async def find_nearest_stops(
    lat: float = Query(..., ge=-90, le=90),
    lon: float = Query(..., ge=-180, le=180),
    radius: int = Query(1000, ge=100, le=5000),
    limit: int = Query(10, ge=1, le=50),
):
    """Find nearest stops using PostGIS RPC."""
    try:
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
