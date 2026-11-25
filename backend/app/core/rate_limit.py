
import hashlib

from fastapi import HTTPException, Request, status
from redis import Redis
from redis.exceptions import RedisError

from app.core.config import settings


redis_client = Redis.from_url(
    settings.redis_url,
    decode_responses=True,
    socket_connect_timeout=2,
    socket_timeout=2,
)


RATE_LIMIT_SCRIPT = """
local current = redis.call("INCR", KEYS[1])

if current == 1 then
    redis.call("EXPIRE", KEYS[1], ARGV[1])
end

local ttl = redis.call("TTL", KEYS[1])

return {current, ttl}
"""


def enforce_rate_limit(
    request: Request,
    action: str,
    limit: int,
    window_seconds: int,
) -> None:
    """
    Enforce a Redis-backed fixed-window rate limit.

    Raises HTTP 429 when the limit is exceeded.
    Raises HTTP 503 when Redis is unavailable.
    """

    client_ip = (
        request.client.host
        if request.client is not None
        else "unknown"
    )

    # Hash the IP so raw IP addresses are not stored in Redis keys.
    ip_hash = hashlib.sha256(
        client_ip.encode("utf-8")
    ).hexdigest()

    redis_key = f"tavuno:rate-limit:{action}:{ip_hash}"

    try:
        result = redis_client.eval(
            RATE_LIMIT_SCRIPT,
            1,
            redis_key,
            window_seconds,
        )

        request_count = int(result[0])
        remaining_seconds = max(int(result[1]), 1)

    except RedisError as exc:
        # Fail closed: do not allow sensitive operations when
        # the rate limiter cannot verify the request count.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again later.",
        ) from exc

    if request_count > limit:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={
                "Retry-After": str(remaining_seconds),
            },
        )
