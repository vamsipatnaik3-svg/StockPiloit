
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

LOGIN_CHECK_SCRIPT = """
local account_count = tonumber(redis.call('GET', KEYS[1]) or '0')
local ip_count = tonumber(redis.call('GET', KEYS[2]) or '0')
local account_limit = tonumber(ARGV[1])
local ip_limit = tonumber(ARGV[2])
local wait = 0
if account_count >= account_limit then
  wait = math.max(wait, redis.call('TTL', KEYS[1]))
end
if ip_count >= ip_limit then
  wait = math.max(wait, redis.call('TTL', KEYS[2]))
end
if wait > 0 then return {0, wait} end
if account_count >= account_limit or ip_count >= ip_limit then
  return {0, 1}
end
return {1, 0}
"""

LOGIN_FAILURE_SCRIPT = """
local account_count = redis.call('INCR', KEYS[1])
if account_count == 1 then redis.call('EXPIRE', KEYS[1], ARGV[1]) end
local ip_count = redis.call('INCR', KEYS[2])
if ip_count == 1 then redis.call('EXPIRE', KEYS[2], ARGV[1]) end
return {account_count, ip_count}
"""


def _login_rate_limit_keys(request: Request, account_identity: str) -> tuple[str, str]:
    client_ip = request.client.host if request.client is not None else "unknown"
    ip_hash = hashlib.sha256(client_ip.encode("utf-8")).hexdigest()
    normalized_identity = account_identity.strip().casefold()
    identity_hash = hashlib.sha256(normalized_identity.encode("utf-8")).hexdigest()
    return (
        f"tavuno:rate-limit:login:account-ip:{identity_hash}:{ip_hash}",
        f"tavuno:rate-limit:login:ip:{ip_hash}",
    )


def enforce_login_rate_limit(request: Request, account_identity: str) -> None:
    """Fail closed when Redis is unavailable; only failed logins consume counts."""
    account_key, ip_key = _login_rate_limit_keys(request, account_identity)
    try:
        allowed, retry_after = redis_client.eval(
            LOGIN_CHECK_SCRIPT, 2, account_key, ip_key,
            settings.login_rate_limit_account_ip, settings.login_rate_limit_ip,
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again later.",
        ) from exc
    if not int(allowed):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Please try again later.",
            headers={"Retry-After": str(max(int(retry_after), 1))},
        )


def record_login_failure(request: Request, account_identity: str) -> None:
    """Record failed credentials in a fixed window without storing account text."""
    account_key, ip_key = _login_rate_limit_keys(request, account_identity)
    try:
        redis_client.eval(
            LOGIN_FAILURE_SCRIPT, 2, account_key, ip_key,
            settings.login_rate_limit_window_seconds,
        )
    except RedisError as exc:
        # Do not return a normal credential failure if it could not be counted.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Service temporarily unavailable. Please try again later.",
        ) from exc


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
