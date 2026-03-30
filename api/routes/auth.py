"""
Authentication routes: login, password change.
"""

from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, status

from lib.database import get_db
from lib.auth import (
    verify_password,
    hash_password,
    create_access_token,
    get_current_user,
    CurrentUser,
)
from api.models import LoginRequest, TokenResponse, PasswordChange

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest):
    """
    Authenticate user and return JWT token.

    Returns:
        JWT access token, user info, and whether password change is required
    """
    db = get_db()

    try:
        result = (
            db.table("users")
            .select("id, email, password_hash, role, must_change_password")
            .eq("email", request.email)
            .eq("is_active", True)
            .execute()
        )
        users = result.data

        if not users:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        user = users[0]

        if not verify_password(request.password, user["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid credentials",
            )

        token = create_access_token(
            user_id=user["id"], email=user["email"], role=user["role"]
        )

        return TokenResponse(
            access_token=token,
            user_id=user["id"],
            role=user["role"],
            must_change_password=user.get("must_change_password", False),
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication service error",
        )


@router.post("/change-password")
async def change_password(
    data: PasswordChange,
    current_user: CurrentUser = Depends(get_current_user),
):
    """
    Change the current user's password.

    Requires authentication. Verifies current password before updating.
    """
    db = get_db()

    try:
        # Get current password hash
        result = (
            db.table("users")
            .select("password_hash")
            .eq("id", current_user.user_id)
            .execute()
        )

        if not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
            )

        if not verify_password(data.current_password, result.data[0]["password_hash"]):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Current password is incorrect",
            )

        # Update password and clear the must_change_password flag
        new_hash = hash_password(data.new_password)
        db.table("users").update(
            {"password_hash": new_hash, "must_change_password": False}
        ).eq("id", current_user.user_id).execute()

        return {
            "status": "success",
            "message": "Password changed successfully",
            "timestamp": datetime.utcnow().isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Password change failed",
        )
