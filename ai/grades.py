"""Practice-only estimated 9–1 and A*–G grades from a speaking score.

4XES2 Unit 4 is one paper (50 marks, 25% of the International GCSE). These
bands are not Pearson series grade boundaries and must never be shown as an
official certificate grade.
"""

from __future__ import annotations

PAPER_MAX = {
    "full": 50,
    "roleplay": 10,
    "topic_talk": 20,
    "picture": 20,
}

# Minimum percentage of the paper maximum. Notional pairing:
# 9≈A*, 8–7≈A, 6≈B, 5–4≈C, 3≈D, 2≈E, 1≈F, U≈U.
_BANDS = (
    (90, "9", "A*"),
    (80, "8", "A"),
    (70, "7", "A"),
    (60, "6", "B"),
    (50, "5", "C"),
    (40, "4", "C"),
    (30, "3", "D"),
    (20, "2", "E"),
    (10, "1", "F"),
    (0, "U", "U"),
)

GRADE_DISCLAIMER = (
    "Estimated from this speaking paper for practice only. "
    "Not an official Pearson Edexcel certificate grade."
)


def paper_max(exam_type: str | None) -> int:
    return PAPER_MAX.get(exam_type or "full", 50)


def estimate_grade(
    score,
    *,
    max_total: int | None = None,
    exam_type: str | None = None,
) -> dict | None:
    """Return 9–1 and A*–G labels for a stored speaking score, or None."""
    if score is None:
        return None
    try:
        marks = int(score)
    except (TypeError, ValueError):
        return None
    ceiling = int(max_total) if max_total is not None else paper_max(exam_type)
    if ceiling <= 0:
        return None
    marks = max(0, min(marks, ceiling))
    percent = (marks / ceiling) * 100
    for minimum, nine, letter in _BANDS:
        if percent >= minimum:
            return {
                "nine": nine,
                "letter": letter,
                "percent": round(percent),
                "score": marks,
                "max_total": ceiling,
                "label": f"{nine} ({letter})",
                "disclaimer": GRADE_DISCLAIMER,
            }
    return None
