import json
import os
import time

from fastapi import Request

# Cache TTLs (seconds)
CACHE_TTL_VEHICLES = 5
CACHE_TTL_ROUTES_STOPS = 300
CACHE_TTL_STATS = 30

# Cache key prefixes
CACHE_KEY_VEHICLES_LIST = "transit:vehicles:list"
CACHE_KEY_VEHICLES_POSITIONS = "transit:vehicles:positions"
CACHE_KEY_ROUTES_LIST = "transit:routes:list"
CACHE_KEY_STATS = "transit:stats"
CACHE_KEY_STOPS_LIST = "transit:stops:list"

# Rate limit tuples: (max_requests, window_seconds)
RATE_LIMIT_LOGIN = (10, 60)
RATE_LIMIT_DRIVER_POS = (12, 60)
RATE_LIMIT_GLOBAL = (200, 60)
RATE_LIMIT_PUSH_SUB = (5, 60)


def _tenant_cache_key(base: str, operator_id: str) -> str:
    """Namespace a cache key by operator so tenants never share cached data."""
    return f"{base}:{operator_id}"


def _get_redis_client():
    """Return an Upstash Redis async client, or None if not configured."""
    url = os.getenv("UPSTASH_REDIS_REST_URL", "")
    token = os.getenv("UPSTASH_REDIS_REST_TOKEN", "")
    if not url or not token:
        return None
    try:
        from upstash_redis.asyncio import Redis

        return Redis(url=url, token=token)
    except Exception:
        return None


async def _cache_get(key: str):
    """Retrieve a JSON-encoded value from Redis. Returns None on miss or error."""
    client = _get_redis_client()
    if client is None:
        return None
    try:
        raw = await client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


async def _cache_set(key: str, value, ttl: int) -> None:
    """Store a JSON-encoded value in Redis with TTL. Silently fails if unavailable."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.set(key, json.dumps(value, default=str), ex=ttl)
    except Exception:
        pass


async def _cache_delete(*keys: str) -> None:
    """Invalidate one or more Redis cache keys. Silently fails if unavailable."""
    client = _get_redis_client()
    if client is None:
        return
    try:
        await client.delete(*keys)
    except Exception:
        pass


async def _redis_health_check() -> bool:
    """Check Redis connectivity (returns True when Redis is not configured)."""
    client = _get_redis_client()
    if client is None:
        return True
    try:
        await client.ping()
        return True
    except Exception:
        return False


async def _rate_limit_check(
    identifier: str, max_requests: int, window_seconds: int
) -> bool:
    """Fixed-window rate limiter backed by Upstash Redis. Returns True if allowed."""
    client = _get_redis_client()
    if client is None:
        return True
    try:
        window = int(time.time()) // window_seconds
        key = f"rl:{identifier}:{window}"
        count = await client.incr(key)
        if count == 1:
            await client.expire(key, window_seconds + 1)
        return count <= max_requests
    except Exception:
        return True


def _get_client_ip(request: Request) -> str:
    """Extract the real client IP, honoring Vercel's X-Forwarded-For proxy header."""
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return "unknown"
