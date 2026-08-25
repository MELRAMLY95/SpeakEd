import json

from tests.conftest import signup
from tests.fake_ai import install_fake


def _complete_roleplay_without_marks(client):
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    for _ in range(8):
        response = client.post(
            "/exam/1/turn",
            json={
                "transcript": "I go to the cinema about twice a month with my sister.",
                "metrics": {"duration_ms": 4000, "word_count": 12},
            },
        )
        data = response.get_json()
        if data.get("redirect"):
            return data["redirect"]
    raise AssertionError("roleplay did not complete")


def _seed_unmarked(app, *, exam_type: str, user_id: int = 1) -> int:
    from database.database import execute

    stage = {"roleplay": "roleplay", "topic_talk": "topic_talk", "picture": "picture", "full": "picture"}[exam_type]
    payload = json.dumps({
        "exam_type": exam_type,
        "turns": [{"stage": stage, "speaker": "student", "text": "I go to the cinema twice a month with my sister."}],
    })
    with app.app_context():
        cursor = execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at, completed_at)
               VALUES (?, ?, 'practice', 'marking_unavailable', 'complete', ?, '2026-08-25T12:00:00+00:00', '2026-08-25T12:10:00+00:00')""",
            (user_id, exam_type, payload),
        )
        attempt_id = cursor.lastrowid
        execute(
            """INSERT INTO transcripts (attempt_id, stage, turn_index, speaker, prompt_id, text, duration_ms, speech_metrics_json, created_at)
               VALUES (?, ?, 1, 'student', 'p1', 'I go to the cinema twice a month with my sister.', 4000, '{}', '2026-08-25T12:01:00+00:00')""",
            (attempt_id, stage),
        )
        return attempt_id


def test_progress_page_empty_then_history(client):
    signup(client)
    page = client.get("/progress")
    assert page.status_code == 200
    history = client.get("/history")
    assert history.status_code == 200


def test_unmarked_roleplay_can_be_retried_from_progress(client, app, monkeypatch):
    signup(client)
    _complete_roleplay_without_marks(client)

    progress = client.get("/progress")
    assert progress.status_code == 200
    assert b"Retry marking" in progress.data
    history = client.get("/history")
    assert b"Retry marking" in history.data
    assert b"Marks pending" in history.data
    detail = client.get("/history/1")
    assert detail.status_code == 200
    assert b"Retry marking" in detail.data

    install_fake(monkeypatch)
    retry = client.post("/exam/1/retry-marking", follow_redirects=True)
    assert retry.status_code == 200
    assert b"could not complete marking" not in retry.data.lower()
    assert b"/10" in retry.data
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT status, roleplay_score FROM attempts WHERE id = 1")
        assert row["status"] == "completed"
        assert row["roleplay_score"] is not None


def test_retry_marking_is_offered_for_each_speaking_task(client, app):
    signup(client)
    for exam_type in ("roleplay", "topic_talk", "picture", "full"):
        attempt_id = _seed_unmarked(app, exam_type=exam_type)
        history = client.get("/history")
        assert history.status_code == 200
        assert f"/exam/{attempt_id}/retry-marking".encode() in history.data
        detail = client.get(f"/history/{attempt_id}")
        assert b"Retry marking" in detail.data


def test_stuck_complete_attempt_can_be_retried(client, app, monkeypatch):
    signup(client)
    _complete_roleplay_without_marks(client)
    with app.app_context():
        from database.database import execute

        execute(
            """UPDATE attempts SET status='in_progress', stage='complete',
               roleplay_score=NULL, total_score=NULL WHERE id=1"""
        )
    history = client.get("/history")
    assert b"Retry marking" in history.data
    install_fake(monkeypatch)
    retry = client.post("/exam/1/retry-marking", follow_redirects=True)
    assert retry.status_code == 200
    with app.app_context():
        from database.database import query_one

        row = query_one("SELECT status, roleplay_score FROM attempts WHERE id = 1")
        assert row["status"] == "completed"
        assert row["roleplay_score"] is not None


def test_in_progress_exam_does_not_offer_retry(client):
    signup(client)
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    client.post(
        "/exam/1/turn",
        json={
            "transcript": "I go to the cinema about twice a month with my sister.",
            "metrics": {"duration_ms": 4000, "word_count": 12},
        },
    )
    history = client.get("/history")
    assert b"Retry marking" not in history.data
    progress = client.get("/progress")
    assert b"Marks not generated" not in progress.data


def test_user_cannot_retry_someone_elses_attempt(client, app):
    signup(client, email="owner@example.com")
    attempt_id = _seed_unmarked(app, exam_type="roleplay")
    client.get("/logout")
    signup(client, email="other@example.com")
    response = client.post(f"/exam/{attempt_id}/retry-marking", follow_redirects=False)
    assert response.status_code in {302, 303}
    assert "/dashboard" in (response.headers.get("Location") or "")
    detail = client.get(f"/history/{attempt_id}")
    assert detail.status_code == 404
