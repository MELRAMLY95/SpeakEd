"""End-to-end tests against a REAL PostgreSQL server.

Skipped unless SPEAKED_TEST_PG points at a throwaway PostgreSQL server. Each
test runs in its own freshly created database and drops it afterwards. This is
the production code path: real psycopg2, real PostgreSQL SQL semantics, real
types, real transactions.
"""

import json
import os

import pytest

from app import create_app
from config import TestConfig
from database.database import engine_kind, execute, query_all, query_one
from tests import pg_real

pytestmark = pytest.mark.skipif(
    not pg_real.available(),
    reason="set SPEAKED_TEST_PG to a throwaway PostgreSQL DSN to run real PostgreSQL tests",
)

PASSWORD = "password12"


@pytest.fixture()
def pg_url():
    name, dsn = pg_real.create_database()
    try:
        yield dsn
    finally:
        pg_real.drop_database(name)


@pytest.fixture()
def pg_app(pg_url):
    def build():
        class Local(TestConfig):
            DATABASE_URL = pg_url
            SECRET_KEY = "stable-real-postgres-secret"

        return create_app(Local)

    return build


def _signup(client, email, password=PASSWORD, name="Malak"):
    return client.post(
        "/signup",
        data={"name": name, "email": email, "password": password, "confirm": password},
        follow_redirects=True,
    )


def _login(client, email, password=PASSWORD):
    return client.post(
        "/login",
        data={"email": email, "password": password},
        follow_redirects=True,
    )


# --------------------------------------------------------------------------
# schema and adapter
# --------------------------------------------------------------------------


def test_schema_initialises_on_real_postgres(pg_app):
    app = pg_app()
    assert engine_kind(app.config["DATABASE_URL"]) == "postgres"
    with app.app_context():
        rows = query_all(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
        )
    names = {r["table_name"] for r in rows}
    for expected in (
        "users",
        "attempts",
        "transcripts",
        "markings",
        "feedback",
        "self_evaluations",
        "prompt_usage",
        "password_resets",
        "gathered_info",
        "subscriptions",
        "webhook_events",
        "usage_counters",
    ):
        assert expected in names, f"table {expected} was not created"


def test_init_db_is_idempotent(pg_app):
    """Multiple gunicorn workers all run init_db at boot."""
    pg_app()
    pg_app()
    app = pg_app()
    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_insert_returning_id_select_and_update(pg_app):
    app = pg_app()
    with app.app_context():
        result = execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A", "a@example.com", "scrypt:1$a$b", "2026-01-01", "2026-01-01"),
        )
        assert isinstance(result.lastrowid, int) and result.lastrowid > 0
        user_id = result.lastrowid

        row = query_one("SELECT * FROM users WHERE id = ?", (user_id,))
        assert row["email"] == "a@example.com"

        execute("UPDATE users SET name = ? WHERE id = ?", ("B", user_id))
        assert query_one("SELECT name FROM users WHERE id = ?", (user_id,))["name"] == "B"


def test_parameterless_sql_and_like_wildcards(pg_app):
    app = pg_app()
    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM attempts")["n"] == 0
        execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A", "a@example.com", "h", "2026-01-01", "2026-01-01"),
        )
        user = query_one("SELECT id FROM users WHERE email = ?", ("a@example.com",))
        execute(
            "INSERT INTO gathered_info (user_id, topic, information, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (user["id"], "Recycling", "Plastic facts", "2026-01-01", "2026-01-01"),
        )
        found = query_all(
            "SELECT * FROM gathered_info WHERE user_id = ? AND (topic LIKE ? OR information LIKE ?)",
            (user["id"], "%ecycl%", "%ecycl%"),
        )
        assert len(found) == 1


def test_null_boolean_json_and_timestamp_handling(pg_app):
    app = pg_app()
    with app.app_context():
        execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A", "a@example.com", "h", "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        )
        user_id = query_one("SELECT id FROM users WHERE email = ?", ("a@example.com",))["id"]
        payload = {"turns": [], "nested": {"a": 1}, "unicode": "café ✓"}
        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at, total_score, completed_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "roleplay", "practice", "in_progress", "roleplay", json.dumps(payload),
             "2026-01-01T00:00:00+00:00", None, None),
        )
        row = query_one("SELECT * FROM attempts WHERE user_id = ?", (user_id,))
        assert row["total_score"] is None
        assert row["completed_at"] is None
        assert json.loads(row["payload_json"])["unicode"] == "café ✓"

        execute("UPDATE attempts SET total_score = ? WHERE id = ?", (0, row["id"]))
        assert query_one("SELECT total_score FROM attempts WHERE id = ?", (row["id"],))["total_score"] == 0


def test_foreign_key_cascade_is_enforced(pg_app):
    app = pg_app()
    with app.app_context():
        with pytest.raises(Exception):
            execute(
                """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (999999, "roleplay", "practice", "in_progress", "roleplay", "{}", "2026-01-01"),
            )


def test_failed_statement_rolls_back_and_connection_stays_usable(pg_app):
    app = pg_app()
    with app.app_context():
        with pytest.raises(Exception):
            execute("INSERT INTO users (name) VALUES (?)", ("missing columns",))
        # Without a rollback PostgreSQL reports InFailedSqlTransaction here.
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 0


def test_on_conflict_upsert_works(pg_app):
    app = pg_app()
    with app.app_context():
        execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A", "a@example.com", "h", "2026-01-01", "2026-01-01"),
        )
        user_id = query_one("SELECT id FROM users WHERE email = ?", ("a@example.com",))["id"]
        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (user_id, "roleplay", "practice", "in_progress", "roleplay", "{}", "2026-01-01"),
        )
        attempt_id = query_one("SELECT id FROM attempts WHERE user_id = ?", (user_id,))["id"]
        for comment in ("first", "second"):
            execute(
                """INSERT INTO feedback (attempt_id, strengths_json, weaknesses_json, lost_marks_json,
                                          recommendations_json, examiner_comments, created_at)
                   VALUES (?, '[]', '[]', '[]', '[]', ?, '2026-01-01')
                   ON CONFLICT(attempt_id) DO UPDATE SET examiner_comments = excluded.examiner_comments""",
                (attempt_id, comment),
            )
        rows = query_all("SELECT * FROM feedback WHERE attempt_id = ?", (attempt_id,))
        assert len(rows) == 1
        assert rows[0]["examiner_comments"] == "second"


# --------------------------------------------------------------------------
# authentication
# --------------------------------------------------------------------------


def test_signup_login_logout_on_real_postgres(pg_app):
    app = pg_app()
    client = app.test_client()
    assert _signup(client, "student@example.com").status_code == 200
    assert client.get("/dashboard").status_code == 200

    client.get("/logout")
    assert b"Sign in" in client.get("/dashboard", follow_redirects=True).data

    assert b"Incorrect email or password" in _login(client, "student@example.com", "wrongpass1").data
    assert b"Incorrect email or password" not in _login(client, "student@example.com").data
    assert client.get("/dashboard").status_code == 200


def test_password_is_hashed_on_real_postgres(pg_app):
    from werkzeug.security import check_password_hash

    app = pg_app()
    _signup(app.test_client(), "student@example.com")
    with app.app_context():
        stored = query_one("SELECT password_hash FROM users WHERE email = ?", ("student@example.com",))["password_hash"]
    assert isinstance(stored, str)
    assert PASSWORD not in stored
    assert stored.startswith(("scrypt:", "pbkdf2:"))
    assert len(stored) > 80
    assert check_password_hash(stored, PASSWORD)
    assert not check_password_hash(stored, "wrongpass1")


def test_duplicate_signup_is_rejected_on_real_postgres(pg_app):
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")
    client.get("/logout")
    assert b"already exists" in _signup(client, "student@example.com").data
    with app.app_context():
        assert query_one("SELECT COUNT(*) AS n FROM users")["n"] == 1


def test_email_unique_constraint_exists_on_real_postgres(pg_app):
    app = pg_app()
    with app.app_context():
        execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("A", "dupe@example.com", "h", "2026-01-01", "2026-01-01"),
        )
        with pytest.raises(Exception):
            execute(
                "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                ("B", "dupe@example.com", "h", "2026-01-01", "2026-01-01"),
            )


# --------------------------------------------------------------------------
# practice / exam start
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "section,expected",
    [("roleplay", "roleplay"), ("topic_talk", "topic_talk"), ("picture", "picture"), ("full", "full")],
)
def test_practice_start_on_real_postgres(pg_app, section, expected):
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")

    data = {"section": section}
    if section == "topic_talk":
        data.update({"topic_title": "Climate change", "topic_notes": "causes, effects"})
    response = client.post("/practice/start", data=data)
    assert response.status_code == 302, response.get_data(as_text=True)

    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    assert attempt_id > 0

    with app.app_context():
        row = query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    assert row is not None
    assert row["exam_type"] == expected
    assert row["status"] == "in_progress"
    assert json.loads(row["payload_json"])

    assert client.get(f"/exam/{attempt_id}").status_code == 200
    state = client.get(f"/exam/{attempt_id}/state").get_json()
    assert state["prompt"], "no first prompt was returned"
    assert state["attempt_id"] == attempt_id


def test_exam_start_route_on_real_postgres(pg_app):
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")
    response = client.post("/exam/start", data={"exam_type": "full", "mode": "full", "topic_title": "Plastic"})
    assert response.status_code == 302
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    with app.app_context():
        assert query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,)) is not None


def test_attempt_is_associated_with_the_logged_in_user(pg_app):
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")
    response = client.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    with app.app_context():
        user = query_one("SELECT id FROM users WHERE email = ?", ("student@example.com",))
        row = query_one("SELECT user_id FROM attempts WHERE id = ?", (attempt_id,))
    assert row["user_id"] == user["id"]


# --------------------------------------------------------------------------
# full lifecycle: answer -> transcript -> marking -> feedback -> progress
# --------------------------------------------------------------------------


def test_full_practice_lifecycle_on_real_postgres(pg_app, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")

    response = client.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    redirect_target = None
    for _ in range(30):
        turn = client.post(
            f"/exam/{attempt_id}/turn",
            json={
                "transcript": "I usually go to the cinema twice a month with my sister because we enjoy action films.",
                "metrics": {"duration_ms": 8000, "word_count": 16},
            },
        )
        assert turn.status_code == 200, turn.get_data(as_text=True)
        body = turn.get_json()
        if body.get("redirect"):
            redirect_target = body["redirect"]
            break
    assert redirect_target, "practice never completed"

    assert client.get(redirect_target).status_code == 200

    with app.app_context():
        transcripts = query_all("SELECT * FROM transcripts WHERE attempt_id = ?", (attempt_id,))
        marking = query_one("SELECT * FROM markings WHERE attempt_id = ?", (attempt_id,))
        feedback = query_one("SELECT * FROM feedback WHERE attempt_id = ?", (attempt_id,))
        attempt = query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,))

    assert transcripts, "no transcript was saved"
    assert any("cinema" in t["text"] for t in transcripts), "student answer was not saved"
    assert marking is not None, "marking was not saved"
    assert json.loads(marking["scores_json"]), "scores were not saved"
    assert feedback is not None, "feedback was not saved"
    assert attempt["status"] == "completed"

    assert client.get("/progress").status_code == 200
    history = client.get("/history")
    assert history.status_code == 200
    assert client.get(f"/history/{attempt_id}").status_code == 200


def test_self_evaluation_persists_on_real_postgres(pg_app, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    app = pg_app()
    client = app.test_client()
    _signup(client, "student@example.com")
    response = client.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    client.post(
        f"/evaluation/{attempt_id}",
        data={
            "confidence": "4",
            "fluency": "3",
            "difficulty": "2",
            "struggled_with": "timing",
            "improve_next": "examples",
            "satisfaction": "5",
            "student_notes": "went ok",
        },
        follow_redirects=True,
    )
    with app.app_context():
        row = query_one("SELECT * FROM self_evaluations WHERE attempt_id = ?", (attempt_id,))
    assert row is not None
    assert row["confidence"] == 4


# --------------------------------------------------------------------------
# persistence across a full application restart
# --------------------------------------------------------------------------


def test_everything_survives_application_restart_on_real_postgres(pg_app, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)

    app1 = pg_app()
    client1 = app1.test_client()
    _signup(client1, "persist@example.com")
    response = client1.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])
    client1.post(
        f"/exam/{attempt_id}/turn",
        json={
            "transcript": "I go swimming every Friday evening with my cousin at the local pool.",
            "metrics": {"duration_ms": 6000, "word_count": 13},
        },
    )
    client1.get("/logout")

    # Full restart: brand new application object, same database.
    app2 = pg_app()
    client2 = app2.test_client()

    assert b"Incorrect email or password" in _login(client2, "persist@example.com", "wrongpass1").data
    assert b"Incorrect email or password" not in _login(client2, "persist@example.com").data

    detail = client2.get(f"/history/{attempt_id}")
    assert detail.status_code == 200
    assert b"swimming" in detail.data, "the saved answer did not survive the restart"
    assert client2.get("/progress").status_code == 200

    with app2.app_context():
        transcripts = query_all("SELECT * FROM transcripts WHERE attempt_id = ?", (attempt_id,))
    assert any("swimming" in t["text"] for t in transcripts)


# --------------------------------------------------------------------------
# user isolation
# --------------------------------------------------------------------------


def test_user_isolation_on_real_postgres(pg_app, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    app = pg_app()

    client_a = app.test_client()
    _signup(client_a, "usera@example.com", name="User A")
    response = client_a.post("/practice/start", data={"section": "roleplay"})
    attempt_a = int(response.headers["Location"].rstrip("/").split("/")[-1])
    client_a.post(
        f"/exam/{attempt_a}/turn",
        json={"transcript": "User A talks about private matters here.", "metrics": {"duration_ms": 5000}},
    )

    client_b = app.test_client()
    _signup(client_b, "userb@example.com", name="User B")

    assert client_b.get(f"/history/{attempt_a}").status_code == 404
    assert client_b.get(f"/exam/{attempt_a}").status_code == 404
    assert client_b.get(f"/exam/{attempt_a}/results").status_code == 404
    assert client_b.get(f"/exam/{attempt_a}/state").status_code == 404
    assert client_b.post(f"/exam/{attempt_a}/turn", json={"transcript": "hi"}).status_code == 404

    history_b = client_b.get("/history")
    assert b"private matters" not in history_b.data
    progress_b = client_b.get("/progress")
    assert b"private matters" not in progress_b.data

    with app.app_context():
        user_b = query_one("SELECT id FROM users WHERE email = ?", ("userb@example.com",))
        rows = query_all("SELECT * FROM attempts WHERE user_id = ?", (user_b["id"],))
    assert rows == [] or all(r["id"] != attempt_a for r in rows)


def test_full_exam_marks_persist_on_real_postgres(pg_app, monkeypatch):
    from tests.fake_ai import install_fake
    from tests.test_full_exam_pipeline import _complete_full_exam

    install_fake(monkeypatch)
    app = pg_app()
    assert engine_kind(app.config["DATABASE_URL"]) == "postgres"
    client = app.test_client()
    _signup(client, "pg-full@example.com")
    result = _complete_full_exam(client)
    page = result["page"]
    assert page.status_code == 200
    assert b"/50" in page.data
    with app.app_context():
        assert engine_kind(app.config["DATABASE_URL"]) == "postgres"
        attempt = query_one(
            "SELECT status, roleplay_score, topic_talk_score, picture_score, total_score FROM attempts WHERE id = 1"
        )
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json FROM feedback WHERE attempt_id = 1")
        transcripts = query_all("SELECT stage, text FROM transcripts WHERE attempt_id = 1 AND speaker = 'student'")
    assert attempt["status"] == "completed"
    assert attempt["roleplay_score"] is not None
    assert attempt["topic_talk_score"] is not None
    assert attempt["picture_score"] is not None
    assert marking is not None
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert payload["picture"]["image_assessed"] is True
    assert feedback is not None
    assert any(row["stage"] == "roleplay" for row in transcripts)
    assert any(row["stage"] == "topic_talk" for row in transcripts)
    assert any(row["stage"] == "picture" for row in transcripts)
    assert str(attempt["roleplay_score"]).encode() in page.data or b"/10" in page.data


def test_anonymous_users_cannot_reach_exam_data(pg_app):
    app = pg_app()
    owner = app.test_client()
    _signup(owner, "owner@example.com")
    response = owner.post("/practice/start", data={"section": "roleplay"})
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    anon = app.test_client()
    for path in (f"/exam/{attempt_id}", f"/exam/{attempt_id}/state", f"/history/{attempt_id}", "/progress", "/dashboard"):
        response = anon.get(path, follow_redirects=True)
        assert b"Sign in" in response.data, f"{path} was reachable without logging in"


@pytest.mark.skipif(os.environ.get("SPEAKED_LIVE_GEMINI") != "1", reason="Set SPEAKED_LIVE_GEMINI=1 to call Gemini")
def test_live_gemini_full_exam_on_real_postgres(pg_url):
    from tests.test_full_exam_pipeline import _complete_full_exam

    key = os.environ.get("GEMINI_API_KEY", "")
    assert key, "GEMINI_API_KEY is required"

    class Live(TestConfig):
        DATABASE_URL = pg_url
        SECRET_KEY = "stable-real-postgres-secret"
        AI_PROVIDER = "gemini"
        GEMINI_API_KEY = key
        GEMINI_MODEL = "gemini-3.5-flash-lite"

    app = create_app(Live)
    assert engine_kind(app.config["DATABASE_URL"]) == "postgres"
    image_part = {"sent": False, "mime": None, "nbytes": 0}
    with app.app_context():
        from ai.ai_provider import get_ai

        provider = get_ai()
        orig = provider._post_model

        def wrap_post(model, payload):
            parts = (((payload.get("contents") or [{}])[0].get("parts")) or [])
            for part in parts:
                inline = part.get("inline_data") or {}
                mime = inline.get("mime_type") or ""
                data = inline.get("data") or ""
                if mime.startswith("image/") and data:
                    image_part["sent"] = True
                    image_part["mime"] = mime
                    image_part["nbytes"] = len(data)
            return orig(model, payload)

        provider._post_model = wrap_post

    client = app.test_client()
    _signup(client, "live-pg@example.com")
    result = _complete_full_exam(client)
    page = result["page"]
    body = page.get_data(as_text=True)
    assert key not in body
    assert engine_kind(app.config["DATABASE_URL"]) == "postgres"
    with app.app_context():
        attempt = query_one(
            "SELECT status, roleplay_score, topic_talk_score, picture_score, total_score FROM attempts WHERE id = 1"
        )
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json, examiner_comments FROM feedback WHERE attempt_id = 1")
    assert attempt["status"] == "completed"
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert attempt["roleplay_score"] is not None
    assert attempt["topic_talk_score"] is not None
    assert attempt["picture_score"] is not None
    assert feedback is not None
    assert payload.get("picture", {}).get("image_assessed") is True
    assert image_part["sent"] is True
    assert image_part["mime"] == "image/png"
    assert image_part["nbytes"] > 50
    assert "/50" in body
    print(json.dumps({
        "engine": engine_kind(app.config["DATABASE_URL"]),
        "scores": {
            "roleplay": attempt["roleplay_score"],
            "topic": attempt["topic_talk_score"],
            "picture": attempt["picture_score"],
            "total": attempt["total_score"],
        },
        "image": image_part,
        "audio_assessed": payload.get("audio_assessed"),
    }))

