"""Student speech is transcribed in the browser by default (Web Speech API)."""

import json


def summarise_metrics(metrics: dict | None) -> dict:
    metrics = metrics or {}
    duration_ms = int(metrics.get("duration_ms") or 0)
    pause_count = int(metrics.get("pause_count") or 0)
    filler_count = int(metrics.get("filler_count") or 0)
    words = int(metrics.get("word_count") or 0)
    wpm = round((words / (duration_ms / 60000)) if duration_ms else 0, 1)
    return {
        "duration_ms": duration_ms,
        "pause_count": pause_count,
        "filler_count": filler_count,
        "word_count": words,
        "words_per_minute": wpm,
        "pronunciation_note": (
            "Pronunciation is not scored from audio in this version. "
            "Clarity is inferred only from transcript completeness and student-reported issues."
        ),
    }


def parse_metrics(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
