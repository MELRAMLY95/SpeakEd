"""Payment provider interface. SpeakEd never stores card numbers or CVV."""


class PaymentError(Exception):
    pass


class PaymentProvider:
    name = "base"

    def create_checkout(self, *, user_id: int, email: str, success_url: str, cancel_url: str) -> str:
        raise NotImplementedError

    def create_portal(self, *, user_id: int, customer_id: str, return_url: str) -> str:
        raise NotImplementedError

    def verify_webhook(self, payload: bytes, signature: str | None) -> dict:
        raise NotImplementedError

    def cancel_subscription(self, *, subscription_id: str) -> None:
        raise NotImplementedError
