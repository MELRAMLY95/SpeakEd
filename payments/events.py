"""Turn provider webhook payloads into SpeakEd subscription updates."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from subscriptions import apply_subscription_state, get_subscription


def _iso(value) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(int(value), timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _user_id_from(obj: dict) -> int | None:
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    raw = obj.get("user_id") or obj.get("client_reference_id") or metadata.get("user_id")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _map_status(raw: str | None, event_type: str) -> str:
    if event_type in {"invoice.payment_failed", "invoice.payment_action_required"}:
        return "payment_failed"
    if event_type in {"customer.subscription.deleted"}:
        return "canceled"
    value = (raw or "").strip().lower()
    mapping = {
        "active": "active",
        "trialing": "trialing",
        "past_due": "past_due",
        "canceled": "canceled",
        "cancelled": "canceled",
        "unpaid": "payment_failed",
        "incomplete": "payment_failed",
        "incomplete_expired": "expired",
        "paused": "past_due",
        "payment_failed": "payment_failed",
        "expired": "expired",
        "free": "free",
    }
    return mapping.get(value, "free")


def apply_provider_event(provider: str, event: dict) -> bool:
    """Apply a verified event. Returns False when the event is ignored."""
    event_type = str(event.get("type") or "")
    data = event.get("data") if isinstance(event.get("data"), dict) else {}
    obj = data.get("object") if isinstance(data.get("object"), dict) else data
    if not isinstance(obj, dict):
        return False

    user_id = _user_id_from(obj)
    customer_id = obj.get("customer") or obj.get("customer_id")
    if isinstance(customer_id, dict):
        customer_id = customer_id.get("id")
    subscription_id = obj.get("subscription") or obj.get("subscription_id") or obj.get("id")
    if isinstance(subscription_id, dict):
        subscription_id = subscription_id.get("id")
    if event_type.startswith("checkout.") and not str(subscription_id or "").startswith("sub"):
        subscription_id = obj.get("subscription")

    if user_id is None and customer_id:
        row = get_subscription_by_customer(str(customer_id))
        if row is not None:
            user_id = int(row["user_id"])
    if user_id is None:
        return False

    status = _map_status(obj.get("status"), event_type)
    if event_type == "checkout.session.completed":
        status = "active"
    start = _iso(obj.get("current_period_start"))
    end = _iso(obj.get("current_period_end"))
    if event_type == "checkout.session.completed" and not end:
        now = datetime.now(timezone.utc)
        start = start or now.isoformat()
        end = (now + timedelta(days=30)).isoformat()

    apply_subscription_state(
        user_id,
        provider=provider,
        provider_customer_id=str(customer_id) if customer_id else None,
        provider_subscription_id=str(subscription_id) if subscription_id else None,
        plan="premium" if status in {"active", "trialing"} else "free",
        status=status,
        current_period_start=start,
        current_period_end=end,
    )
    return True


def get_subscription_by_customer(customer_id: str):
    from database.database import query_one

    return query_one(
        "SELECT * FROM subscriptions WHERE provider_customer_id = ?",
        (customer_id,),
    )
