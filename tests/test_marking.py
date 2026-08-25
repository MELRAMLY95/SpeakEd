from ai.marking import analyse_text, mark_attempt, mark_roleplay, load_scheme, marking_unavailable
from tests.fake_ai import FakeAIProvider


def test_roleplay_one_word_is_not_full_marks():
    scheme = load_scheme()
    ai = FakeAIProvider()
    result = mark_roleplay(
        [
            {"text": "Yes"},
            {"text": "Comedy"},
            {"text": "Tomorrow"},
            {"text": "Pizza"},
            {"text": "How much?", "requires_question": True},
        ],
        scheme,
        ai=ai,
    )
    assert result["max"] == 10
    assert result["prompt_marks"][0]["mark"] < 2
    assert result["score"] <= 8


def test_roleplay_developed_answers_can_reach_two():
    scheme = load_scheme()
    ai = FakeAIProvider()
    result = mark_roleplay(
        [
            {"text": "I go to the cinema about twice a month with my sister."},
            {"text": "I would like to see a science fiction film."},
            {"text": "I want to go on Saturday evening after dinner."},
            {"text": "I would like to eat popcorn and a sandwich."},
            {"text": "How much are the tickets, please?", "requires_question": True},
        ],
        scheme,
        ai=ai,
    )
    assert result["score"] == 10


def test_length_alone_does_not_create_analysis_error():
    short = analyse_text("I agree because recycling reduces waste, for example plastic bottles.")
    long = analyse_text("I think " + ("very " * 80) + "good.")
    assert short["development_markers"] >= 1
    assert long["word_count"] > short["word_count"]


def test_marking_unavailable_without_ai(app):
    with app.app_context():
        result = mark_attempt(1, {
            "exam_type": "roleplay",
            "roleplay_student_turns": [{"text": "I go to the cinema twice a month.", "question": "How often?"}],
            "topic_turns": [],
            "picture_turns": [],
        }, persist=False)
        assert result["unavailable"] is True
        assert result["total"] is None
        assert result["retry"] is True


def test_provider_failure_does_not_fabricate_score():
    scheme = load_scheme()
    ai = FakeAIProvider(fail=True)
    try:
        mark_roleplay([{"text": "I go to the cinema twice a month with my sister."}], scheme, ai=ai)
        raised = False
    except Exception:
        raised = True
    assert raised
    result = marking_unavailable("provider failure", scheme)
    assert result["unavailable"] is True
    assert result["roleplay"] is None


def test_invalid_json_does_not_become_a_score():
    scheme = load_scheme()
    ai = FakeAIProvider(invalid_json=True)
    try:
        mark_roleplay([{"text": "I go to the cinema twice a month with my sister."}], scheme, ai=ai)
        ok = False
    except Exception:
        ok = True
    assert ok


def test_audio_marking_failure_falls_back_to_transcript():
    scheme = load_scheme()
    ai = FakeAIProvider(supports_audio_flag=True, fail_audio=True)
    result = mark_roleplay(
        [{"text": "I go to the cinema twice a month with my sister."}],
        scheme,
        ai=ai,
        audio=(b"not-real-audio", "audio/webm"),
    )
    assert result["score"] >= 1
    assert ai.audio_calls >= 1


def test_two_answers_produce_different_marking_evidence():
    scheme = load_scheme()
    ai = FakeAIProvider()
    short = mark_roleplay(
        [{"text": "I like football because it is fun.", "question": "Why do you enjoy playing sport?"}],
        scheme,
        ai=ai,
    )
    long = mark_roleplay(
        [{
            "text": (
                "I enjoy football because it gives me the chance to work with other people. "
                "When I play with my friends, we have to communicate and make decisions quickly, "
                "which has helped me become more confident."
            ),
            "question": "Why do you enjoy playing sport?",
        }],
        scheme,
        ai=ai,
    )
    assert short["prompt_marks"][0]["evidence"] != long["prompt_marks"][0]["evidence"]
    assert short["prompt_marks"][0]["strengths"] != long["prompt_marks"][0]["strengths"]
    assert short["score"] <= long["score"]
