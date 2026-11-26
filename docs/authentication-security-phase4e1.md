# Authentication security hardening (Phase 4E.1)

## Session cookies

`APP_ENVIRONMENT` controls the session cookie's `Secure` attribute. The default
is `development`; `development`, `dev`, `local`, and `test` keep `Secure` off so
the cookie works over local HTTP. Other environment values, including
`production`, enable `Secure` and therefore require HTTPS in the browser.
`HttpOnly`, `SameSite=Lax`, the existing cookie name, path, and lifetime are
shared by cookie creation and deletion.

## Login throttling

Login attempts use the existing Redis service. Only failed credentials consume
the fixed-window allowance. A normalized email plus client IP is limited to 5
failures per 900 seconds; all accounts from one client IP share a second limit
of 30 failures per 900 seconds. Successful attempts do not increment either
counter. Both counter keys contain SHA-256 digests rather than the email or IP
in plaintext. The temporary window avoids permanent account lockout, while the
IP limit constrains attempts spread across many account names. Redis keys are
not authentication credentials and no passwords are placed in keys or logs.

The login endpoint fails closed with a generic HTTP 503 when Redis cannot
check or record the counters. If Redis is down, login is temporarily
unavailable rather than silently accepting unlimited attempts or returning a
normal bad-password response that was not recorded. Existing password-reset
rate limits and behavior are unchanged.

## Operational limitation

The counters use fixed windows and an account-plus-IP bucket. Distributed
attempts against one account from many IP addresses are bounded by the shared
per-IP limit for each source, but there is no global per-account lockout (which
would enable account-denial attacks). Redis availability is required for login
while this fail-closed policy is enabled.
