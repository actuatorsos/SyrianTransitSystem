from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from api.core.auth import CurrentUser, optional_auth
from api.core.cache import CACHE_KEY_STATS, CACHE_TTL_STATS, _cache_get, _cache_set, _tenant_cache_key
from api.core.database import _supabase_get
from api.core.tenancy import _op_filter, _resolve_operator_id

router = APIRouter()


@router.get("/api/stats", response_model=dict, tags=["stats"])
async def get_fleet_stats(
    operator: Optional[str] = Query(None, description="Operator slug"),
    current_user: Optional[CurrentUser] = Depends(optional_auth),
):
    """Get fleet statistics and real-time metrics."""
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

        vehicles = await _supabase_get(f"vehicles?is_active=eq.true&select=id,status{op_suffix}")
        active_count = len([v for v in vehicles if v.get("status") == "active"]) if vehicles else 0
        idle_count = len([v for v in vehicles if v.get("status") == "idle"]) if vehicles else 0
        maintenance_count = len([v for v in vehicles if v.get("status") == "maintenance"]) if vehicles else 0

        routes = await _supabase_get(f"routes?is_active=eq.true&select=id{op_suffix}")
        stops = await _supabase_get(f"stops?is_active=eq.true&select=id{op_suffix}")
        drivers = await _supabase_get(f"users?role=eq.driver&select=id,is_active{op_suffix}")
        active_drivers = len([d for d in drivers if d.get("is_active")]) if drivers else 0

        positions = await _supabase_get(f"vehicle_positions_latest?select=occupancy_pct{op_suffix}")
        occupancy_values = [p["occupancy_pct"] for p in positions if p.get("occupancy_pct") is not None]
        avg_occupancy = sum(occupancy_values) / len(occupancy_values) if occupancy_values else None

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
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))
