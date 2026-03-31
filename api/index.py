"""
DamascusTransit FastAPI Backend — Modular edition.
This file is the thin app factory; all business logic lives in api/routers/*.
"""

import asyncio
import os
import sys
import time
import uuid
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
load_dotenv()

# ── Structured logging ───────────────────────────────────────────────────────
from api.core.logging import setup_logging  # noqa: E402

setup_logging()

from api.core.logging import logger  # noqa: E402

# ── Sentry (optional) ────────────────────────────────────────────────────────
_SENTRY_DSN = os.getenv("SENTRY_DSN", "")
if _SENTRY_DSN:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
    from sentry_sdk.integrations.httpx import HttpxIntegration

    sentry_sdk.init(
        dsn=_SENTRY_DSN,
        integrations=[FastApiIntegration(), HttpxIntegration()],
        traces_sample_rate=0.1,
        profiles_sample_rate=0.0,
        environment=os.getenv("VERCEL_ENV", "development"),
        send_default_pii=False,
    )
    logger.info("Sentry error tracking initialised")
else:
    logger.info("SENTRY_DSN not set — error tracking disabled")

# ── OpenAPI tag metadata ─────────────────────────────────────────────────────
_OPENAPI_TAGS = [
    {
        "name": "health",
        "description": "Service health and status checks. No authentication required.",
    },
    {"name": "auth", "description": "User authentication. Returns a JWT bearer token."},
    {
        "name": "routes",
        "description": "Transit route data. Public read access; no authentication required.",
    },
    {
        "name": "stops",
        "description": "Bus stop locations and nearest-stop lookup. Public read access.",
    },
    {
        "name": "vehicles",
        "description": "Real-time vehicle positions and fleet list. Public read access.",
    },
    {
        "name": "stream",
        "description": "Server-Sent Events (SSE) stream for live vehicle updates. Public.",
    },
    {
        "name": "websocket",
        "description": "WebSocket real-time vehicle tracking with route subscriptions.",
    },
    {"name": "stats", "description": "Aggregate fleet statistics. Public read access."},
    {
        "name": "schedules",
        "description": "Route schedules and timetables. Public read access.",
    },
    {
        "name": "alerts",
        "description": "Passenger-facing service alerts. Public read access.",
    },
    {
        "name": "driver",
        "description": "Driver-only endpoints. Requires `driver` role JWT.",
    },
    {
        "name": "admin",
        "description": "Admin and dispatcher endpoints. Requires `admin` or `dispatcher` role JWT.",
    },
    {
        "name": "traccar",
        "description": "Traccar GPS device webhooks. Secured by HMAC signature header.",
    },
    {
        "name": "gtfs",
        "description": "GTFS static and realtime feeds for Google Maps / transit apps.",
    },
    {
        "name": "operators",
        "description": "Fleet operator (tenant) management. super_admin role required for most operations.",
    },
    {"name": "push", "description": "Web Push notification subscriptions."},
    {"name": "cron", "description": "Scheduled background jobs. Bearer-token secured."},
]

app = FastAPI(
    title="DamascusTransit API",
    description=(
        "Real-time transit tracking and fleet management — multi-tenant SaaS edition.\n\n"
        "## Authentication\n\n"
        "Most read endpoints are public but require an `?operator=<slug>` query parameter.\n"
        "1. **POST /api/v1/auth/login** — exchange email/password for a JWT token\n"
        "2. Include the token as `Authorization: Bearer <token>` on protected endpoints\n\n"
        "Roles: `super_admin` · `admin` · `dispatcher` · `driver` · `viewer`\n\n"
        "Tokens expire after 24 hours."
    ),
    version="1.0.0",
    openapi_tags=_OPENAPI_TAGS,
)

# ── CORS ─────────────────────────────────────────────────────────────────────
_cors_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_allowed_origins = [o.strip() for o in _cors_origins_env.split(",") if o.strip()]
if not _allowed_origins:
    raise RuntimeError(
        "ALLOWED_ORIGINS env var must be set to a comma-separated list of allowed origins"
    )
_is_production = os.getenv("VERCEL_ENV", "").lower() == "production"
if _is_production:
    _allowed_origins = [
        o for o in _allowed_origins if "localhost" not in o and "127.0.0.1" not in o
    ]
    if not _allowed_origins:
        raise RuntimeError(
            "All ALLOWED_ORIGINS are localhost — no valid origins remain for production"
        )

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
)

# ── Middleware ────────────────────────────────────────────────────────────────
from api.core.cache import RATE_LIMIT_GLOBAL, _get_client_ip, _rate_limit_check  # noqa: E402

_GLOBAL_RATE_LIMIT_SKIP = frozenset(
    {"/api/health", "/", "/docs", "/openapi.json", "/redoc"}
)

_API_V1_PREFIX = "/api/v1"
_API_PREFIX = "/api"
_SUNSET_DATE = "2026-09-30"


@app.middleware("http")
async def _global_rate_limit_middleware(request: Request, call_next):
    if request.url.path not in _GLOBAL_RATE_LIMIT_SKIP:
        client_ip = _get_client_ip(request)
        max_req, window = RATE_LIMIT_GLOBAL
        if not await _rate_limit_check(f"global:{client_ip}", max_req, window):
            logger.warning(
                "global_rate_limit_exceeded",
                extra={"client_ip": client_ip, "path": request.url.path},
            )
            return JSONResponse(
                status_code=429,
                content={
                    "detail": "Too many requests. Please slow down.",
                    "timestamp": datetime.utcnow().isoformat(),
                },
                headers={"Retry-After": str(window)},
            )
    return await call_next(request)


@app.middleware("http")
async def _request_logging_middleware(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    duration_ms = round((time.perf_counter() - start) * 1000, 1)
    logger.info(
        "request",
        extra={
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    response.headers["X-Request-Id"] = request_id
    return response


@app.middleware("http")
async def _api_versioning_middleware(request: Request, call_next):
    original_path = request.url.path
    if (
        original_path.startswith(_API_V1_PREFIX + "/")
        or original_path == _API_V1_PREFIX
    ):
        new_path = _API_PREFIX + original_path[len(_API_V1_PREFIX) :]
        if not new_path:
            new_path = _API_PREFIX
        request.scope["path"] = new_path
        response = await call_next(request)
        response.headers["X-API-Version"] = "v1"
        return response
    if original_path.startswith(_API_PREFIX + "/") or original_path == _API_PREFIX:
        response = await call_next(request)
        v1_path = _API_V1_PREFIX + original_path[len(_API_PREFIX) :]
        response.headers["X-API-Version"] = "v1"
        response.headers["Deprecation"] = "true"
        response.headers["Sunset"] = _SUNSET_DATE
        response.headers["Link"] = f'<{v1_path}>; rel="successor-version"'
        return response
    return await call_next(request)


# ── Routers ───────────────────────────────────────────────────────────────────
from api.routers import (  # noqa: E402
    admin,
    alerts,
    auth,
    cron,
    driver,
    gtfs,
    health,
    operators,
    push,
    routes,
    schedules,
    stats,
    stops,
    stream,
    traccar,
    vehicles,
    websocket,
)

for _router in [
    health.router,
    auth.router,
    routes.router,
    stops.router,
    vehicles.router,
    stream.router,
    websocket.router,
    stats.router,
    schedules.router,
    alerts.router,
    driver.router,
    admin.router,
    cron.router,
    traccar.router,
    gtfs.router,
    push.router,
    operators.router,
]:
    app.include_router(_router)


# ── Startup event ─────────────────────────────────────────────────────────────
@app.on_event("startup")
async def _startup():
    asyncio.create_task(websocket._ws_broadcast_loop())


# ── Exception handlers ────────────────────────────────────────────────────────
from fastapi import HTTPException  # noqa: E402


@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail, "timestamp": datetime.utcnow().isoformat()},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request, exc):
    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.get("/")
async def root():
    return {"message": "DamascusTransit API", "docs": "/docs", "health": "/api/health"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
