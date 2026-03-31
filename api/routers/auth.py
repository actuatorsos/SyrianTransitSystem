import urllib.parse
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status

from api.core.auth import (
    create_access_token,
    verify_password,
)
from api.core.cache import RATE_LIMIT_LOGIN, _rate_limit_check
from api.core.database import _supabase_get
from api.models.schemas import LoginRequest, TokenResponse

router = APIRouter()


@router.post("/api/auth/login", response_model=TokenResponse, tags=["auth"])
async def login(request: LoginRequest, raw_request: Request):
    """Authenticate user and return JWT token."""
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

        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials"
            )

        operator_id: Optional[str] = user.get("operator_id")

        vehicle_id = None
        vehicle_route_id = None
        if user["role"] == "driver":
            driver_vehicles = await _supabase_get(
                f"vehicles?assigned_driver_id=eq.{user['id']}&select=id,assigned_route_id"
            )
            if driver_vehicles:
                vehicle_id = driver_vehicles[0]["id"]
                vehicle_route_id = driver_vehicles[0].get("assigned_route_id")

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
