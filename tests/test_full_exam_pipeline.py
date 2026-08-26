import json
import os
import re

import pytest

from tests.conftest import signup
from tests.fake_ai import FakeAIProvider, install_fake

PLASTIC = (
    "Plastic pollution is a serious global issue because single-use bottles stay in rivers for years. "
    "For example, after the weekend market in my city the water is full of packaging. "
    "I think a bottle deposit scheme would help, and schools should teach students not to drop litter."
)
TENNIS = (
    "I don't really enjoy football. I prefer tennis because it's more individual. "
    "In this picture I can see people using the space in their own way, and that reminds me of choosing a quieter sport."
)


def _answer_for(state: dict) -> str:
    stage = state.get("stage")
    prompt = state.get("prompt") or {}
    display = (prompt.get("display") or prompt.get("spoken") or "").lower()
    if stage == "warmup":
        return "My day is going well, thank you. I am a little nervous but I am ready to start."
    if stage == "roleplay":
        if prompt.get("ask_question") or "do you have a question" in display:
            return "How much does it cost, please?"
        if "often" in display or "how many" in display:
            return "I usually go about twice a month with my sister."
        if "film" in display or "see" in display or "watch" in display:
            return "I would like to see a science fiction film because the story is exciting."
        if "when" in display or "day" in display or "week" in display or "free" in display:
            return "I am free on Saturday evening after dinner."
        if "eat" in display or "food" in display or "snack" in display:
            return "I would like popcorn and a sandwich, please."
        if "skill" in display or "experience" in display or "interested" in display:
            return "I am interested because I want to learn office skills and help customers."
        return "Yes, I can do that on Saturday because I am free after lunch."
    if stage == "topic_talk":
        return PLASTIC
    if stage == "picture":
        title = ((state.get("cards") or {}).get("picture") or {}).get("title") or "the picture"
        return f"This photo is about {title}. {TENNIS}"
    return "I am ready to continue."


def _complete_full_exam(client, *, attempt_id: int = 1) -> dict:
    start = client.post(
        "/exam/start",
        data={"exam_type": "full", "mode": "full", "topic_title": "Plastic pollution"},
        follow_redirects=False,
    )
    assert start.status_code in {200, 302}
    begin = client.post(f"/exam/{attempt_id}/begin", follow_redirects=True)
    assert begin.status_code == 200
    captured = []
    redirect = None
    for _ in range(40):
        state = client.get(f"/exam/{attempt_id}/state").get_json()
        if state.get("stage") == "complete" or not state.get("prompt"):
            break
        answer = _answer_for(state)
        captured.append({
            "stage": state.get("stage"),
            "question": (state.get("prompt") or {}).get("display") or (state.get("prompt") or {}).get("spoken"),
            "answer": answer,
        })
        response = client.post(
            f"/exam/{attempt_id}/turn",
            json={"transcript": answer, "metrics": {"duration_ms": 8000, "word_count": 24}},
        )
        data = response.get_json() or {}
        if response.status_code != 200:
            raise AssertionError(f"turn failed {response.status_code}: {data}")
        if data.get("redirect"):
            redirect = data["redirect"]
            break
    assert redirect, "full exam did not complete"
    page = client.get(redirect)
    return {"redirect": redirect, "page": page, "turns": captured}


def test_full_exam_marks_all_sections_from_different_answers(client, app, monkeypatch):
    fake = install_fake(monkeypatch)
    signup(client)
    result = _complete_full_exam(client)
    page = result["page"]
    assert page.status_code == 200
    assert b"/50" in page.data
    assert b"could not complete marking" not in page.data.lower()
    assert b"What went well" in page.data or b"what went well" in page.data.lower()
    stages = [t["stage"] for t in result["turns"]]
    assert "warmup" in stages
    assert "roleplay" in stages
    assert "topic_talk" in stages
    assert "picture" in stages
    with app.app_context():
        from database.database import query_all, query_one

        attempt = query_one("SELECT status, roleplay_score, topic_talk_score, picture_score, total_score FROM attempts WHERE id = 1")
        marking = query_one("SELECT justification_json, scores_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json, examiner_comments FROM feedback WHERE attempt_id = 1")
        transcripts = query_all("SELECT stage, text FROM transcripts WHERE attempt_id = 1 AND speaker = 'student' ORDER BY id")
        warmup_n = query_one("SELECT COUNT(*) AS n FROM transcripts WHERE attempt_id = 1 AND stage = 'warmup'")
    topic_text = " ".join(row["text"] for row in transcripts if row["stage"] == "topic_talk")
    picture_text = " ".join(row["text"] for row in transcripts if row["stage"] == "picture")
    assert "plastic" in topic_text.lower()
    assert "tennis" in picture_text.lower()
    assert attempt["status"] == "completed"
    assert attempt["roleplay_score"] is not None
    assert attempt["topic_talk_score"] is not None
    assert attempt["picture_score"] is not None
    assert attempt["total_score"] == attempt["roleplay_score"] + attempt["topic_talk_score"] + attempt["picture_score"]
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False
    assert payload["max_total"] == 50
    assert 0 <= payload["roleplay"]["score"] <= 10
    assert 0 <= payload["topic_talk"]["score"] <= 20
    assert 0 <= payload["picture"]["score"] <= 20
    assert feedback is not None
    assert warmup_n["n"] >= 1
    marking_prompts = [p for p in fake.prompts if "4XES2" in p or "Role Play" in p or "COMMUNICATION AND CONTENT" in p]
    assert any(PLASTIC in p for p in marking_prompts)
    assert any(TENNIS in p or "tennis" in p.lower() for p in marking_prompts)
    assert any("CHOSEN TOPIC: Plastic pollution" in p for p in marking_prompts)
    assert any("PICTURE TASK:" in p for p in marking_prompts)
    assert any("Clearly communicated" in p for p in marking_prompts)
    assert payload.get("audio_assessed") is False
    assert payload.get("pronunciation_assessed") is False


def _redact(text: str, key: str) -> str:
    out = str(text or "")
    if key:
        out = out.replace(key, "[REDACTED]")
    return re.sub(r"key=[^&\s\"]+", "key=[REDACTED]", out)


@pytest.mark.skipif(os.environ.get("SPEAKED_LIVE_GEMINI") != "1", reason="Set SPEAKED_LIVE_GEMINI=1 to call Gemini")
def test_live_gemini_full_exam(tmp_path):
    from app import create_app
    from config import TestConfig

    key = os.environ.get("GEMINI_API_KEY", "")
    assert key, "GEMINI_API_KEY is required for the live Gemini test"

    class Live(TestConfig):
        DATABASE_URL = f"sqlite:///{tmp_path / 'live-full.db'}"
        AI_PROVIDER = "gemini"
        GEMINI_API_KEY = key
        GEMINI_MODEL = "gemini-3.5-flash-lite"

    application = create_app(Live)
    client = application.test_client()
    log = []

    with application.app_context():
        from ai.ai_provider import get_ai

        provider = get_ai()
        assert provider is not None and provider.name == "gemini"
        orig_post = provider._post_model

        def wrap_post(model, payload):
            stage = "unknown"
            try:
                user_text = (((payload.get("contents") or [{}])[0].get("parts") or [{}])[0].get("text") or "")
                if "Task 1 Role Play" in user_text:
                    stage = "mark_roleplay"
                elif "Task 2 Topic Talk" in user_text:
                    stage = "mark_topic_talk"
                elif "Task 3 Picture" in user_text:
                    stage = "mark_picture"
                elif "personalized feedback" in user_text.lower() or "STUDENT QUESTION/ANSWER RECORD" in user_text:
                    stage = "feedback"
                else:
                    stage = "other"
            except Exception:
                stage = "unknown"
            entry = {"stage": stage, "model": model, "ok": False, "http": None, "schema": None, "error": None}
            try:
                text = orig_post(model, payload)
                entry["ok"] = True
                entry["http"] = provider.last_http_status
                entry["model"] = provider.last_model_used or model
                stripped = text.strip()
                if stripped.startswith("{"):
                    entry["schema"] = "object"
                elif stripped.startswith("["):
                    entry["schema"] = "array"
                else:
                    entry["schema"] = "other"
                log.append(entry)
                return text
            except Exception as exc:
                entry["http"] = provider.last_http_status
                entry["error"] = _redact(provider.last_error_redacted or str(exc), key)[:400]
                log.append(entry)
                raise

        provider._post_model = wrap_post

    signup(client, email="live-full@example.com")
    result = _complete_full_exam(client)
    page = result["page"]
    body = page.get_data(as_text=True)
    assert key not in body
    assert key not in json.dumps(log)

    with application.app_context():
        from database.database import query_one

        attempt = query_one(
            "SELECT status, roleplay_score, topic_talk_score, picture_score, total_score FROM attempts WHERE id = 1"
        )
        marking = query_one("SELECT justification_json FROM markings WHERE attempt_id = 1")
        feedback = query_one("SELECT strengths_json, weaknesses_json, examiner_comments FROM feedback WHERE attempt_id = 1")

    assert attempt["status"] == "completed", f"attempt not completed: {attempt} log={log}"
    payload = json.loads(marking["justification_json"])
    assert payload["unavailable"] is False, payload.get("error")
    assert 0 <= attempt["roleplay_score"] <= 10
    assert 0 <= attempt["topic_talk_score"] <= 20
    assert 0 <= attempt["picture_score"] <= 20
    assert attempt["total_score"] == attempt["roleplay_score"] + attempt["topic_talk_score"] + attempt["picture_score"]
    blob = json.dumps(payload).lower() + (feedback["strengths_json"] + feedback["examiner_comments"]).lower()
    assert "plastic" in blob
    assert "tennis" in blob
    assert "plastic" in body.lower()
    assert "tennis" in body.lower()
    assert "/50" in body
    assert "could not complete marking" not in body.lower()
    stages = {e["stage"] for e in log if e["ok"]}
    assert "mark_roleplay" in stages
    assert "mark_topic_talk" in stages
    assert "mark_picture" in stages
    assert payload.get("audio_assessed") is False
    print(json.dumps({
        "calls": log,
        "scores": {
            "roleplay": attempt["roleplay_score"],
            "topic": attempt["topic_talk_score"],
            "picture": attempt["picture_score"],
            "total": attempt["total_score"],
        },
        "audio_assessed": payload.get("audio_assessed"),
        "call_count": len(log),
    }, indent=2))
