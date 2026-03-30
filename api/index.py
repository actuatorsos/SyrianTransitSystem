"""
DamascusTransit FastAPI Backend — Production Server v1.1.0

Entry point for Vercel serverless deployment.
Routes are organized into modular routers; middleware handles
CORS, rate limiting, structured logging, and security headers.
"""

import asyncio
from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from api.middleware import setup_middleware, logger
from api.routes.public import router as public_router
from api.routes.auth import router as auth_router
from api.routes.driver import router as driver_router
from api.routes.admin import router as admin_router
from api.routes.traccar import router as traccar_router
from api.routes.ws import router as ws_router, _position_broadcast_loop

# ============================================================================
# App Initialization
# ============================================================================

app = FastAPI(
    title="DamascusTransit API",
    description="Real-time transit tracking and fleet management for Damascus",
    version="1.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# Apply security middleware stack
setup_middleware(app)

# Register route modules
app.include_router(public_router)
app.include_router(auth_router)
app.include_router(driver_router)
app.include_router(admin_router)
app.include_router(traccar_router)
app.include_router(ws_router)


@app.on_event("startup")
async def startup_event():
    """Start the WebSocket position broadcast background loop."""
    asyncio.create_task(_position_broadcast_loop())


# ============================================================================
# Global Error Handlers
# ============================================================================


@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    """Catch-all handler — never expose internal errors to clients."""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "timestamp": datetime.utcnow().isoformat(),
        },
    )


@app.get("/")
async def root():
    """Root endpoint — API info and documentation links."""
    return {
        "name": "DamascusTransit API",
        "version": "1.1.0",
        "docs": "/api/docs",
        "health": "/api/health",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
