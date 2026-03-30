"""
JWT authentication and authorization utilities.
Handles token generation, validation, and role-based access control.
"""

import os
from datetime import datetime, timedelta
from typing import Optional, Literal
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthCredentials
from dotenv import load_dotenv

load_dotenv()

JWT_SECRET = os.getenv("JWT_SECRET")
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

if not JWT_SECRET:
    raise ValueError("JWT_SECRET environment variable is required")

# Password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# HTTP Bearer security scheme
security = HTTPBearer()

UserRole = Literal["admin", "dispatcher", "driver", "viewer"]


class TokenPayload(BaseModel):
    """JWT token payload structure."""

    user_id: str
    email: str
    role: UserRole
    exp: datetime


class CurrentUser(BaseModel):
    """Current authenticated user context."""

    user_id: str
    email: str
    role: UserRole


def hash_password(password: str) -> str:
    """Hash a plain text password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain text password against a bcrypt hash."""
    return pwd_context.verify(plain_password, hashed_password)


def create_access_token(
    user_id: str, email: str, role: UserRole, expires_delta: Optional[timedelta] = None
) -> str:
    """
    Create a JWT access token.

    Args:
        user_id: User UUID
        email: User email address
        role: User role (admin, dispatcher, driver, viewer)
        expires_delta: Custom expiration time (default: 24 hours)

    Returns:
        Encoded JWT token string
    """
    if expires_delta is None:
        expires_delta = timedelta(hours=JWT_EXPIRATION_HOURS)

    expire = datetime.utcnow() + expires_delta
    to_encode = {"user_id": user_id, "email": email, "role": role, "exp": expire}

    encoded_jwt = jwt.encode(to_encode, JWT_SECRET, algorithm=JWT_ALGORITHM)
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
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id: str = payload.get("user_id")
        email: str = payload.get("email")
        role: str = payload.get("role")

        if user_id is None or email is None or role is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token payload"
            )

        return TokenPayload(
            user_id=user_id, email=email, role=role, exp=payload.get("exp")
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired token"
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
    )
