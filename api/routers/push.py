import os
from datetime import datetime

from fastapi import APIRouter, HTTPException, Request, status

from api.core.cache import RATE_LIMIT_PUSH_SUB, _cache_delete, _cache_set, _get_client_ip, _get_redis_client, _rate_limit_check
from api.models.schemas import PushSubscribeRequest

router = APIRouter()

# In-memory push subscription store (keyed by endpoint URL).
# For production, migrate to Redis or Supabase push_subscriptions table.
_push_subscriptions: dict = {}


@router.get("/api/push/vapid-public-key", tags=["push"])
async def get_vapid_public_key():
    """Return the VAPID public key for Web Push subscription setup."""
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    return {"publicKey": key, "enabled": bool(key)}


@router.post("/api/push/subscribe", tags=["push"])
async def subscribe_push(req: PushSubscribeRequest, raw_request: Request):
    """Store a Web Push subscription and associate it with watched stop IDs."""
    client_ip = _get_client_ip(raw_request)
    max_req, window = RATE_LIMIT_PUSH_SUB
    if not await _rate_limit_check(f"pushsub:{client_ip}", max_req, window):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many subscription requests. Try again later.",
        )
    endpoint = req.subscription.endpoint
    _push_subscriptions[endpoint] = {
        "subscription": req.subscription.model_dump(),
        "stopIds": req.stopIds,
        "createdAt": datetime.utcnow().isoformat(),
    }
    redis = _get_redis_client()
    if redis:
        try:
            await _cache_set(
                f"push_sub:{endpoint}",
                _push_subscriptions[endpoint],
                ttl=60 * 60 * 24 * 30,
            )
        except Exception:
            pass
    return {"status": "subscribed", "endpoint": endpoint}


@router.delete("/api/push/subscribe", tags=["push"])
async def unsubscribe_push(req: dict):
    """Remove a Web Push subscription by endpoint URL."""
    endpoint = req.get("endpoint", "")
    _push_subscriptions.pop(endpoint, None)
    redis = _get_redis_client()
    if redis:
        try:
            await _cache_delete(f"push_sub:{endpoint}")
        except Exception:
            pass
    return {"status": "unsubscribed"}
