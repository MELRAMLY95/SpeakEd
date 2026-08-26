"""In-process sandbox provider. No network, no real charges."""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta, timezone
from flask import current_app, url_for

from payments.base import PaymentError, PaymentProvider


def _secret() -> str:
    return (current_app.config.get("PAYMENT_WEBHOOK_SECRET") or current_app.config.get("STRIPE_WEBHOOK_SECRET") or "").strip()


class FakePaymentProvider(PaymentProvider):
    name = "fake"

    def create_checkout(self, *, user_id: int, email: str, success_url: str, cancel_url: str) -> str:
        token = secrets.token_urlsafe(24)
        current_app.config.setdefault("_FAKE_CHECKOUTS", {})[token] = {
            "user_id": int(user_id),
            "email": email,
            "success_url": success_url,
            "cancel_url": cancel_url,
        }
        return url_for("billing.fake_checkout", token=token)

    def create_portal(self, *, user_id: int, customer_id: str, return_url: str) -> str:
        return url_for("billing.manage")

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        secret = _secret()
        if not secret:
            raise PaymentError("Webhook secret is not configured.")
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        provided = (signature or "").replace("sha256=", "").strip()
        if not provided or not hmac.compare_digest(expected, provided):
            raise PaymentError("Invalid webhook signature.")
        try:
            event = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PaymentError("Invalid webhook payload.") from exc
        if not isinstance(event, dict) or not event.get("id") or not event.get("type"):
            raise PaymentError("Webhook event is missing id or type.")
        return event

    def cancel_subscription(self, *, subscription_id: str) -> None:
        return None

    def sign(self, event: dict) -> tuple[bytes, str]:
        payload = json.dumps(event, separators=(",", ":")).encode("utf-8")
        secret = _secret()
        signature = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
        return payload, f"sha256={signature}"


def fake_checkout_event(user_id: int, *, status: str = "active") -> dict:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=30)
    event_id = f"evt_fake_{secrets.token_hex(8)}"
    sub_id = f"sub_fake_{user_id}"
    customer_id = f"cus_fake_{user_id}"
    if status == "payment_failed":
        return {
            "id": event_id,
            "type": "invoice.payment_failed",
            "data": {
                "user_id": user_id,
                "customer_id": customer_id,
                "subscription_id": sub_id,
                "status": "payment_failed",
                "plan": "premium",
                "current_period_start": now.isoformat(),
                "current_period_end": end.isoformat(),
            },
        }
    return {
        "id": event_id,
        "type": "checkout.session.completed",
        "data": {
            "user_id": user_id,
            "customer_id": customer_id,
            "subscription_id": sub_id,
            "status": status,
            "plan": "premium",
            "current_period_start": now.isoformat(),
            "current_period_end": end.isoformat(),
        },
    }


def fake_query(token: str) -> str:
    return urlencode({"token": token})
