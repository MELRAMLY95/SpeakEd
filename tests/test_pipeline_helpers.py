import pytest

from ai.json_util import parse_json_object
from ai.speech import summarise_metrics, SpeechError, validate_audio_bytes
from tests.fake_ai import FakeAIProvider


def test_parse_json_object_recovers_fence():
    raw = '```json\n{"score": 2, "ok": true}\n```'
    assert parse_json_object(raw)["score"] == 2


def test_parse_json_object_rejects_garbage():
    with pytest.raises(ValueError):
        parse_json_object("not json at all")


def test_summarise_metrics_flags_missing_audio():
    note = summarise_metrics({"duration_ms": 1000, "word_count": 5})["pronunciation_note"]
    assert "No audio" in note or "not assessed" in note.lower()


def test_validate_audio_requires_app(app):
    with app.app_context():
        ext = validate_audio_bytes(b"\x00" * 400, "audio/webm", "turn.webm", duration_ms=1000)
        assert ext == ".webm"
        with pytest.raises(SpeechError) as exc:
            validate_audio_bytes(b"x", "audio/webm", "turn.webm", duration_ms=1000)
        assert exc.value.code == "empty_recording"


def test_feedback_json_differs_for_two_answers():
    ai = FakeAIProvider()
    short = ai.generate_json('Give feedback. STUDENT RESPONSE: "I like football because it is fun."')
    long = ai.generate_json(
        'Give feedback. STUDENT RESPONSE: "I enjoy football because it gives me the chance to work with other people."'
    )
    assert short["strengths"] != long["strengths"]
    assert short["recommendations"] != long["recommendations"]
