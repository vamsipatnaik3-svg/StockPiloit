import hashlib

import pytest
from fastapi import HTTPException
from redis.exceptions import RedisError
from starlette.requests import Request

from app.core import rate_limit


def make_request(ip="192.0.2.15"):
    return Request({
        "type": "http",
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": [],
        "client": (ip, 12345),
        "server": ("testserver", 80),
    })


def test_login_rate_limit_keys_hash_account_and_ip():
    account_key, ip_key = rate_limit._login_rate_limit_keys(
        make_request(), " Owner@Example.com "
    )

    assert hashlib.sha256(b"owner@example.com").hexdigest() in account_key
    assert "owner@example.com" not in account_key
    assert "192.0.2.15" not in account_key
    assert "192.0.2.15" not in ip_key


@pytest.mark.parametrize(
    "operation",
    [rate_limit.enforce_login_rate_limit, rate_limit.record_login_failure],
)
def test_login_rate_limiter_fails_closed_when_redis_is_unavailable(
    monkeypatch, operation
):
    class UnavailableRedis:
        def eval(self, *args):
            raise RedisError("simulated connection failure")

    monkeypatch.setattr(rate_limit, "redis_client", UnavailableRedis())

    with pytest.raises(HTTPException) as exc_info:
        if operation is rate_limit.enforce_login_rate_limit:
            operation(make_request(), "owner@example.com")
        else:
            operation(make_request(), "owner@example.com")

    assert exc_info.value.status_code == 503
    assert "temporarily unavailable" in exc_info.value.detail
