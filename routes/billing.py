"""Subscription checkout, portal, and verified webhooks."""

from __future__ import annotations

import logging

from flask import abort, current_app, flash, g, redirect, render_template, request, url_for

from payments import get_provider
from payments.base import PaymentError
from payments.events import apply_provider_event
from payments.fake import FakePaymentProvider, fake_checkout_event
from plans import PRACTICE_EXAM, format_price, free_plan, premium_plan
from routes import billing_bp
from routes.auth import login_required
from security import redact_secrets
from subscriptions import (
    apply_subscription_state,
    get_subscription,
    is_premium,
    mark_webhook_processed,
    record_webhook_event,
    usage_snapshot,
)

logger = logging.getLogger(__name__)


@billing_bp.route("/pricing")
def pricing():
    snapshot = usage_snapshot(g.get("user")) if g.get("user") else {
        "premium": False,
        "plan": free_plan(),
        "status": "free",
        "subscription": None,
        "usage": {},
    }
    premium = premium_plan()
    free = free_plan()
    return render_template(
        "billing/pricing.html",
        snapshot=snapshot,
        free_plan=free,
        premium_plan=premium,
        premium_price=format_price(premium["price_amount"], premium["currency"], premium["interval"]),
        practice_feature=PRACTICE_EXAM,
    )


@billing_bp.route("/billing")
@login_required
def manage():
    snapshot = usage_snapshot(g.user)
    premium = premium_plan()
    return render_template(
        "billing/manage.html",
        snapshot=snapshot,
        premium_price=format_price(premium["price_amount"], premium["currency"], premium["interval"]),
    )


@billing_bp.route("/billing/checkout", methods=["POST"])
@login_required
def checkout():
    if is_premium(g.user):
        flash("Your Premium plan is already active.", "info")
        return redirect(url_for("billing.manage"))
    provider = get_provider()
    success = url_for("billing.success", _external=True)
    cancel = url_for("billing.pricing", _external=True)
    try:
        url = provider.create_checkout(
            user_id=int(g.user["id"]),
            email=g.user["email"],
            success_url=success,
            cancel_url=cancel,
        )
    except PaymentError as exc:
        logger.warning("Checkout could not start: %s", redact_secrets(exc))
        flash("Checkout is not available right now. Please try again later.", "error")
        return redirect(url_for("billing.pricing"))
    return redirect(url)


@billing_bp.route("/billing/success")
@login_required
def success():
    snapshot = usage_snapshot(g.user)
    return render_template("billing/success.html", snapshot=snapshot)


@billing_bp.route("/billing/portal", methods=["POST"])
@login_required
def portal():
    row = get_subscription(g.user["id"])
    if row is None or not row["provider_customer_id"]:
        flash("There is no billing account to manage yet.", "error")
        return redirect(url_for("billing.manage"))
    provider = get_provider()
    try:
        url = provider.create_portal(
            user_id=int(g.user["id"]),
            customer_id=row["provider_customer_id"],
            return_url=url_for("billing.manage", _external=True),
        )
    except PaymentError as exc:
        logger.warning("Billing portal could not start: %s", redact_secrets(exc))
        flash("The billing portal is not available right now.", "error")
        return redirect(url_for("billing.manage"))
    return redirect(url)


@billing_bp.route("/billing/cancel", methods=["POST"])
@login_required
def cancel():
    row = get_subscription(g.user["id"])
    if row is None:
        flash("You do not have a paid subscription to cancel.", "info")
        return redirect(url_for("billing.manage"))
    provider = get_provider()
    sub_id = row["provider_subscription_id"]
    try:
        if sub_id:
            provider.cancel_subscription(subscription_id=sub_id)
    except PaymentError as exc:
        logger.warning("Cancel at provider failed: %s", redact_secrets(exc))
        flash("The payment provider could not cancel the subscription. Please try again.", "error")
        return redirect(url_for("billing.manage"))
    apply_subscription_state(
        int(g.user["id"]),
        provider=row["provider"] or provider.name,
        provider_customer_id=row["provider_customer_id"],
        provider_subscription_id=sub_id,
        plan="premium",
        status="canceled",
        current_period_start=row["current_period_start"],
        current_period_end=row["current_period_end"],
    )
    flash("Premium will remain available until the end of the current billing period. Your exam history is kept.", "info")
    return redirect(url_for("billing.manage"))


@billing_bp.route("/billing/fake-checkout/<token>", methods=["GET", "POST"])
@login_required
def fake_checkout(token):
    if (current_app.config.get("PAYMENT_PROVIDER") or "fake").strip().lower() != "fake":
        abort(404)
    sessions = current_app.config.get("_FAKE_CHECKOUTS") or {}
    session = sessions.get(token)
    if not session or int(session["user_id"]) != int(g.user["id"]):
        abort(404)
    if request.method == "GET":
        premium = premium_plan()
        return render_template(
            "billing/fake_checkout.html",
            token=token,
            premium_price=format_price(premium["price_amount"], premium["currency"], premium["interval"]),
        )
    outcome = (request.form.get("outcome") or "pay").strip().lower()
    provider = FakePaymentProvider()
    event = fake_checkout_event(
        int(g.user["id"]),
        status="payment_failed" if outcome == "fail" else "active",
    )
    payload, signature = provider.sign(event)
    try:
        verified = provider.verify_webhook(payload, signature)
        if record_webhook_event(provider.name, verified["id"], verified["type"]):
            apply_provider_event(provider.name, verified)
            mark_webhook_processed(provider.name, verified["id"])
    except PaymentError:
        flash("The sandbox payment could not be confirmed.", "error")
        return redirect(url_for("billing.pricing"))
    sessions.pop(token, None)
    if outcome == "fail":
        flash("The sandbox payment failed. You remain on the Free plan.", "error")
        return redirect(url_for("billing.pricing"))
    return redirect(url_for("billing.success"))


@billing_bp.route("/billing/webhook", methods=["POST"])
def webhook():
    provider = get_provider()
    payload = request.get_data()
    signature = request.headers.get("Stripe-Signature") or request.headers.get("X-SpeakEd-Signature")
    try:
        event = provider.verify_webhook(payload, signature)
    except PaymentError:
        logger.warning("Rejected a billing webhook with an invalid signature")
        return ("invalid signature", 400)
    event_id = str(event.get("id") or "")
    event_type = str(event.get("type") or "")
    if not record_webhook_event(provider.name, event_id, event_type):
        return ("", 200)
    try:
        apply_provider_event(provider.name, event)
        mark_webhook_processed(provider.name, event_id)
    except Exception:
        logger.exception("Billing webhook could not be applied for event type %s", event_type)
        return ("", 500)
    return ("", 200)
