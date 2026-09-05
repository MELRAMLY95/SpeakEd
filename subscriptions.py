"""Server-side subscription and usage service. Never reads plan status from the client."""

from __future__ import annotations

from datetime import datetime, timezone

from flask import current_app, has_app_context

from database.database import execute, query_one
from plans import INFO_GEN, PRACTICE_EXAM, PREMIUM_FEATURES, RETRY_MARKING, UNLIMITED, plan_for

PREMIUM_LIVE_STATUSES = frozenset({"active", "trialing"})
# Operator account is never capped by Free monthly usage, even without a Stripe subscription.
OPERATOR_EMAILS = frozenset({"malak@owner.com"})
KNOWN_STATUSES = frozenset(
    {"free", "active", "trialing", "past_due", "canceled", "expired", "payment_failed"}
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().isoformat()


def current_period() -> str:
    """UTC calendar month, e.g. 2026-08. Avoids local-midnight boundary bugs."""
    return _now().strftime("%Y-%m")


def _user_id(user) -> int | None:
    if not user:
        return None
    try:
        return int(user["id"])
    except (KeyError, TypeError, ValueError):
        return None


def _parse_end(value: str | None) -> datetime | None:
    raw = (value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def get_subscription(user_id: int):
    return query_one("SELECT * FROM subscriptions WHERE user_id = ?", (user_id,))


def _row_grants_premium(row) -> bool:
    if not row:
        return False
    status = (row["status"] or "free").strip().lower()
    end = _parse_end(row["current_period_end"])
    if status in PREMIUM_LIVE_STATUSES:
        if end is not None and end <= _now():
            return False
        return True
    if status == "canceled" and end is not None and end > _now():
        return True
    return False


def _user_email(user) -> str:
    if not user:
        return ""
    try:
        return str(user["email"] or "").strip().lower()
    except (KeyError, TypeError):
        return ""


def is_owner(user) -> bool:
    """True for the configured operator account. Not based on request flags."""
    email = _user_email(user)
    if not email:
        return False
    if email in OPERATOR_EMAILS:
        return True
    configured = ""
    if has_app_context():
        configured = (current_app.config.get("OWNER_EMAIL") or "").strip().lower()
    return bool(configured) and email == configured


def is_premium(user) -> bool:
    """True when the operator account or the subscriptions table grants access."""
    if is_owner(user):
        return True
    user_id = _user_id(user)
    if user_id is None:
        return False
    return _row_grants_premium(get_subscription(user_id))


def can_use_feature(user, feature: str) -> bool:
    name = (feature or "").strip().lower()
    if name in {"practice", "exam", "progress", "ads"}:
        return True
    if name in PREMIUM_FEATURES or name in {"unlimited_practice", "no_ads"}:
        return is_premium(user)
    return False


def get_usage_limit(user, feature: str) -> int | None:
    plan = plan_for(is_premium(user))
    limit = plan["limits"].get(feature)
    if limit is None:
        return 0
    if int(limit) == UNLIMITED:
        return None
    return max(0, int(limit))


def usage_count(user, feature: str) -> int:
    user_id = _user_id(user)
    if user_id is None:
        return 0
    row = query_one(
        "SELECT count FROM usage_counters WHERE user_id = ? AND feature = ? AND period = ?",
        (user_id, feature, current_period()),
    )
    if not row:
        return 0
    return int(row["count"] or 0)


def consume_usage(user, feature: str) -> bool:
    """Increment this month's counter. False means the user is at their plan limit."""
    user_id = _user_id(user)
    if user_id is None:
        return False
    limit = get_usage_limit(user, feature)
    if limit is None:
        return True
    period = current_period()
    row = query_one(
        "SELECT id, count FROM usage_counters WHERE user_id = ? AND feature = ? AND period = ?",
        (user_id, feature, period),
    )
    if row is None:
        execute(
            "INSERT INTO usage_counters (user_id, feature, period, count) VALUES (?, ?, ?, 1)",
            (user_id, feature, period),
        )
        return True
    if int(row["count"] or 0) >= limit:
        return False
    execute("UPDATE usage_counters SET count = count + 1 WHERE id = ?", (row["id"],))
    return True


def remaining_usage(user, feature: str) -> int | None:
    limit = get_usage_limit(user, feature)
    if limit is None:
        return None
    return max(0, limit - usage_count(user, feature))


def record_webhook_event(provider: str, event_id: str, event_type: str) -> bool:
    """Return True if this event should be applied. False means a duplicate."""
    if not event_id:
        return False
    existing = query_one(
        "SELECT id, processed FROM webhook_events WHERE provider = ? AND event_id = ?",
        (provider, event_id),
    )
    if existing is not None:
        return int(existing["processed"] or 0) == 0
    try:
        execute(
            """INSERT INTO webhook_events (provider, event_id, event_type, processed, created_at)
               VALUES (?, ?, ?, 0, ?)""",
            (provider, event_id, event_type, _now_iso()),
        )
        return True
    except Exception:
        again = query_one(
            "SELECT processed FROM webhook_events WHERE provider = ? AND event_id = ?",
            (provider, event_id),
        )
        if again is not None:
            return int(again["processed"] or 0) == 0
        raise


def mark_webhook_processed(provider: str, event_id: str) -> None:
    execute(
        "UPDATE webhook_events SET processed = 1 WHERE provider = ? AND event_id = ?",
        (provider, event_id),
    )


def apply_subscription_state(
    user_id: int,
    *,
    provider: str,
    provider_customer_id: str | None,
    provider_subscription_id: str | None,
    plan: str,
    status: str,
    current_period_start: str | None,
    current_period_end: str | None,
) -> None:
    """Upsert the user's subscription. Does not create extra rows for the same user."""
    status = (status or "free").strip().lower()
    if status not in KNOWN_STATUSES:
        status = "free"
    plan = "premium" if plan == "premium" else "free"
    if status in {"expired", "payment_failed", "past_due", "free"}:
        plan = "free" if status != "past_due" else plan
    if status in PREMIUM_LIVE_STATUSES:
        plan = "premium"
    if status == "canceled":
        plan = "premium" if _parse_end(current_period_end) and _parse_end(current_period_end) > _now() else "free"

    stamp = _now_iso()
    existing = get_subscription(user_id)
    if existing is None:
        execute(
            """INSERT INTO subscriptions (
                   user_id, provider, provider_customer_id, provider_subscription_id,
                   plan, status, current_period_start, current_period_end, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user_id,
                provider,
                provider_customer_id,
                provider_subscription_id,
                plan,
                status,
                current_period_start,
                current_period_end,
                stamp,
                stamp,
            ),
        )
    else:
        execute(
            """UPDATE subscriptions SET
                   provider = ?, provider_customer_id = COALESCE(?, provider_customer_id),
                   provider_subscription_id = COALESCE(?, provider_subscription_id),
                   plan = ?, status = ?, current_period_start = ?, current_period_end = ?,
                   updated_at = ?
               WHERE user_id = ?""",
            (
                provider,
                provider_customer_id,
                provider_subscription_id,
                plan,
                status,
                current_period_start,
                current_period_end,
                stamp,
                user_id,
            ),
        )
    premium_flag = 1 if is_premium({"id": user_id}) else 0
    execute("UPDATE users SET is_premium = ? WHERE id = ?", (premium_flag, user_id))


def activate_test_subscription(user_id: int, *, status: str = "active", days: int = 30) -> None:
    """Test helper: grant or expire Premium without touching payment credentials."""
    start = _now()
    if status == "expired" or days < 0:
        end = start.replace(year=start.year - 1) if days < 0 else start
        apply_status = "expired" if status == "expired" else status
        apply_subscription_state(
            user_id,
            provider="fake",
            provider_customer_id="cus_test",
            provider_subscription_id=f"sub_test_{user_id}",
            plan="premium",
            status=apply_status,
            current_period_start=start.isoformat(),
            current_period_end=end.isoformat(),
        )
        return
    from datetime import timedelta

    end = start + timedelta(days=days)
    apply_subscription_state(
        user_id,
        provider="fake",
        provider_customer_id="cus_test",
        provider_subscription_id=f"sub_test_{user_id}",
        plan="premium",
        status=status,
        current_period_start=start.isoformat(),
        current_period_end=end.isoformat(),
    )


def usage_snapshot(user) -> dict:
    premium = is_premium(user)
    plan = plan_for(premium)
    user_id = _user_id(user)
    row = get_subscription(user_id) if user_id is not None else None
    sub = dict(row) if row is not None else None
    features = (PRACTICE_EXAM, RETRY_MARKING, INFO_GEN)
    usage = {}
    for feature in features:
        limit = get_usage_limit(user, feature)
        usage[feature] = {
            "used": usage_count(user, feature),
            "limit": limit,
            "remaining": remaining_usage(user, feature),
        }
    return {
        "premium": premium,
        "plan": plan,
        "status": (sub or {}).get("status") or "free",
        "subscription": sub,
        "usage": usage,
    }
