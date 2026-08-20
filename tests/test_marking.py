from ai.marking import analyse_text, mark_roleplay, load_scheme


def test_roleplay_one_word_is_not_full_marks():
    scheme = load_scheme()
    result = mark_roleplay(
        [
            {"text": "Yes"},
            {"text": "Comedy"},
            {"text": "Tomorrow"},
            {"text": "Pizza"},
            {"text": "How much?", "requires_question": True},
        ],
        scheme,
    )
    assert result["max"] == 10
    assert result["prompt_marks"][0]["mark"] < 2
    assert result["score"] <= 8


def test_roleplay_developed_answers_can_reach_two():
    scheme = load_scheme()
    result = mark_roleplay(
        [
            {"text": "I go to the cinema about twice a month with my sister."},
            {"text": "I would like to see a science fiction film."},
            {"text": "I want to go on Saturday evening after dinner."},
            {"text": "I would like to eat popcorn and a sandwich."},
            {"text": "How much are the tickets, please?", "requires_question": True},
        ],
        scheme,
    )
    assert result["score"] == 10


def test_length_alone_does_not_create_analysis_error():
    short = analyse_text("I agree because recycling reduces waste, for example plastic bottles.")
    long = analyse_text("I think " + ("very " * 80) + "good.")
    assert short["development_markers"] >= 1
    assert long["word_count"] > short["word_count"]
