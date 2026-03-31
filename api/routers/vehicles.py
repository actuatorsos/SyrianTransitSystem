from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.auth import CurrentUser, optional_auth
from api.core.cache import (
    CACHE_KEY_VEHICLES_LIST,
    CACHE_KEY_VEHICLES_POSITIONS,
    CACHE_TTL_VEHICLES,
    _cache_get,
    _cache_set,
    _tenant_cache_key,
)
from api.core.database import _supabase_get
from api.core.tenancy import _op_filter, _resolve_operator_id
from api.models.schemas import VehicleResponse

router = APIRouter()


@router.get("/api/vehicles", response_model=List[VehicleResponse], tags=["vehicles"])
async def list_vehicles(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """List all active vehicles with latest positions."""
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
            for v in (positions or [])
            if v.get("vehicles")
        ]

        await _cache_set(cache_key, [r.model_dump() for r in result], CACHE_TTL_VEHICLES)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.get("/api/vehicles/positions", response_model=List[dict], tags=["vehicles"])
async def get_vehicle_positions(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """Get latest vehicle positions only (lightweight endpoint)."""
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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
