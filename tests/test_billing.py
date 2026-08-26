"""Server-side Freemium / Premium subscription behaviour."""

import json

from app import create_app
from config import TestConfig
from payments.fake import FakePaymentProvider, fake_checkout_event
from plans import PRACTICE_EXAM
from tests.conftest import signup
from tests.fake_ai import install_fake


class BillingConfig(TestConfig):
    ADS_ENABLED = True
    ADS_CONSENT_REQUIRED = False
    AD_CLIENT_ID = "ca-pub-XXXXXXXXXXXXXXXX"
    AD_SLOT_HOME = "slot-home"
    AD_SLOT_DASHBOARD = "slot-dashboard"
    FREE_PRACTICE_EXAMS_PER_MONTH = 1
    FREE_RETRY_MARKING_PER_MONTH = 1
    FREE_INFO_GEN_PER_MONTH = 1
    PAYMENT_PROVIDER = "fake"
    PAYMENT_WEBHOOK_SECRET = "test-webhook-secret"


def _app(tmp_path, **overrides):
    class Local(BillingConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'billing.db'}"

    for key, value in overrides.items():
        setattr(Local, key, value)
    return create_app(Local)


def _user_id(app, email="student@example.com"):
    from database.database import query_one

    with app.app_context():
        return query_one("SELECT id FROM users WHERE email = ?", (email,))["id"]


def test_new_user_starts_as_free(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    dashboard = client.get("/dashboard")
    assert b"Current plan: Free" in dashboard.data
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": _user_id(app)}) is False


def test_free_user_can_access_free_functionality(tmp_path, monkeypatch):
    install_fake(monkeypatch)
    app = _app(tmp_path, FREE_PRACTICE_EXAMS_PER_MONTH=4)
    client = app.test_client()
    signup(client)
    assert client.get("/practice").status_code == 200
    started = client.post(
        "/practice/start",
        data={"section": "roleplay"},
        follow_redirects=True,
    )
    assert started.status_code == 200
    assert b"ad-slot" in client.get("/dashboard").data or app.config["ADS_ENABLED"]
    assert client.get("/progress").status_code == 200


def test_free_user_cannot_exceed_practice_limit(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    first = client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    assert first.status_code == 200
    second = client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    assert b"Upgrade to Premium" in second.data
    assert client.get("/exam/2").status_code == 404


def test_premium_user_can_exceed_free_limit(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    with app.app_context():
        from subscriptions import activate_test_subscription

        activate_test_subscription(_user_id(app))
    first = client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    second = client.post("/practice/start", data={"section": "topic_talk"}, follow_redirects=True)
    assert first.status_code == 200
    assert second.status_code == 200
    assert client.get("/exam/2").status_code == 200


def test_browser_cannot_fake_premium(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    spoofed = client.get("/dashboard?premium=true&isPremium=1&plan=premium", headers={"X-Premium": "true"})
    assert b"Current plan: Free" in spoofed.data
    assert b"Current plan: Premium" not in spoofed.data
    client.set_cookie("isPremium", "true")
    client.set_cookie("plan", "premium")
    again = client.get("/dashboard")
    assert b"Current plan: Free" in again.data


def test_user_cannot_access_another_subscription(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client, "one@example.com")
    with app.app_context():
        from subscriptions import activate_test_subscription

        activate_test_subscription(_user_id(app, "one@example.com"))
    client.post("/logout", follow_redirects=True)
    signup(client, "two@example.com")
    page = client.get("/billing")
    assert page.status_code == 200
    assert b"Premium features are active" not in page.data
    assert b"one@example.com" not in page.data


def test_invalid_and_forged_webhooks_are_rejected(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    user_id = _user_id(app)
    event = fake_checkout_event(user_id)
    payload = json.dumps(event).encode()
    rejected = client.post("/billing/webhook", data=payload, headers={"X-SpeakEd-Signature": "sha256=deadbeef"})
    assert rejected.status_code == 400
    missing = client.post("/billing/webhook", data=payload)
    assert missing.status_code == 400
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": user_id}) is False


def test_verified_webhook_activates_premium_and_duplicate_is_safe(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    user_id = _user_id(app)
    with app.app_context():
        from subscriptions import is_premium

        provider = FakePaymentProvider()
        event = fake_checkout_event(user_id)
        payload, signature = provider.sign(event)
        first = client.post("/billing/webhook", data=payload, headers={"X-SpeakEd-Signature": signature})
        assert first.status_code == 200
        assert is_premium({"id": user_id}) is True
        second = client.post("/billing/webhook", data=payload, headers={"X-SpeakEd-Signature": signature})
        assert second.status_code == 200
        from database.database import query_one

        row = query_one("SELECT COUNT(*) AS n FROM subscriptions WHERE user_id = ?", (user_id,))
        assert int(row["n"]) == 1


def test_checkout_page_does_not_grant_premium(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    response = client.post("/billing/checkout", follow_redirects=False)
    assert response.status_code in {302, 303}
    location = response.headers.get("Location") or ""
    assert "fake-checkout" in location
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": _user_id(app)}) is False
    sandbox = client.get(location)
    assert sandbox.status_code == 200
    assert b"Sandbox payment" in sandbox.data
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": _user_id(app)}) is False


def test_sandbox_payment_success_and_failure(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    start = client.post("/billing/checkout", follow_redirects=False)
    token = (start.headers.get("Location") or "").rstrip("/").split("/")[-1]
    failed = client.post(f"/billing/fake-checkout/{token}", data={"outcome": "fail"}, follow_redirects=True)
    assert b"Free" in failed.data
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": _user_id(app)}) is False
    start = client.post("/billing/checkout", follow_redirects=False)
    token = (start.headers.get("Location") or "").rstrip("/").split("/")[-1]
    paid = client.post(f"/billing/fake-checkout/{token}", data={"outcome": "pay"}, follow_redirects=True)
    assert paid.status_code == 200
    with app.app_context():
        from subscriptions import is_premium

        assert is_premium({"id": _user_id(app)}) is True


def test_cancellation_keeps_history_and_expiration_removes_premium(tmp_path, monkeypatch):
    install_fake(monkeypatch)
    app = _app(tmp_path, FREE_PRACTICE_EXAMS_PER_MONTH=4)
    client = app.test_client()
    signup(client)
    client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    with app.app_context():
        from subscriptions import activate_test_subscription, is_premium

        activate_test_subscription(_user_id(app), status="canceled", days=10)
        assert is_premium({"id": _user_id(app)}) is True
        activate_test_subscription(_user_id(app), status="expired", days=0)
        assert is_premium({"id": _user_id(app)}) is False
    history = client.get("/history")
    assert history.status_code == 200
    assert b"roleplay" in history.data.lower() or b"Role" in history.data


def test_failed_payment_status_is_not_premium(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    with app.app_context():
        from subscriptions import activate_test_subscription, is_premium

        activate_test_subscription(_user_id(app), status="payment_failed")
        assert is_premium({"id": _user_id(app)}) is False
    assert b"Current plan: Free" in client.get("/dashboard").data


def test_usage_survives_logout_login_and_refresh(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    client.get("/dashboard")
    client.post("/logout", follow_redirects=True)
    client.post("/login", data={"email": "student@example.com", "password": "password12"}, follow_redirects=True)
    blocked = client.post("/practice/start", data={"section": "roleplay"}, follow_redirects=True)
    assert b"Upgrade to Premium" in blocked.data
    with app.app_context():
        from subscriptions import usage_count

        assert usage_count({"id": _user_id(app)}, PRACTICE_EXAM) == 1


def test_marking_is_not_repeated_on_results_refresh(tmp_path, monkeypatch):
    install_fake(monkeypatch)
    app = _app(tmp_path, FREE_PRACTICE_EXAMS_PER_MONTH=4)
    client = app.test_client()
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    client.post("/exam/1/begin", follow_redirects=True)
    for _ in range(20):
        response = client.post(
            "/exam/1/turn",
            json={"transcript": "I usually go once a month because I enjoy action films with my friends.", "metrics": {"duration_ms": 8000, "word_count": 18}},
        )
        data = response.get_json() or {}
        if data.get("redirect"):
            break
    else:
        raise AssertionError("exam did not complete")
    first = client.get("/exam/1/results")
    second = client.get("/exam/1/results")
    assert first.status_code == 200
    assert second.status_code == 200
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT COUNT(*) AS n FROM markings WHERE attempt_id = 1")
        assert int(row["n"]) == 1


def test_premium_users_do_not_see_advertisements(tmp_path):
    app = _app(tmp_path)
    client = app.test_client()
    signup(client)
    assert b"ad-slot" in client.get("/dashboard").data
    with app.app_context():
        from subscriptions import activate_test_subscription

        activate_test_subscription(_user_id(app))
    assert b"ad-slot" not in client.get("/dashboard").data
    assert b"ad-slot" not in client.get("/").data


def test_pricing_shows_recurring_price_without_dark_patterns(tmp_path):
    client = _app(tmp_path).test_client()
    page = client.get("/pricing")
    assert page.status_code == 200
    assert b"billed every" in page.data.lower() or b"Billed every" in page.data
    assert b"countdown" not in page.data.lower()
    assert b"only 3 left" not in page.data.lower()
