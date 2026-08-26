"""Central plan catalogue. Limits and prices come from configuration, not routes."""

from __future__ import annotations

from flask import current_app

PRACTICE_EXAM = "practice_exam"
RETRY_MARKING = "retry_marking"
INFO_GEN = "info_gen"

UNLIMITED = -1

PREMIUM_FEATURES = frozenset(
    {
        "no_ads",
        "unlimited_practice",
        "detailed_feedback",
        "audio_assessment",
        "advanced_progress",
    }
)

FREE_FEATURES = frozenset({"practice", "progress", "exam", "ads"})


def _int(name: str, default: int) -> int:
    raw = current_app.config.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def free_plan() -> dict:
    return {
        "id": "free",
        "name": current_app.config.get("FREE_PLAN_NAME") or "Free",
        "price_amount": 0,
        "currency": (current_app.config.get("PREMIUM_CURRENCY") or "gbp").lower(),
        "interval": "month",
        "limits": {
            PRACTICE_EXAM: _int("FREE_PRACTICE_EXAMS_PER_MONTH", 4),
            RETRY_MARKING: _int("FREE_RETRY_MARKING_PER_MONTH", 2),
            INFO_GEN: _int("FREE_INFO_GEN_PER_MONTH", 8),
        },
        "features": sorted(FREE_FEATURES),
    }


def premium_plan() -> dict:
    return {
        "id": "premium",
        "name": current_app.config.get("PREMIUM_PLAN_NAME") or "Premium",
        "price_amount": _int("PREMIUM_PRICE_AMOUNT", 499),
        "currency": (current_app.config.get("PREMIUM_CURRENCY") or "gbp").lower(),
        "interval": current_app.config.get("PREMIUM_INTERVAL") or "month",
        "limits": {
            PRACTICE_EXAM: _int("PREMIUM_PRACTICE_EXAMS_PER_MONTH", UNLIMITED),
            RETRY_MARKING: _int("PREMIUM_RETRY_MARKING_PER_MONTH", UNLIMITED),
            INFO_GEN: _int("PREMIUM_INFO_GEN_PER_MONTH", UNLIMITED),
        },
        "features": sorted(FREE_FEATURES | PREMIUM_FEATURES - {"ads"}),
    }


def plan_for(is_premium_user: bool) -> dict:
    return premium_plan() if is_premium_user else free_plan()


def format_price(amount: int, currency: str, interval: str) -> str:
    major = amount / 100
    symbol = {"gbp": "£", "usd": "$", "eur": "€"}.get((currency or "gbp").lower(), f"{currency} ")
    period = "month" if interval == "month" else interval
    if amount <= 0:
        return "£0"
    if major == int(major):
        return f"{symbol}{int(major)} / {period}"
    return f"{symbol}{major:.2f} / {period}"
