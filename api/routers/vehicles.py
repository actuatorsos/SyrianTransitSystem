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
            op_id = await _resolve_operator_id(operator) if operator else None

        cache_key = _tenant_cache_key(CACHE_KEY_VEHICLES_LIST, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        # Query vehicles table directly (base table) so all vehicles are
        # returned even when the PostgREST embed on vehicle_positions_latest
        # fails or no position data exists yet.
        vehicles_query = (
            "vehicles?select=id,vehicle_id,name,name_ar,vehicle_type,"
            "capacity,status,assigned_route_id"
            "&status=neq.decommissioned"
        )
        if op_id:
            vehicles_query += f"&{_op_filter(op_id)}"
        vehicles = await _supabase_get(vehicles_query)

        # Fetch latest positions separately and merge by vehicle UUID
        pos_query = (
            "vehicle_positions_latest?select=vehicle_id,latitude,longitude,"
            "speed_kmh,occupancy_pct,recorded_at"
        )
        if op_id:
            pos_query += f"&{_op_filter(op_id)}"
        positions = await _supabase_get(pos_query)

        pos_by_id = {p["vehicle_id"]: p for p in (positions or [])}

        result = [
            VehicleResponse(
                id=v["id"],
                vehicle_id=v["vehicle_id"],
                name=v["name"],
                name_ar=v.get("name_ar", ""),
                vehicle_type=v["vehicle_type"],
                capacity=v["capacity"],
                status=v["status"],
                assigned_route_id=v.get("assigned_route_id"),
                latitude=pos_by_id.get(v["id"], {}).get("latitude"),
                longitude=pos_by_id.get(v["id"], {}).get("longitude"),
                speed_kmh=pos_by_id.get(v["id"], {}).get("speed_kmh"),
                occupancy_pct=pos_by_id.get(v["id"], {}).get("occupancy_pct"),
                recorded_at=pos_by_id.get(v["id"], {}).get("recorded_at"),
            )
            for v in (vehicles or [])
        ]

        await _cache_set(
            cache_key, [r.model_dump() for r in result], CACHE_TTL_VEHICLES
        )
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )


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
            op_id = await _resolve_operator_id(operator) if operator else None

        cache_key = _tenant_cache_key(CACHE_KEY_VEHICLES_POSITIONS, op_id or "all")
        cached = await _cache_get(cache_key)
        if cached is not None:
            return cached

        # Fetch positions and vehicle metadata separately to avoid broken
        # PostgREST embed from vehicle_positions_latest → vehicles.
        pos_query = (
            "vehicle_positions_latest"
            "?select=vehicle_id,latitude,longitude,speed_kmh,heading,source,"
            "occupancy_pct,recorded_at"
        )
        if op_id:
            pos_query += f"&{_op_filter(op_id)}"
        raw = await _supabase_get(pos_query)

        # Build vehicle lookup from vehicles table
        veh_query = (
            "vehicles?select=id,vehicle_id,vehicle_type,name,name_ar,assigned_route_id"
        )
        if op_id:
            veh_query += f"&{_op_filter(op_id)}"
        vehicles = await _supabase_get(veh_query)
        veh_by_id = {v["id"]: v for v in (vehicles or [])}

        result = []
        for pos in raw or []:
            vehicle = veh_by_id.get(pos.get("vehicle_id"), {})
            result.append(
                {
                    "vehicle_id": vehicle.get("vehicle_id") or pos.get("vehicle_id"),
                    "vehicle_type": vehicle.get("vehicle_type", "bus"),
                    "vehicle_name": vehicle.get("name", ""),
                    "vehicle_name_ar": vehicle.get("name_ar", ""),
                    "route_name": vehicle.get("assigned_route_id"),
                    "lat": pos.get("latitude"),
                    "lon": pos.get("longitude"),
                    "heading": pos.get("heading", 0),
                    "source": pos.get("source", "simulator"),
                    "speed_kmh": pos.get("speed_kmh"),
                    "occupancy_pct": pos.get("occupancy_pct"),
                    "recorded_at": pos.get("recorded_at"),
                }
            )

        await _cache_set(cache_key, result, CACHE_TTL_VEHICLES)
        return result

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e)
        )
