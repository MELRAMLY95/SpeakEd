import json
import os

import pytest

from ai.feedback import build_feedback
from ai.marking import MarkingUnavailable, load_scheme, mark_attempt, mark_roleplay
from tests.conftest import signup
from tests.fake_ai import FakeAIProvider, install_fake

FOOTBALL = "I love football because I play it with my friends every weekend."
TENNIS = "I don't really enjoy football. I prefer tennis because it's more individual."


def _finish_roleplay(client, transcript: str) -> str:
    client.post("/exam/start", data={"exam_type": "roleplay", "mode": "practice"}, follow_redirects=True)
    for _ in range(8):
        response = client.post(
            "/exam/1/turn",
            json={"transcript": transcript, "metrics": {"duration_ms": 4000, "word_count": 12}},
        )
        data = response.get_json()
        if data.get("redirect"):
            return data["redirect"]
    raise AssertionError("roleplay did not complete")


def test_successful_gemini_shaped_marking(app, monkeypatch):
    fake = install_fake(monkeypatch)
    with app.app_context():
        result = mark_attempt(
            1,
            {
                "exam_type": "roleplay",
                "roleplay_student_turns": [{"text": FOOTBALL, "question": "Do you enjoy playing sport?"}],
                "topic_turns": [],
                "picture_turns": [],
            },
            persist=False,
        )
    assert result["unavailable"] is False
    assert result["total"] is not None
    assert 0 <= result["total"] <= 10
    prompt = fake.prompts[0]
    assert FOOTBALL in prompt
    assert "Do you enjoy playing sport?" in prompt
    assert "Clearly communicated" in prompt or "4XES2" in prompt
    assert FOOTBALL in json.dumps(result)


def test_malformed_json_marks_unavailable(app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(invalid_json=True))
    with app.app_context():
        result = mark_attempt(
            1,
            {
                "exam_type": "roleplay",
                "roleplay_student_turns": [{"text": FOOTBALL, "question": "Do you enjoy sport?"}],
                "topic_turns": [],
                "picture_turns": [],
            },
            persist=False,
        )
    assert result["unavailable"] is True
    assert result["total"] is None
    assert result["retry"] is True
    assert result["roleplay"] is None


def test_gemini_unavailable_does_not_fabricate_score(app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(http_error=503))
    with app.app_context():
        result = mark_attempt(
            1,
            {
                "exam_type": "roleplay",
                "roleplay_student_turns": [{"text": FOOTBALL, "question": "Do you enjoy sport?"}],
                "topic_turns": [],
                "picture_turns": [],
            },
            persist=False,
        )
    assert result["unavailable"] is True
    assert result["total"] is None
    assert "503" in (result.get("error") or "") or "unavailable" in (result.get("error") or "").lower() or "valid mark" in (result.get("error") or "").lower()


def test_gemini_timeout_marks_unavailable(app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(timeout=True))
    with app.app_context():
        result = mark_attempt(
            1,
            {
                "exam_type": "roleplay",
                "roleplay_student_turns": [{"text": FOOTBALL, "question": "Do you enjoy sport?"}],
                "topic_turns": [],
                "picture_turns": [],
            },
            persist=False,
        )
    assert result["unavailable"] is True
    assert result["total"] is None
    assert "timed out" in (result.get("error") or "").lower()


def test_invalid_mark_range_retries_then_can_succeed():
    scheme = load_scheme()
    ai = FakeAIProvider(out_of_range_once=True)
    result = mark_roleplay(
        [{"text": FOOTBALL, "question": "Do you enjoy playing sport?"}],
        scheme,
        ai=ai,
    )
    assert result["prompt_marks"][0]["mark"] in {0, 1, 2}
    assert ai.json_calls >= 2
    assert "STRICT RETRY" in ai.prompts[-1]


def test_out_of_range_without_valid_retry_is_unavailable():
    class AlwaysHigh(FakeAIProvider):
        def _json_for(self, prompt: str) -> dict:
            return {
                "prompt_marks": [{
                    "prompt_index": 1,
                    "mark": 9,
                    "reasoning": "too high",
                    "evidence": [FOOTBALL],
                    "strengths": ["x"],
                    "weaknesses": ["y"],
                    "improvements": ["z"],
                }]
            }

    scheme = load_scheme()
    with pytest.raises(MarkingUnavailable, match="outside"):
        mark_roleplay([{"text": FOOTBALL, "question": "Do you enjoy sport?"}], scheme, ai=AlwaysHigh())


def test_missing_student_answer_is_zero_not_invented():
    scheme = load_scheme()
    ai = FakeAIProvider()
    result = mark_roleplay(
        [{"text": "", "question": "How often do you go to the cinema?"}],
        scheme,
        ai=ai,
    )
    assert result["prompt_marks"][0]["mark"] == 0
    assert result["score"] == 0


def test_two_student_answers_produce_grounded_marks_and_feedback(app, monkeypatch):
    fake = install_fake(monkeypatch)
    scheme = load_scheme()
    a = mark_roleplay([{"text": FOOTBALL, "question": "Do you enjoy playing sport?"}], scheme, ai=fake)
    b = mark_roleplay([{"text": TENNIS, "question": "Do you enjoy playing sport?"}], scheme, ai=fake)
    assert FOOTBALL in fake.prompts[0]
    assert TENNIS in fake.prompts[1]
    assert FOOTBALL in json.dumps(a["prompt_marks"][0]["evidence"])
    assert TENNIS in json.dumps(b["prompt_marks"][0]["evidence"])
    assert a["prompt_marks"][0]["evidence"] != b["prompt_marks"][0]["evidence"]
    monkeypatch.setattr("ai.feedback._persist_feedback", lambda *args, **kwargs: None)
    with app.app_context():
        fb_a = build_feedback(1, {"unavailable": False, "roleplay": a, "topic_talk": {}, "picture": {}, "total": a["score"], "max_total": 10}, [{"speaker": "student", "text": FOOTBALL, "stage": "roleplay"}], payload={"roleplay_student_turns": [{"text": FOOTBALL, "question": "Do you enjoy playing sport?"}]})
        fb_b = build_feedback(2, {"unavailable": False, "roleplay": b, "topic_talk": {}, "picture": {}, "total": b["score"], "max_total": 10}, [{"speaker": "student", "text": TENNIS, "stage": "roleplay"}], payload={"roleplay_student_turns": [{"text": TENNIS, "question": "Do you enjoy playing sport?"}]})
    blob_a = json.dumps(fb_a).lower()
    blob_b = json.dumps(fb_b).lower()
    assert "football" in blob_a
    assert "tennis" in blob_b
    assert fb_a["strengths"] != fb_b["strengths"]
    assert "good job, keep practicing" not in blob_a


def test_marking_and_feedback_saved_then_results_retrieve(client, app, monkeypatch):
    fake = install_fake(monkeypatch)
    signup(client)
    redirect_url = _finish_roleplay(client, FOOTBALL)
    page = client.get(redirect_url)
    assert page.status_code == 200
    assert b"/10" in page.data
    assert b"football" in page.data.lower()
    assert b"could not complete marking" not in page.data.lower()
    with app.app_context():
        from database.database import query_one

        attempt = query_one("SELECT status, roleplay_score, total_score FROM attempts WHERE id = 1")
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json, examiner_comments FROM feedback WHERE attempt_id = 1")
    assert attempt["status"] == "completed"
    assert attempt["roleplay_score"] is not None
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert FOOTBALL in json.dumps(payload) or "football" in json.dumps(payload).lower()
    assert "football" in (feedback["strengths_json"] + feedback["examiner_comments"]).lower()
    assert any(FOOTBALL in p for p in fake.prompts)


def test_retry_marking_after_timeout(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(timeout=True))
    signup(client)
    redirect_url = _finish_roleplay(client, FOOTBALL)
    page = client.get(redirect_url)
    assert b"Retry marking" in page.data
    with app.app_context():
        from database.database import query_one

        before = query_one("SELECT status, roleplay_score FROM attempts WHERE id = 1")
    assert before["roleplay_score"] is None
    install_fake(monkeypatch, FakeAIProvider())
    retry = client.post("/exam/1/retry-marking", follow_redirects=True)
    assert retry.status_code == 200
    assert b"/10" in retry.data
    assert b"football" in retry.data.lower()
    with app.app_context():
        from database.database import query_one

        after = query_one("SELECT status, roleplay_score FROM attempts WHERE id = 1")
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
    assert after["status"] == "completed"
    assert after["roleplay_score"] is not None
    assert json.loads(marking["justification_json"])["unavailable"] is False


def test_no_fabricated_score_when_gemini_fails_on_finish(client, app, monkeypatch):
    install_fake(monkeypatch, FakeAIProvider(http_error=503))
    signup(client)
    redirect_url = _finish_roleplay(client, FOOTBALL)
    page = client.get(redirect_url)
    assert b"Retry marking" in page.data or b"could not complete marking" in page.data.lower()
    with app.app_context():
        from database.database import query_one

        attempt = query_one("SELECT status, roleplay_score, total_score FROM attempts WHERE id = 1")
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
    assert attempt["roleplay_score"] is None
    assert attempt["total_score"] is None
    if marking:
        payload = json.loads(marking["justification_json"] or "{}")
        assert payload.get("unavailable") is True or payload.get("total") is None


@pytest.mark.skipif(os.environ.get("SPEAKED_LIVE_GEMINI") != "1", reason="Set SPEAKED_LIVE_GEMINI=1 to call Gemini")
def test_live_gemini_roleplay_is_grounded(tmp_path):
    from app import create_app
    from config import TestConfig

    key = os.environ.get("GEMINI_API_KEY", "")
    assert key, "GEMINI_API_KEY is required for the live Gemini test"

    class Live(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'live-gemini.db'}"
        AI_PROVIDER = "gemini"
        GEMINI_API_KEY = key
        GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")

    application = create_app(Live)
    client = application.test_client()
    captured = {"prompts": [], "status": None, "model": None, "error": None}

    with application.app_context():
        from ai.ai_provider import get_ai

        provider = get_ai()
        original = provider.generate_text

        def wrapped(prompt, *args, **kwargs):
            captured["prompts"].append(prompt)
            try:
                text = original(prompt, *args, **kwargs)
            except Exception as exc:
                captured["status"] = getattr(provider, "last_http_status", None)
                captured["model"] = getattr(provider, "last_model_used", None)
                captured["error"] = getattr(provider, "last_error_redacted", str(exc)[:400])
                raise
            captured["status"] = getattr(provider, "last_http_status", None)
            captured["model"] = getattr(provider, "last_model_used", None)
            return text

        provider.generate_text = wrapped

    signup(client, email="live-gemini@example.com")
    redirect_url = _finish_roleplay(client, FOOTBALL)
    page = client.get(redirect_url)
    assert captured["prompts"], "Gemini was not called"
    assert FOOTBALL in captured["prompts"][0]
    assert "Do you" in captured["prompts"][0] or "EXAMINER PROMPT" in captured["prompts"][0]
    assert "4XES2" in captured["prompts"][0] or "Clearly communicated" in captured["prompts"][0]
    assert captured["status"] in {200, None} or captured["status"] == 200
    assert key not in json.dumps(captured)
    assert b"/10" in page.data
    assert b"football" in page.data.lower()
    with application.app_context():
        from database.database import query_one

        attempt = query_one("SELECT status, roleplay_score FROM attempts WHERE id = 1")
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json, examiner_comments FROM feedback WHERE attempt_id = 1")
    assert attempt["status"] == "completed"
    assert attempt["roleplay_score"] is not None
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert "football" in json.dumps(payload).lower()
    assert "football" in (feedback["strengths_json"] + feedback["examiner_comments"]).lower()
