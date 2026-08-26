"""Regression tests for starting exams and practice on the PostgreSQL code path.

These run against tests/fake_pg.py, an in-process driver that enforces the
psycopg2 rules our adapter must satisfy. No real database is created or deleted.
"""

import json

import pytest

from app import create_app
from config import TestConfig
from database.database import query_all, query_one
from tests import fake_pg

PASSWORD = "password12"
EMAIL = "pg-exam@example.com"


def _pg_config():
    class Local(TestConfig):
        DATABASE_URL = "postgresql://speaked:secret@db.internal:5432/speaked"
        SECRET_KEY = "stable-postgres-secret"

    return Local


@pytest.fixture()
def pg(monkeypatch, tmp_path):
    return fake_pg.install(monkeypatch, tmp_path / "pg" / "speaked.sql")


@pytest.fixture()
def logged_in(pg):
    app = create_app(_pg_config())
    client = app.test_client()
    client.post(
        "/signup",
        data={"name": "Malak", "email": EMAIL, "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    return app, client


def _start(client, section, **extra):
    data = {"section": section}
    data.update(extra)
    return client.post("/practice/start", data=data, follow_redirects=False)


def _assert_attempt_usable(app, client, response, expected_type):
    assert response.status_code == 302, f"start failed: {response.status_code}"
    location = response.headers["Location"]
    attempt_id = int(location.rstrip("/").split("/")[-1])
    assert attempt_id > 0, "attempt id was not generated"

    with app.app_context():
        row = query_one("SELECT * FROM attempts WHERE id = ?", (attempt_id,))
    assert row is not None, "attempt row could not be retrieved"
    assert row["exam_type"] == expected_type
    assert row["status"] == "in_progress"
    assert json.loads(row["payload_json"]) != {}

    room = client.get(f"/exam/{attempt_id}")
    assert room.status_code == 200, "exam room did not render"
    return attempt_id


def test_roleplay_practice_starts(logged_in):
    app, client = logged_in
    response = _start(client, "roleplay")
    attempt_id = _assert_attempt_usable(app, client, response, "roleplay")

    state = client.get(f"/exam/{attempt_id}/state").get_json()
    assert state["prompt"], "no first prompt returned"
    assert state["prompt"].get("spoken"), "first prompt has no spoken text"


def test_topic_talk_practice_starts(logged_in):
    app, client = logged_in
    response = _start(client, "topic_talk", topic_title="Climate change", topic_notes="causes, effects")
    attempt_id = _assert_attempt_usable(app, client, response, "topic_talk")

    state = client.get(f"/exam/{attempt_id}/state").get_json()
    assert state["prompt"], "no first prompt returned"


def test_picture_conversation_practice_starts(logged_in):
    app, client = logged_in
    response = _start(client, "picture")
    attempt_id = _assert_attempt_usable(app, client, response, "picture")

    state = client.get(f"/exam/{attempt_id}/state").get_json()
    assert state["prompt"], "no first prompt returned"


def test_full_exam_starts(logged_in):
    app, client = logged_in
    response = _start(client, "full")
    _assert_attempt_usable(app, client, response, "full")


def test_prompt_usage_is_recorded_on_postgres(logged_in):
    app, client = logged_in
    _start(client, "roleplay")
    with app.app_context():
        rows = query_all("SELECT * FROM prompt_usage")
    assert rows, "prompt usage was not recorded"


def test_missing_insert_id_fails_loudly_instead_of_a_confusing_500(pg, monkeypatch):
    """The original bug: a None id became KeyError: 'attempt_id' two layers away.

    If an INSERT ever stops returning an id again, it must raise here, naming
    the real problem, rather than degrading into an unrelated lookup miss.
    """
    import database.database as db

    app = create_app(_pg_config())
    client = app.test_client()
    client.post(
        "/signup",
        data={"name": "Malak", "email": EMAIL, "password": PASSWORD, "confirm": PASSWORD},
        follow_redirects=True,
    )
    monkeypatch.setattr(db, "_returned_id", lambda cursor: None)
    app.config["PROPAGATE_EXCEPTIONS"] = True

    with pytest.raises(RuntimeError, match="did not return an id"):
        client.post("/practice/start", data={"section": "roleplay"})


def test_strict_type_checking_is_actually_active(pg):
    """Guard the guard: the fake driver must reject integer/text mismatches."""
    from database.database import execute

    app = create_app(_pg_config())
    with app.app_context():
        with pytest.raises(Exception, match="type text but expression is of type integer"):
            execute(
                "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (1234, "typed@example.com", "scrypt:1$a$b", "2026-01-01", "2026-01-01"),
            )


def test_turn_and_transcript_insert_work_on_postgres(logged_in, monkeypatch):
    from tests.fake_ai import install_fake

    install_fake(monkeypatch)
    app, client = logged_in
    response = _start(client, "roleplay")
    attempt_id = int(response.headers["Location"].rstrip("/").split("/")[-1])

    turn = client.post(
        f"/exam/{attempt_id}/turn",
        json={
            "transcript": "I go to the cinema about twice a month with my sister.",
            "metrics": {"duration_ms": 4000, "word_count": 12},
        },
    )
    assert turn.status_code == 200, turn.get_data(as_text=True)

    with app.app_context():
        rows = query_all("SELECT * FROM transcripts WHERE attempt_id = ?", (attempt_id,))
    assert rows, "transcript row was not written"


def test_two_attempts_get_distinct_ids(logged_in):
    app, client = logged_in
    first = _start(client, "roleplay")
    second = _start(client, "roleplay")
    first_id = int(first.headers["Location"].rstrip("/").split("/")[-1])
    second_id = int(second.headers["Location"].rstrip("/").split("/")[-1])
    assert first_id != second_id


def test_retry_marking_does_not_500_on_postgres(logged_in, monkeypatch):
    """Retry marking starts with an UPDATE. Fetching a result from that UPDATE
    used to abort the PostgreSQL transaction and 500 before marks were saved."""
    from tests.fake_ai import install_fake

    app, client = logged_in
    start = _start(client, "roleplay")
    attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
    finished = None
    for _ in range(8):
        response = client.post(
            f"/exam/{attempt_id}/turn",
            json={
                "transcript": "I go to the cinema about twice a month with my sister.",
                "metrics": {"duration_ms": 4000, "word_count": 12},
            },
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        data = response.get_json()
        if data.get("redirect"):
            finished = data["redirect"]
            break
    assert finished, "roleplay did not complete"
    retry = client.post(f"/exam/{attempt_id}/retry-marking", follow_redirects=False)
    assert retry.status_code in {302, 303}, retry.get_data(as_text=True)
    assert b"Internal Server Error" not in retry.data

    install_fake(monkeypatch)
    marked = client.post(f"/exam/{attempt_id}/retry-marking", follow_redirects=True)
    assert marked.status_code == 200
    assert b"Internal Server Error" not in marked.data
    with app.app_context():
        row = query_one("SELECT status, roleplay_score FROM attempts WHERE id = ?", (attempt_id,))
    assert row["status"] == "completed"
    assert row["roleplay_score"] is not None


def test_marking_and_feedback_persist_on_postgres(logged_in, monkeypatch):
    from tests.fake_ai import FakeAIProvider, install_fake

    app, client = logged_in
    fake = install_fake(monkeypatch, FakeAIProvider())
    start = _start(client, "roleplay")
    attempt_id = int(start.headers["Location"].rstrip("/").split("/")[-1])
    answer = "I love football because I play it with my friends every weekend."
    finished = None
    for _ in range(8):
        response = client.post(
            f"/exam/{attempt_id}/turn",
            json={"transcript": answer, "metrics": {"duration_ms": 4000, "word_count": 14}},
        )
        assert response.status_code == 200, response.get_data(as_text=True)
        data = response.get_json()
        if data.get("redirect"):
            finished = data["redirect"]
            break
    assert finished
    page = client.get(finished)
    assert page.status_code == 200
    assert b"/10" in page.data
    assert b"football" in page.data.lower()
    with app.app_context():
        marking = query_one("SELECT justification_json, scores_json FROM markings WHERE attempt_id = ?", (attempt_id,))
        feedback = query_one("SELECT strengths_json, examiner_comments FROM feedback WHERE attempt_id = ?", (attempt_id,))
        attempt = query_one("SELECT status, roleplay_score FROM attempts WHERE id = ?", (attempt_id,))
    assert marking is not None
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert payload["total"] == attempt["roleplay_score"]
    assert "football" in json.dumps(payload).lower()
    assert feedback is not None
    assert "football" in (feedback["strengths_json"] + feedback["examiner_comments"]).lower()
    assert any("football" in p.lower() for p in fake.prompts)
