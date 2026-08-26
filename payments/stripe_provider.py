"""Stripe Checkout + webhooks. Card data never touches SpeakEd."""

from __future__ import annotations

from flask import current_app

from payments.base import PaymentError, PaymentProvider


def _secret_key() -> str:
    return (
        current_app.config.get("STRIPE_SECRET_KEY")
        or current_app.config.get("PAYMENT_SECRET_KEY")
        or ""
    ).strip()


def _webhook_secret() -> str:
    return (
        current_app.config.get("STRIPE_WEBHOOK_SECRET")
        or current_app.config.get("PAYMENT_WEBHOOK_SECRET")
        or ""
    ).strip()


class StripePaymentProvider(PaymentProvider):
    name = "stripe"

    def _stripe(self):
        try:
            import stripe
        except ImportError as exc:
            raise PaymentError("The stripe package is not installed.") from exc
        key = _secret_key()
        if not key or key.startswith("sk_live_") and current_app.config.get("PAYMENT_TEST_MODE", True):
            if key.startswith("sk_live_"):
                raise PaymentError("Live Stripe keys are blocked while PAYMENT_TEST_MODE is enabled.")
        if not key:
            raise PaymentError("STRIPE_SECRET_KEY is not configured.")
        stripe.api_key = key
        return stripe

    def create_checkout(self, *, user_id: int, email: str, success_url: str, cancel_url: str) -> str:
        stripe = self._stripe()
        price = (current_app.config.get("STRIPE_PRICE_ID") or "").strip()
        if not price:
            raise PaymentError("STRIPE_PRICE_ID is not configured.")
        session = stripe.checkout.Session.create(
            mode="subscription",
            success_url=success_url,
            cancel_url=cancel_url,
            customer_email=email or None,
            client_reference_id=str(user_id),
            metadata={"user_id": str(user_id)},
            line_items=[{"price": price, "quantity": 1}],
            subscription_data={"metadata": {"user_id": str(user_id)}},
        )
        if not session.url:
            raise PaymentError("Stripe did not return a checkout URL.")
        return session.url

    def create_portal(self, *, user_id: int, customer_id: str, return_url: str) -> str:
        stripe = self._stripe()
        if not customer_id:
            raise PaymentError("No Stripe customer is on file.")
        portal = stripe.billing_portal.Session.create(customer=customer_id, return_url=return_url)
        if not portal.url:
            raise PaymentError("Stripe did not return a billing portal URL.")
        return portal.url

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        stripe = self._stripe()
        secret = _webhook_secret()
        if not secret:
            raise PaymentError("STRIPE_WEBHOOK_SECRET is not configured.")
        if not signature:
            raise PaymentError("Missing webhook signature.")
        try:
            event = stripe.Webhook.construct_event(payload, signature, secret)
        except Exception as exc:
            raise PaymentError("Invalid webhook signature.") from exc
        return event if isinstance(event, dict) else dict(event)

    def cancel_subscription(self, *, subscription_id: str) -> None:
        stripe = self._stripe()
        stripe.Subscription.modify(subscription_id, cancel_at_period_end=True)
