"""Request-level security helpers: CSRF, redirects, rate limits, headers, redaction."""

from __future__ import annotations

import hmac
import ipaddress
import re
import secrets
import threading
import time
from urllib.parse import urlparse

from flask import abort, current_app, g, jsonify, request, session

_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "TRACE"})
_AUTH_FAILURES: dict[str, list[float]] = {}
_RATE_EVENTS: dict[str, list[float]] = {}
_AUTH_LOCK = threading.Lock()
_RATE_LOCK = threading.Lock()

_SECRET_PATTERNS = (
    (re.compile(r"postgres(?:ql)?://[^:\s/]+:[^@\s/]+@", re.I), "postgresql://***:***@"),
    (re.compile(r"(api[_-]?key\s*[=:]\s*)([^\s&\"']+)", re.I), r"\1[REDACTED]"),
    (re.compile(r"(key=)([^&\s\"']+)", re.I), r"\1[REDACTED]"),
    (re.compile(r"(Bearer\s+)\S+", re.I), r"\1[REDACTED]"),
    (re.compile(r"AIza[0-9A-Za-z\-_]{10,}"), "[REDACTED]"),
    (re.compile(r"sk-[A-Za-z0-9]{10,}"), "[REDACTED]"),
    (re.compile(r"whsec_[A-Za-z0-9]+"), "[REDACTED]"),
    (re.compile(r"(Stripe-Signature:\s*)\S+", re.I), r"\1[REDACTED]"),
)


def apply_production_security(app) -> None:
    """HTTPS cookies and proxy headers for hosted deployments (Render)."""
    if not app.config.get("IS_PRODUCTION"):
        return
    app.config["SESSION_COOKIE_SECURE"] = True
    app.config["PREFERRED_URL_SCHEME"] = "https"
    app.config["DEBUG"] = False
    app.config["TESTING"] = False
    from werkzeug.middleware.proxy_fix import ProxyFix

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)


def csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf_token"] = token
    return token


def _submitted_csrf_token() -> str:
    header = request.headers.get("X-CSRF-Token") or request.headers.get("X-CSRFToken") or ""
    if header:
        return header
    form_token = request.form.get("csrf_token")
    if form_token:
        return form_token
    payload = request.get_json(silent=True) or {}
    if isinstance(payload, dict):
        return str(payload.get("csrf_token") or "")
    return ""


def _wants_json_csrf_error() -> bool:
    if request.is_json:
        return True
    path = request.path or ""
    if path.endswith("/turn") or path.endswith("/refresh-images"):
        return True
    return (request.accept_mimetypes.best or "") == "application/json"


def csrf_protect() -> object | None:
    if not current_app.config.get("CSRF_PROTECT", True):
        return None
    if request.method in _SAFE_METHODS:
        return None
    if request.endpoint in {"static", "billing.webhook"}:
        return None
    expected = session.get("_csrf_token")
    submitted = _submitted_csrf_token()
    if (
        not expected
        or not submitted
        or not hmac.compare_digest(str(submitted), str(expected))
    ):
        if _wants_json_csrf_error():
            return (
                jsonify(
                    {
                        "error": "Your session expired. Refresh the page and try again.",
                        "code": "csrf",
                        "retry": True,
                    }
                ),
                400,
            )
        abort(400)
    return None


def safe_next_path(target: str | None, fallback: str = "/dashboard") -> str:
    """Allow only same-origin relative paths. Blocks //evil.com open redirects."""
    if not target:
        return fallback
    value = target.strip()
    if not value or "\\" in value or "\n" in value or "\r" in value or "\0" in value:
        return fallback
    if not value.startswith("/") or value.startswith("//"):
        return fallback
    parsed = urlparse(value)
    if parsed.scheme or parsed.netloc:
        return fallback
    return value


def client_ip() -> str:
    return (request.remote_addr or "unknown").strip() or "unknown"


def reset_auth_failures() -> None:
    with _AUTH_LOCK:
        _AUTH_FAILURES.clear()


def auth_is_rate_limited(kind: str) -> bool:
    if not current_app.config.get("LOGIN_RATE_LIMIT", True):
        return False
    max_fails = int(current_app.config.get("LOGIN_RATE_MAX") or 8)
    window = float(current_app.config.get("LOGIN_RATE_WINDOW") or 900)
    key = f"{kind}:{client_ip()}"
    now = time.monotonic()
    with _AUTH_LOCK:
        stamps = [stamp for stamp in _AUTH_FAILURES.get(key, []) if now - stamp < window]
        _AUTH_FAILURES[key] = stamps
        return len(stamps) >= max_fails


def record_auth_failure(kind: str) -> None:
    if not current_app.config.get("LOGIN_RATE_LIMIT", True):
        return
    key = f"{kind}:{client_ip()}"
    with _AUTH_LOCK:
        _AUTH_FAILURES.setdefault(key, []).append(time.monotonic())


def clear_auth_failures(kind: str) -> None:
    key = f"{kind}:{client_ip()}"
    with _AUTH_LOCK:
        _AUTH_FAILURES.pop(key, None)


def redact_secrets(text: str | None) -> str:
    value = str(text or "")
    for pattern, replacement in _SECRET_PATTERNS:
        value = pattern.sub(replacement, value)
    return value


def public_error_message(fallback: str = "Something went wrong. Please try again.") -> str:
    return fallback


def apply_security_headers(response):
    ads_script = bool(getattr(g, "allow_ad_script", False))
    script_src = ["'self'"]
    img_src = ["'self'", "data:", "blob:", "https://picsum.photos", "https://i.picsum.photos"]
    connect_src = ["'self'"]
    frame_src = []
    if ads_script:
        script_src.extend(
            [
                "https://pagead2.googlesyndication.com",
                "https://googleads.g.doubleclick.net",
                "https://www.googletagservices.com",
            ]
        )
        img_src.extend(
            [
                "https://pagead2.googlesyndication.com",
                "https://googleads.g.doubleclick.net",
                "https://tpc.googlesyndication.com",
                "https://www.google.com",
                "https://ep1.adtrafficquality.google",
            ]
        )
        connect_src.extend(
            [
                "https://pagead2.googlesyndication.com",
                "https://googleads.g.doubleclick.net",
                "https://ep1.adtrafficquality.google",
            ]
        )
        frame_src.extend(
            [
                "https://googleads.g.doubleclick.net",
                "https://tpc.googlesyndication.com",
                "https://www.google.com",
            ]
        )
    directives = [
        "default-src 'self'",
        "script-src " + " ".join(script_src),
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
        "font-src 'self' https://fonts.gstatic.com",
        "img-src " + " ".join(img_src),
        "connect-src " + " ".join(connect_src),
        "media-src 'self' blob:",
        "worker-src 'self' blob:",
        "object-src 'none'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
    ]
    if frame_src:
        directives.append("frame-src " + " ".join(frame_src))
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(self), payment=()",
    )
    response.headers.setdefault("Content-Security-Policy", "; ".join(directives))
    if current_app.config.get("IS_PRODUCTION"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response


def reset_action_rates() -> None:
    with _RATE_LOCK:
        _RATE_EVENTS.clear()


def consume_rate(kind: str, identity: str, max_events: int, window: float) -> bool:
    """Record an event and return True when the caller should be blocked."""
    if not current_app.config.get("ACTION_RATE_LIMIT", True):
        return False
    key = f"{kind}:{identity}"
    now = time.monotonic()
    with _RATE_LOCK:
        stamps = [stamp for stamp in _RATE_EVENTS.get(key, []) if now - stamp < window]
        if len(stamps) >= max_events:
            _RATE_EVENTS[key] = stamps
            return True
        stamps.append(now)
        _RATE_EVENTS[key] = stamps
        return False


def host_is_blocked(host: str) -> bool:
    name = (host or "").strip().strip("[]").lower()
    if not name or name in {"localhost", "metadata.google.internal"}:
        return True
    if name.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(name)
    except ValueError:
        return False
    return bool(
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )
