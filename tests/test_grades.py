from ai.grades import estimate_grade, paper_max


def test_top_full_exam_is_nine_and_a_star():
    grade = estimate_grade(50, exam_type="full")
    assert grade["nine"] == "9"
    assert grade["letter"] == "A*"
    assert grade["label"] == "9 (A*)"


def test_mid_full_exam_is_six_and_b():
    grade = estimate_grade(34, exam_type="full")
    assert grade["nine"] == "6"
    assert grade["letter"] == "B"


def test_zero_is_ungraded():
    grade = estimate_grade(0, exam_type="full")
    assert grade["nine"] == "U"
    assert grade["letter"] == "U"


def test_missing_score_has_no_grade():
    assert estimate_grade(None, exam_type="full") is None


def test_roleplay_uses_paper_maximum():
    assert paper_max("roleplay") == 10
    grade = estimate_grade(9, exam_type="roleplay")
    assert grade["nine"] == "9"
    assert grade["letter"] == "A*"
    assert grade["max_total"] == 10


def test_grade_does_not_claim_official_certificate():
    grade = estimate_grade(45, exam_type="full")
    assert "not an official" in grade["disclaimer"].lower()
    assert "pearson" in grade["disclaimer"].lower()
