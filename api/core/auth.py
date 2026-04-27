import os
import contextvars
from datetime import datetime, timedelta
from typing import Literal, Optional

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer
from fastapi.security.http import HTTPAuthorizationCredentials as HTTPAuthCredentials
from pydantic import BaseModel

JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)

UserRole = Literal["admin", "dispatcher", "driver", "viewer", "super_admin"]

current_user_token = contextvars.ContextVar("current_user_token", default=None)

_PLACEHOLDER_JWT_SECRETS = {"change-me-to-a-random-64-char-string", "secret", ""}


def _get_jwt_secret() -> str:
    secret = os.getenv("JWT_SECRET", "")
    if not secret or secret in _PLACEHOLDER_JWT_SECRETS or len(secret) < 32:
        raise HTTPException(
            status_code=500,
            detail="JWT_SECRET is not configured or is too weak (minimum 32 characters required)",
        )
    return secret


class TokenPayload(BaseModel):
    user_id: str
    email: str
    role: UserRole
    exp: datetime
    operator_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_route_id: Optional[str] = None


class CurrentUser(BaseModel):
    user_id: str
    email: str
    role: UserRole
    operator_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_route_id: Optional[str] = None


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode(), salt).decode()


def verify_password(plain_password: str, hashed_password: str) -> bool:
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

    return jwt.encode(to_encode, _get_jwt_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str) -> TokenPayload:
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
    token = credentials.credentials
    current_user_token.set(token)
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
    credentials: Optional[HTTPAuthCredentials] = Depends(optional_security),
) -> Optional[CurrentUser]:
    if credentials is None:
        current_user_token.set(None)
        return None
    token = credentials.credentials
    current_user_token.set(token)
    token_payload = verify_token(token)
    return CurrentUser(
        user_id=token_payload.user_id,
        email=token_payload.email,
        role=token_payload.role,
        operator_id=token_payload.operator_id,
        vehicle_id=token_payload.vehicle_id,
        vehicle_route_id=token_payload.vehicle_route_id,
    )
