import time
import redis.asyncio as aioredis

from app.config import get_settings
from app.logger import get_logger

settings = get_settings()
logger = get_logger(__name__)


def get_redis() -> aioredis.Redis:
    return aioredis.from_url(settings.redis_url, decode_responses=True)


async def check_rate_limit(
    tenant_id: str,
    limit: int,
    window_seconds: int = 60,
) -> tuple[bool, int, int]:
    """
    Sliding window rate limiter.
    Returns (allowed, current_count, retry_after_seconds)
    """
    redis = get_redis()
    now = time.time()
    window_start = now - window_seconds
    key = f"ratelimit:{tenant_id}"

    pipe = redis.pipeline()
    # Remove old entries outside window
    await pipe.zremrangebyscore(key, 0, window_start)
    # Count current entries
    await pipe.zcard(key)
    # Add current request
    await pipe.zadd(key, {str(now): now})
    # Set expiry
    await pipe.expire(key, window_seconds)
    results = await pipe.execute()

    current_count = results[1]
    await redis.aclose()

    if current_count >= limit:
        retry_after = int(window_seconds - (now - window_start))
        logger.warning(
            "rate_limit_exceeded",
            tenant_id=tenant_id,
            count=current_count,
            limit=limit,
        )
        return False, current_count, retry_after

    return True, current_count + 1, 0