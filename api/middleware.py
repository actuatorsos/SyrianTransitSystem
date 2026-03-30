"""
Security middleware: CORS, rate limiting, structured logging, error handling.
Production-grade middleware stack for DamascusTransit API.
"""

import os
import time
import logging
import json
from datetime import datetime
from collections import defaultdict
from typing import Callable

from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

# ============================================================================
# Structured Logging
# ============================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()


class JSONFormatter(logging.Formatter):
    """JSON log formatter for structured logging in production."""

    def format(self, record):
        log_entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if hasattr(record, "request_id"):
            log_entry["request_id"] = record.request_id
        if hasattr(record, "method"):
            log_entry["method"] = record.method
        if hasattr(record, "path"):
            log_entry["path"] = record.path
        if hasattr(record, "status_code"):
            log_entry["status_code"] = record.status_code
        if hasattr(record, "duration_ms"):
            log_entry["duration_ms"] = record.duration_ms
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(log_entry)


def setup_logging():
    """Configure structured JSON logging."""
    logger = logging.getLogger("damascus_transit")
    logger.setLevel(getattr(logging, LOG_LEVEL, logging.INFO))

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)

    return logger


logger = setup_logging()


# ============================================================================
# Rate Limiting (In-Memory - suitable for Vercel serverless)
# ============================================================================


class RateLimiter:
    """Simple in-memory rate limiter.

    Note: On Vercel serverless, each function invocation gets fresh state,
    so this effectively limits burst requests within a single instance.
    For production at scale, use Redis-backed rate limiting via Upstash.
    """

    def __init__(self):
        self._requests: dict[str, list[float]] = defaultdict(list)

    def is_rate_limited(self, key: str, max_requests: int, window_seconds: int) -> bool:
        """Check if a key has exceeded the rate limit."""
        now = time.time()
        window_start = now - window_seconds

        # Clean old entries
        self._requests[key] = [t for t in self._requests[key] if t > window_start]

        if len(self._requests[key]) >= max_requests:
            return True

        self._requests[key].append(now)
        return False


rate_limiter = RateLimiter()


# ============================================================================
# Request Logging Middleware
# ============================================================================


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every request with method, path, status, and duration."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        start_time = time.time()
        request_id = f"{int(start_time * 1000)}"

        # Add request_id to state for downstream use
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception as exc:
            duration_ms = round((time.time() - start_time) * 1000, 2)
            logger.error(
                f"Request failed: {request.method} {request.url.path}",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": str(request.url.path),
                    "duration_ms": duration_ms,
                },
                exc_info=True,
            )
            raise

        duration_ms = round((time.time() - start_time) * 1000, 2)

        # Log based on status code severity
        log_level = logging.INFO if response.status_code < 400 else logging.WARNING
        if response.status_code >= 500:
            log_level = logging.ERROR

        logger.log(
            log_level,
            f"{request.method} {request.url.path} → {response.status_code} ({duration_ms}ms)",
            extra={
                "request_id": request_id,
                "method": request.method,
                "path": str(request.url.path),
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )

        # Add security headers to all responses
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"

        return response


# ============================================================================
# Rate Limiting Middleware
# ============================================================================


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Apply rate limiting to sensitive endpoints."""

    # Endpoint-specific rate limits: (max_requests, window_seconds)
    RATE_LIMITS = {
        "/api/auth/login": (5, 60),       # 5 login attempts per minute
        "/api/admin/users": (20, 60),     # 20 user operations per minute
        "/api/driver/position": (60, 60), # 60 position updates per minute (1/sec)
    }

    # Global rate limit for all API endpoints
    GLOBAL_LIMIT = (100, 60)  # 100 requests per minute per IP

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        client_ip = request.client.host if request.client else "unknown"
        path = request.url.path

        # Check endpoint-specific rate limit
        for endpoint, (max_req, window) in self.RATE_LIMITS.items():
            if path.startswith(endpoint):
                key = f"{client_ip}:{endpoint}"
                if rate_limiter.is_rate_limited(key, max_req, window):
                    logger.warning(
                        f"Rate limit exceeded: {client_ip} on {endpoint}",
                        extra={"method": request.method, "path": path},
                    )
                    return JSONResponse(
                        status_code=429,
                        content={
                            "error": "Too many requests",
                            "detail": f"Rate limit exceeded. Max {max_req} requests per {window}s.",
                            "retry_after": window,
                        },
                        headers={"Retry-After": str(window)},
                    )

        # Check global rate limit
        global_key = f"{client_ip}:global"
        if rate_limiter.is_rate_limited(global_key, *self.GLOBAL_LIMIT):
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests", "retry_after": self.GLOBAL_LIMIT[1]},
                headers={"Retry-After": str(self.GLOBAL_LIMIT[1])},
            )

        return await call_next(request)


# ============================================================================
# Setup Function
# ============================================================================

# Allowed origins for CORS
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")
# Always allow the Vercel deployment URLs and localhost for dev
DEFAULT_ORIGINS = [
    "https://syrian-transit-system.vercel.app",
    "https://damascus-transit.vercel.app",
    "http://localhost:3000",
    "http://localhost:8000",
    "http://localhost:8080",
]


def setup_middleware(app: FastAPI):
    """Apply all middleware to the FastAPI app in correct order.

    Middleware executes in REVERSE order of addition (last added = first executed).
    Order: Rate Limiting → Logging → CORS → App
    """
    # CORS — must be added first (executed last, wraps everything)
    origins = [o.strip() for o in ALLOWED_ORIGINS if o.strip()] or DEFAULT_ORIGINS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Content-Type", "Authorization", "X-Traccar-Signature"],
    )

    # Request logging
    app.add_middleware(RequestLoggingMiddleware)

    # Rate limiting
    app.add_middleware(RateLimitMiddleware)

    logger.info(f"Middleware configured. CORS origins: {origins}")
