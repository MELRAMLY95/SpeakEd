from payments.base import PaymentError, PaymentProvider
from payments.fake import FakePaymentProvider
from payments.stripe_provider import StripePaymentProvider


def get_provider() -> PaymentProvider:
    from flask import current_app

    name = (current_app.config.get("PAYMENT_PROVIDER") or "fake").strip().lower()
    if name == "stripe":
        return StripePaymentProvider()
    return FakePaymentProvider()
