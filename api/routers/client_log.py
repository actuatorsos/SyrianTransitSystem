"""
Client-side error logging endpoint.
Accepts uncaught JS errors reported by the browser and records them via the
structured logger (and Sentry when configured).
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request
from pydantic import BaseModel

router = APIRouter()
logger = logging.getLogger(__name__)


class ClientErrorPayload(BaseModel):
    message: str
    source: Optional[str] = ""
    lineno: Optional[int] = 0
    colno: Optional[int] = 0
    type: Optional[str] = "Error"
    url: Optional[str] = ""
    userAgent: Optional[str] = ""
    timestamp: Optional[str] = ""


@router.post("/api/log-client-error", status_code=204, tags=["health"])
async def log_client_error(payload: ClientErrorPayload, request: Request):
    """Receive and record an uncaught JS error from a browser client."""
    client_ip = request.headers.get(
        "x-forwarded-for", request.client.host if request.client else "unknown"
    )

    logger.error(
        "client_js_error",
        extra={
            "error_type": payload.type,
            "message": payload.message,
            "source": payload.source,
            "lineno": payload.lineno,
            "colno": payload.colno,
            "page_url": payload.url,
            "client_ip": client_ip,
            "client_timestamp": payload.timestamp,
        },
    )

    # Forward to Sentry when available so client errors appear alongside
    # server errors in the same project.
    try:
        import sentry_sdk

        with sentry_sdk.push_scope() as scope:
            scope.set_tag("source", "client_js")
            scope.set_extra("page_url", payload.url)
            scope.set_extra("error_source_file", payload.source)
            scope.set_extra("lineno", payload.lineno)
            scope.set_extra("colno", payload.colno)
            scope.set_extra("userAgent", payload.userAgent)
            sentry_sdk.capture_message(
                f"[Client JS] {payload.type}: {payload.message}",
                level="error",
            )
    except Exception:
        pass  # Sentry not configured — already logged above
