"""Server-side advertising policy. Visibility is never taken from the browser."""

from __future__ import annotations

import re

from flask import current_app, g, request, session

ALLOWED_SLOTS = frozenset({"home", "dashboard", "information", "privacy"})

_SLOT_PATHS = {
    "home": frozenset({"/"}),
    "dashboard": frozenset({"/dashboard"}),
    "information": frozenset({"/information"}),
    "privacy": frozenset({"/privacy"}),
}

_SLOT_CONFIG_KEYS = {
    "home": "AD_SLOT_HOME",
    "dashboard": "AD_SLOT_DASHBOARD",
    "information": "AD_SLOT_INFORMATION",
    "privacy": "AD_SLOT_PRIVACY",
}

BLOCKED_PREFIXES = (
    "/exam",
    "/practice",
    "/evaluation",
    "/progress",
    "/history",
    "/login",
    "/signup",
    "/account",
    "/forgot-password",
    "/reset-password",
    "/ads/",
    "/billing",
    "/pricing",
)

_CLIENT_RE = re.compile(r"^ca-pub-\d{10,20}$")
_SLOT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def _norm_path(path: str | None) -> str:
    value = (path or "/").split("?", 1)[0]
    if value != "/" and value.endswith("/"):
        return value.rstrip("/")
    return value or "/"


def ads_enabled() -> bool:
    return bool(current_app.config.get("ADS_ENABLED"))


def user_is_premium(user) -> bool:
    """Premium status comes only from the server-side subscription service."""
    from subscriptions import is_premium

    return is_premium(user)


def path_forbids_ads(path: str | None) -> bool:
    normalised = _norm_path(path)
    for prefix in BLOCKED_PREFIXES:
        if normalised == prefix or normalised.startswith(prefix + "/"):
            return True
    return False


def publisher_id() -> str:
    return (current_app.config.get("AD_CLIENT_ID") or "").strip()


def is_live_publisher(client_id: str | None = None) -> bool:
    value = (client_id if client_id is not None else publisher_id()).strip()
    return bool(_CLIENT_RE.fullmatch(value))


def safe_slot_id(value: str | None) -> str:
    raw = (value or "").strip()
    return raw if _SLOT_ID_RE.fullmatch(raw) else ""


def consent_choice() -> str:
    choice = session.get("ads_consent")
    return choice if choice in {"allow", "deny"} else ""


def ads_consent_required() -> bool:
    return bool(current_app.config.get("ADS_CONSENT_REQUIRED"))


def build_ad_slot(name: str) -> dict | None:
    """Return a render payload for one approved slot, or None to show nothing."""
    slot_name = (name or "").strip().lower()
    if slot_name not in ALLOWED_SLOTS:
        return None
    if not ads_enabled():
        return None
    if user_is_premium(g.get("user")):
        return None

    path = _norm_path(request.path)
    if path_forbids_ads(path):
        return None
    if path not in _SLOT_PATHS[slot_name]:
        return None

    if consent_choice() == "deny":
        return None

    needs_consent = ads_consent_required() and consent_choice() != "allow"
    config_key = _SLOT_CONFIG_KEYS[slot_name]
    slot_id = safe_slot_id(current_app.config.get(config_key))
    client = publisher_id()
    live = is_live_publisher(client) and not needs_consent and bool(slot_id)
    if live:
        g.allow_ad_script = True

    return {
        "name": slot_name,
        "slot_id": slot_id,
        "client_id": client if live else "",
        "live": live,
        "provider": (current_app.config.get("ADS_PROVIDER") or "adsense").strip().lower(),
        "needs_consent": needs_consent,
        "npa": True,
        "under_age_of_consent": True,
        "test_mode": bool(current_app.config.get("ADS_TEST_MODE", True)),
    }
