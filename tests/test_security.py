import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from flask import Flask

from app import create_app
from config import TestConfig
from security import apply_production_security, reset_auth_failures, safe_next_path
from tests.conftest import signup


def _csrf(client):
    client.get("/login")
    with client.session_transaction() as sess:
        return sess["_csrf_token"]


@pytest.fixture()
def csrf_app(tmp_path):
    class Locked(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'csrf.db'}"
        CSRF_PROTECT = True
        LOGIN_RATE_LIMIT = False

    return create_app(Locked)


@pytest.fixture()
def csrf_client(csrf_app):
    return csrf_app.test_client()


@pytest.fixture()
def rate_app(tmp_path):
    class Limited(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'rate.db'}"
        CSRF_PROTECT = False
        LOGIN_RATE_LIMIT = True
        LOGIN_RATE_MAX = 3
        LOGIN_RATE_WINDOW = 900

    application = create_app(Limited)
    reset_auth_failures()
    yield application
    reset_auth_failures()


@pytest.fixture()
def rate_client(rate_app):
    return rate_app.test_client()


def test_safe_next_path_blocks_open_redirects():
    assert safe_next_path("/progress") == "/progress"
    assert safe_next_path("/dashboard?tab=1") == "/dashboard?tab=1"
    assert safe_next_path("//evil.example") == "/dashboard"
    assert safe_next_path("https://evil.example") == "/dashboard"
    assert safe_next_path("/\\evil.example") == "/dashboard"
    assert safe_next_path("http://speaked.test") == "/dashboard"


def test_login_open_redirect_is_blocked(client):
    signup(client)
    client.get("/logout")
    response = client.post(
        "/login?next=//evil.example/phish",
        data={"email": "student@example.com", "password": "password12"},
        follow_redirects=False,
    )
    location = response.headers.get("Location") or ""
    assert "evil" not in location
    assert location.endswith("/dashboard")


def test_forgot_password_does_not_return_reset_token(client):
    signup(client)
    client.get("/logout")
    response = client.post("/forgot-password", data={"email": "student@example.com"})
    assert response.status_code == 200
    assert b"reset-password" not in response.data
    assert b"/reset-password/" not in response.data
    body = response.get_data(as_text=True)
    assert "token=" not in body.lower()


def test_password_reset_with_hashed_token_works(client, app):
    signup(client)
    client.get("/logout")
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    expires = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
    with app.app_context():
        from database.database import execute

        execute(
            "INSERT INTO password_resets (user_id, token_hash, expires_at, used) VALUES (?, ?, ?, 0)",
            (1, token_hash, expires),
        )
    update = client.post(
        f"/reset-password/{token}",
        data={"password": "newpass12", "confirm": "newpass12"},
        follow_redirects=True,
    )
    assert b"updated" in update.data.lower() or b"sign in" in update.data.lower()
    bad = client.post("/login", data={"email": "student@example.com", "password": "password12"})
    assert b"Incorrect" in bad.data
    ok = client.post(
        "/login",
        data={"email": "student@example.com", "password": "newpass12"},
        follow_redirects=True,
    )
    assert b"Welcome" in ok.data


def test_csrf_rejects_login_without_token(csrf_client):
    csrf_client.get("/login")
    response = csrf_client.post(
        "/login",
        data={"email": "student@example.com", "password": "password12"},
    )
    assert response.status_code == 400


def test_csrf_allows_login_with_token(csrf_client):
    token = _csrf(csrf_client)
    signup_token = token
    created = csrf_client.post(
        "/signup",
        data={
            "name": "Malak",
            "email": "csrf@example.com",
            "password": "password12",
            "confirm": "password12",
            "csrf_token": signup_token,
        },
        follow_redirects=True,
    )
    assert created.status_code == 200
    assert b"Welcome" in created.data


def test_login_rate_limit_returns_429(rate_client):
    signup(rate_client, "brute@example.com")
    rate_client.get("/logout")
    for _ in range(3):
        failed = rate_client.post(
            "/login",
            data={"email": "brute@example.com", "password": "wrongpass1"},
        )
        assert failed.status_code == 200
        assert b"Incorrect" in failed.data
    blocked = rate_client.post(
        "/login",
        data={"email": "brute@example.com", "password": "wrongpass1"},
    )
    assert blocked.status_code == 429
    assert b"Too many" in blocked.data


def test_sql_injection_in_login_does_not_authenticate(client):
    signup(client)
    client.get("/logout")
    response = client.post(
        "/login",
        data={"email": "student@example.com' OR 1=1 --", "password": "anything1"},
        follow_redirects=True,
    )
    assert b"Incorrect" in response.data
    assert client.get("/dashboard", follow_redirects=False).status_code == 302


def test_xss_in_transcript_is_escaped(client, app):
    signup(client)
    payload = "<script>alert('xss')</script>"
    with app.app_context():
        from database.database import execute

        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
               VALUES (1, 'roleplay', 'practice', 'completed', 'complete', '{}', '2026-01-01T00:00:00+00:00')"""
        )
        execute(
            """INSERT INTO transcripts (attempt_id, stage, turn_index, speaker, prompt_id, text, duration_ms, speech_metrics_json, created_at)
               VALUES (1, 'roleplay', 1, 'student', 'p1', ?, 1000, '{}', '2026-01-01T00:00:00+00:00')""",
            (payload,),
        )
    page = client.get("/history/1")
    assert page.status_code == 200
    assert b"<script>alert('xss')</script>" not in page.data
    assert b"&lt;script&gt;" in page.data


def test_idor_blocks_exam_results_and_evaluation(client, app):
    signup(client, "owner@example.com")
    with app.app_context():
        from database.database import execute, query_one

        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at, completed_at)
               VALUES (1, 'roleplay', 'practice', 'completed', 'complete', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00')"""
        )
        row = query_one("SELECT id FROM attempts")
        execute(
            "INSERT INTO gathered_info (user_id, topic, information, created_at, updated_at) VALUES (1, 'Owner topic', 'secret notes', '2026-01-01', '2026-01-01')"
        )
        info = query_one("SELECT id FROM gathered_info")
    attempt_id = row["id"]
    info_id = info["id"]
    client.get("/logout")
    signup(client, "intruder@example.com")
    assert client.get(f"/exam/{attempt_id}/results").status_code == 404
    assert client.get(f"/exam/{attempt_id}").status_code == 404
    assert client.get(f"/evaluation/{attempt_id}").status_code == 404
    assert client.get(f"/information/{info_id}").status_code == 404
    assert client.post(f"/information/{info_id}/delete").status_code == 404


def test_session_cookie_is_httponly_and_samesite(client):
    response = client.post(
        "/signup",
        data={
            "name": "Malak",
            "email": "cookie@example.com",
            "password": "password12",
            "confirm": "password12",
        },
        follow_redirects=False,
    )
    header = ";".join(response.headers.getlist("Set-Cookie")).lower()
    assert "httponly" in header
    assert "samesite=lax" in header


def test_audio_read_rejects_paths_outside_exam_audio(app, tmp_path):
    secret = tmp_path / "secret.webm"
    secret.write_bytes(b"\x00" * 400)
    with app.app_context():
        from ai.speech import read_audio_file

        data, mime = read_audio_file(str(secret))
        assert data is None
        assert mime is None


def test_apply_production_security_is_noop_outside_production():
    app = Flask(__name__)
    app.config["IS_PRODUCTION"] = False
    app.config["SESSION_COOKIE_SECURE"] = False
    apply_production_security(app)
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_security_headers_are_present(client):
    response = client.get("/")
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "SAMEORIGIN"
    assert "strict-origin-when-cross-origin" in (response.headers.get("Referrer-Policy") or "")
    csp = response.headers.get("Content-Security-Policy") or ""
    assert "script-src 'self'" in csp
    assert "object-src 'none'" in csp
    assert "microphone=(self)" in (response.headers.get("Permissions-Policy") or "")


def test_get_logout_does_not_clear_session_when_csrf_on(csrf_client):
    token = _csrf(csrf_client)
    csrf_client.post(
        "/signup",
        data={
            "name": "Malak",
            "email": "logout-csrf@example.com",
            "password": "password12",
            "confirm": "password12",
            "csrf_token": token,
        },
        follow_redirects=True,
    )
    csrf_client.get("/logout")
    dashboard = csrf_client.get("/dashboard", follow_redirects=False)
    assert dashboard.status_code == 200


def test_results_get_does_not_finish_an_active_exam(client, app, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    response = client.get("/exam/1/results", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/exam/1" in (response.headers.get("Location") or "")
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT status, stage FROM attempts WHERE id = 1")
        assert row["status"] == "in_progress"
        assert row["stage"] != "complete" or row["status"] == "in_progress"


def test_executable_disguised_as_audio_is_rejected(client, monkeypatch):
    import io
    import json

    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    audio = (io.BytesIO(b"MZ" + b"\x00" * 400), "turn.webm", "audio/webm")
    response = client.post(
        "/exam/1/turn",
        data={
            "transcript": "Hello",
            "metrics": json.dumps({"duration_ms": 2000}),
            "audio": audio,
        },
    )
    assert response.status_code == 400
    assert response.get_json()["code"] == "invalid_audio"


def test_redact_secrets_strips_keys_and_database_urls():
    from security import redact_secrets

    assert "[REDACTED]" in redact_secrets("Authorization: Bearer super-secret-token-value")
    assert "***" in redact_secrets("postgresql://user:hunter2@db.example/speaked")
    assert "hunter2" not in redact_secrets("postgresql://user:hunter2@db.example/speaked")


def test_retry_marking_is_rate_limited(tmp_path):
    class Limited(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'retry-rate.db'}"
        CSRF_PROTECT = False
        LOGIN_RATE_LIMIT = False
        ACTION_RATE_LIMIT = True
        RETRY_MARKING_MAX = 1
        RETRY_MARKING_WINDOW = 900

    from security import reset_action_rates

    reset_action_rates()
    application = create_app(Limited)
    client = application.test_client()
    signup(client)
    with application.app_context():
        from database.database import execute

        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at, completed_at)
               VALUES (1, 'roleplay', 'practice', 'marking_unavailable', 'complete', '{}', '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00')"""
        )
    first = client.post("/exam/1/retry-marking", follow_redirects=True)
    assert first.status_code == 200
    second = client.post("/exam/1/retry-marking", follow_redirects=True)
    assert b"wait before retrying" in second.data.lower()
    reset_action_rates()

