import json

from werkzeug.security import check_password_hash

from app import create_app
from config import TestConfig
from database.database import engine_kind, execute, normalize_postgres_dsn, query_one, to_postgres_sql
from tests.conftest import signup


def _file_app(tmp_path, name="persist.db"):
    class Local(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / name}"
        SECRET_KEY = "stable-secret-for-restart"

    return create_app(Local)


def test_sqlite_engine_kind():
    assert engine_kind("sqlite:///instance/speaked.db") == "sqlite"
    assert engine_kind("") == "sqlite"


def test_postgres_engine_kind_and_dsn():
    assert engine_kind("postgres://u:p@host/db") == "postgres"
    assert engine_kind("postgresql://u:p@host/db") == "postgres"
    dsn = normalize_postgres_dsn("postgres://u:p@host/db")
    assert dsn.startswith("postgresql://")
    assert "sslmode=require" in dsn
    already = normalize_postgres_dsn("postgresql://u:p@host/db?sslmode=disable")
    assert "sslmode=disable" in already
    assert "sslmode=require" not in already


def test_to_postgres_sql_placeholders_and_conflict():
    sql = to_postgres_sql("INSERT INTO feedback (attempt_id) VALUES (?) ON CONFLICT(attempt_id) DO UPDATE SET x=excluded.x")
    assert "%s" in sql
    assert "?" not in sql
    assert "ON CONFLICT (attempt_id)" in sql
    assert "RETURNING ID" in sql.upper()


def test_sqlite_local_default_is_file(tmp_path):
    app = _file_app(tmp_path)
    assert engine_kind(app.config["DATABASE_URL"]) == "sqlite"
    assert "persist.db" in app.config["DATABASE_URL"] or str(tmp_path) in app.config["DATABASE_URL"]
    assert (tmp_path / "persist.db").exists()


def test_database_init_creates_users_table(tmp_path):
    app = _file_app(tmp_path)
    with app.app_context():
        row = query_one("SELECT name FROM sqlite_master WHERE type='table' AND name='users'")
        assert row is not None


def test_duplicate_signup_rejected(client):
    first = signup(client)
    assert first.status_code == 200
    client.get("/logout")
    again = signup(client)
    assert b"already exists" in again.data


def test_logout_clears_session(client):
    signup(client)
    dash = client.get("/dashboard")
    assert dash.status_code == 200
    client.get("/logout", follow_redirects=True)
    again = client.get("/dashboard", follow_redirects=True)
    assert b"Sign in" in again.data


def test_password_is_hashed_not_plaintext(app, client):
    signup(client)
    with app.app_context():
        user = query_one("SELECT email, password_hash FROM users WHERE email = ?", ("student@example.com",))
        assert user["password_hash"] != "password12"
        assert "password12" not in user["password_hash"]
        assert check_password_hash(user["password_hash"], "password12")


def test_login_survives_application_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'restart.db'}"

    class Local(TestConfig):
        DATABASE_URL = db_url
        SECRET_KEY = "stable-secret-for-restart"

    app1 = create_app(Local)
    client1 = app1.test_client()
    signup(client1, "persist@example.com")
    client1.get("/logout")

    app2 = create_app(Local)
    client2 = app2.test_client()
    failed = client2.post(
        "/login",
        data={"email": "persist@example.com", "password": "wrongpass1"},
        follow_redirects=True,
    )
    assert b"Incorrect" in failed.data
    ok = client2.post(
        "/login",
        data={"email": "persist@example.com", "password": "password12"},
        follow_redirects=True,
    )
    assert ok.status_code == 200
    assert b"Welcome" in ok.data
    dash = client2.get("/dashboard")
    assert dash.status_code == 200


def test_attempts_marks_feedback_survive_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'progress.db'}"

    class Local(TestConfig):
        DATABASE_URL = db_url
        SECRET_KEY = "stable-secret-for-restart"

    app1 = create_app(Local)
    client1 = app1.test_client()
    signup(client1, "owner@example.com")
    with app1.app_context():
        user = query_one("SELECT id FROM users WHERE email = ?", ("owner@example.com",))
        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, total_score, started_at, completed_at)
               VALUES (?, 'roleplay', 'practice', 'completed', 'complete', '{}', 8, '2026-01-01T00:00:00+00:00', '2026-01-01T00:10:00+00:00')""",
            (user["id"],),
        )
        attempt = query_one("SELECT id FROM attempts WHERE user_id = ?", (user["id"],))
        execute(
            "INSERT INTO transcripts (attempt_id, stage, turn_index, speaker, prompt_id, text, created_at) VALUES (?, 'roleplay', 1, 'student', 'p1', 'I go to the cinema twice a month.', '2026-01-01T00:01:00+00:00')",
            (attempt["id"],),
        )
        execute(
            "INSERT INTO markings (attempt_id, analysis_json, scores_json, justification_json, created_at) VALUES (?, '{}', ?, '{}', '2026-01-01T00:10:00+00:00')",
            (attempt["id"], json.dumps({"roleplay": 8, "total": 8})),
        )
        execute(
            "INSERT INTO feedback (attempt_id, strengths_json, weaknesses_json, lost_marks_json, recommendations_json, examiner_comments, created_at) VALUES (?, ?, '[]', '[]', '[]', 'Specific comment about cinema.', '2026-01-01T00:10:00+00:00')",
            (attempt["id"], json.dumps(["You mentioned going to the cinema."])),
        )
        execute(
            "INSERT INTO self_evaluations (attempt_id, confidence, fluency, difficulty, struggled_with, improve_next, satisfaction, student_notes, created_at) VALUES (?, 4, 3, 2, 'timing', 'examples', 5, 'ok', '2026-01-01T00:11:00+00:00')",
            (attempt["id"],),
        )
        saved_attempt_id = attempt["id"]

    app2 = create_app(Local)
    client2 = app2.test_client()
    client2.post(
        "/login",
        data={"email": "owner@example.com", "password": "password12"},
        follow_redirects=True,
    )
    history = client2.get("/history")
    assert history.status_code == 200
    detail = client2.get(f"/history/{saved_attempt_id}")
    assert detail.status_code == 200
    assert b"I go to the cinema twice a month." in detail.data
    assert b"Specific comment about cinema." in detail.data
    with app2.app_context():
        marking = query_one("SELECT scores_json FROM markings WHERE attempt_id = ?", (saved_attempt_id,))
        feedback = query_one("SELECT strengths_json FROM feedback WHERE attempt_id = ?", (saved_attempt_id,))
        evaluation = query_one("SELECT confidence FROM self_evaluations WHERE attempt_id = ?", (saved_attempt_id,))
        assert json.loads(marking["scores_json"])["total"] == 8
        assert "cinema" in json.loads(feedback["strengths_json"])[0]
        assert evaluation["confidence"] == 4


def test_user_cannot_see_other_progress_after_restart(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'isolate.db'}"

    class Local(TestConfig):
        DATABASE_URL = db_url
        SECRET_KEY = "stable-secret-for-restart"

    app1 = create_app(Local)
    c1 = app1.test_client()
    signup(c1, "owner@example.com")
    with app1.app_context():
        execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
               VALUES (1, 'full', 'full', 'completed', 'complete', '{}', '2026-01-01T00:00:00+00:00')"""
        )
        row = query_one("SELECT id FROM attempts")
        attempt_id = row["id"]
    c1.get("/logout")
    signup(c1, "other@example.com")

    app2 = create_app(Local)
    c2 = app2.test_client()
    c2.post("/login", data={"email": "other@example.com", "password": "password12"}, follow_redirects=True)
    hidden = c2.get(f"/history/{attempt_id}")
    assert hidden.status_code == 404


def test_sqlite_is_used_when_url_is_sqlite():
    from config import BASE_DIR

    fallback = f"sqlite:///{BASE_DIR / 'instance' / 'speaked.db'}"
    assert engine_kind(fallback) == "sqlite"
    assert engine_kind("sqlite:///:memory:") == "sqlite"
