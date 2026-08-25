import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from database.database import execute
from ai.ai_provider import get_ai
from ai.speech import collect_attempt_audio, read_audio_file

logger = logging.getLogger(__name__)

SCHEME_PATH = Path(__file__).resolve().parents[1] / "data" / "mark_scheme" / "4XES2_mark_scheme.json"

FILLERS = {"um", "uh", "er", "erm", "like", "you know", "kind of", "sort of"}
DEVELOPMENT = {"because", "for example", "for instance", "therefore", "however", "although", "so that", "since", "due to"}
COMPLEX = {"because", "although", "which", "that", "if", "when", "while", "whereas", "unless", "despite", "providing that"}
WEAK_EXPRESSIONS = {"i think", "maybe", "perhaps", "i guess", "probably", "kind of", "sort of"}
STRONG_EXPRESSIONS = {"certainly", "definitely", "clearly", "obviously", "undoubtedly", "without doubt"}
CONNECTORS = {"moreover", "furthermore", "in addition", "additionally", "on the other hand", "consequently", "as a result"}


class MarkingUnavailable(Exception):
    pass


def load_scheme() -> dict:
    with SCHEME_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


def analyse_text(text: str, metrics: dict | None = None) -> dict:
    metrics = metrics or {}
    clean = (text or "").strip()
    words = re.findall(r"[A-Za-z']+", clean.lower())
    sentences = [s.strip() for s in re.split(r"[.!?]+", clean) if s.strip()]
    unique = set(words)
    fillers = sum(1 for w in words if w in FILLERS)
    development_hits = sum(1 for marker in DEVELOPMENT if marker in clean.lower())
    complex_hits = sum(1 for w in words if w in COMPLEX)
    weak_hits = sum(1 for marker in WEAK_EXPRESSIONS if marker in clean.lower())
    strong_hits = sum(1 for marker in STRONG_EXPRESSIONS if marker in clean.lower())
    connector_hits = sum(1 for marker in CONNECTORS if marker in clean.lower())
    question = "?" in clean
    duration_ms = int(metrics.get("duration_ms") or 0)
    wpm = round((len(words) / (duration_ms / 60000)) if duration_ms else 0, 1)
    avg_word_length = sum(len(w) for w in words) / len(words) if words else 0
    sentence_variety = len(set(len(s.split()) for s in sentences)) if sentences else 0
    lower_words = set(words)
    has_examples = any(phrase in clean.lower() for phrase in ["for example", "for instance", "such as"])
    has_reasoning = (
        any(phrase in clean.lower() for phrase in ["because", "since", "due to"])
        or "as" in lower_words
        or "so" in lower_words
    )
    has_comparison = any(c in clean.lower() for c in ["more than", "less than", "better than", "worse than", "compared to"])
    has_speculation = any(s in clean.lower() for s in ["might", "could", "would", "perhaps", "maybe", "probably"])
    return {
        "word_count": len(words),
        "unique_words": len(unique),
        "sentence_count": len(sentences),
        "avg_sentence_length": round(len(words) / len(sentences), 1) if sentences else 0,
        "filler_count": fillers + int(metrics.get("filler_count") or 0),
        "pause_count": int(metrics.get("pause_count") or 0),
        "development_markers": development_hits,
        "complex_markers": complex_hits,
        "weak_expressions": weak_hits,
        "strong_expressions": strong_hits,
        "connector_hits": connector_hits,
        "asked_question": question,
        "duration_ms": duration_ms,
        "words_per_minute": wpm,
        "one_word": len(words) <= 1,
        "lexical_diversity": round(len(unique) / len(words), 2) if words else 0,
        "avg_word_length": round(avg_word_length, 2),
        "sentence_variety": sentence_variety,
        "has_examples": has_examples,
        "has_reasoning": has_reasoning,
        "has_comparison": has_comparison,
        "has_speculation": has_speculation,
        "audio_received": bool(metrics.get("audio_received") or metrics.get("audio_path")),
    }


def _band_from_score(bands: list[dict], score: int) -> dict:
    for band in bands:
        if band["min"] <= score <= band["max"]:
            return band
    return bands[-1]


def _clip(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _scheme_lines(bands: list[dict]) -> str:
    lines = []
    for band in bands:
        if "mark" in band:
            heading = f"{band['mark']} marks"
        elif band["min"] == band["max"]:
            heading = f"{band['min']} marks"
        else:
            heading = f"{band['min']}-{band['max']} marks"
        lines.append(f"{heading}: {band['descriptor']}")
    return "\n".join(lines)


def _format_qa(turns: list[dict]) -> str:
    blocks = []
    for index, turn in enumerate(turns, start=1):
        question = (turn.get("question") or "").strip() or "(question not recorded)"
        answer = (turn.get("text") or "").strip() or "(no response)"
        blocks.append(f"Turn {index}\nExaminer: {question}\nStudent: {answer}")
    return "\n\n".join(blocks) or "(no student turns)"


def _require_int(result: dict, key: str, low: int, high: int) -> int:
    if key not in result:
        raise MarkingUnavailable(f"AI marking JSON missing required field '{key}'.")
    try:
        value = int(result[key])
    except (TypeError, ValueError) as exc:
        raise MarkingUnavailable(f"AI marking JSON field '{key}' was not an integer.") from exc
    return _clip(value, low, high)


def _list_field(result: dict, key: str) -> list[str]:
    value = result.get(key) or []
    if not isinstance(value, list):
        return [str(value)]
    return [str(item) for item in value if str(item).strip()][:6]


def marking_unavailable(reason: str, scheme: dict | None = None) -> dict:
    scheme = scheme or load_scheme()
    return {
        "unavailable": True,
        "retry": True,
        "error": reason,
        "disclaimer": scheme["disclaimer"],
        "source": scheme["source"],
        "roleplay": None,
        "topic_talk": None,
        "picture": None,
        "total": None,
        "max_total": None,
        "strongest_area": None,
        "weakest_area": None,
        "audio_assessed": False,
        "pronunciation_assessed": False,
    }


def _empty_roleplay(scheme: dict) -> dict:
    grid = scheme["task1_roleplay"]
    return {
        "task": "roleplay",
        "score": 0,
        "max": grid["max_marks"],
        "prompt_marks": [],
        "justification": "Role play not attempted.",
        "evidence": [],
        "strengths": [],
        "weaknesses": [],
        "improvements": [],
    }


def _empty_extended(task: str) -> dict:
    return {
        "task": task,
        "score": 0,
        "max": 20,
        "communication_and_content": {
            "score": 0,
            "max": 12,
            "band": "0-0",
            "descriptor": "No rewardable material.",
        },
        "linguistic_knowledge_and_accuracy": {
            "score": 0,
            "max": 8,
            "band": "0-0",
            "descriptor": "No rewardable material.",
        },
        "analyses": [],
        "justification": "No student responses recorded for this task.",
        "evidence": [],
        "strengths": [],
        "weaknesses": [],
        "improvements": [],
    }


def _extended_result(task: str, grid: dict, comm: int, ling: int, analyses: list[dict], extra: dict) -> dict:
    comm_band = _band_from_score(grid["communication_and_content"], comm)
    ling_band = _band_from_score(grid["linguistic_knowledge_and_accuracy"], ling)
    return {
        "task": task,
        "score": comm + ling,
        "max": 20,
        "communication_and_content": {
            "score": comm,
            "max": 12,
            "band": f"{comm_band['min']}-{comm_band['max']}",
            "descriptor": comm_band["descriptor"],
        },
        "linguistic_knowledge_and_accuracy": {
            "score": ling,
            "max": 8,
            "band": f"{ling_band['min']}-{ling_band['max']}",
            "descriptor": ling_band["descriptor"],
        },
        "analyses": analyses,
        "justification": extra.get("reasoning") or extra.get("justification") or "",
        "evidence": extra.get("evidence") or [],
        "strengths": extra.get("strengths") or [],
        "weaknesses": extra.get("weaknesses") or [],
        "improvements": extra.get("improvements") or [],
    }


def _student_turns(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("speaker", "student") == "student"]


def _call_json(ai, prompt: str, system: str, max_tokens: int, audio: tuple[bytes | None, str | None]):
    audio_bytes, mime = audio
    if audio_bytes and ai.supports_audio():
        return ai.generate_json_with_audio(
            prompt,
            audio_bytes,
            mime or "audio/webm",
            system=system,
            max_tokens=max_tokens,
            temperature=0.1,
        )
    return ai.generate_json(prompt, system=system, max_tokens=max_tokens, temperature=0.1)


def mark_roleplay(turns: list[dict], scheme: dict, *, ai=None, audio=None) -> dict:
    ai = ai if ai is not None else get_ai()
    if not ai or not ai.is_available():
        raise MarkingUnavailable("No AI examiner is available, so role play was not marked.")
    grid = scheme["task1_roleplay"]
    if not turns:
        return _empty_roleplay(scheme)
    prompt_marks = []
    for index, turn in enumerate(turns[:5], start=1):
        response_text = turn.get("text", "")
        requires_question = turn.get("requires_question", False)
        question = (turn.get("question") or "").strip()
        analysis = analyse_text(response_text, turn.get("metrics"))
        turn_audio = audio
        if not turn_audio or not turn_audio[0]:
            turn_audio = read_audio_file((turn.get("metrics") or {}).get("audio_path"))
        audio_note = (
            "You have the student's original recording. You may comment on pronunciation only if it is audible."
            if turn_audio[0] and ai.supports_audio()
            else "You do NOT have audio. Do not claim to have assessed pronunciation or intonation from sound."
        )
        prompt = f"""Mark this IGCSE ESL (Pearson 4XES2) Task 1 Role Play turn.

EXAMINER PROMPT: "{question or '(not recorded)'}"
STUDENT RESPONSE: "{response_text}"
QUESTION REQUIRED: {"yes — award 0 if the student did not ask a question" if requires_question else "no"}
{audio_note}

OFFICIAL CRITERIA:
{_scheme_lines(grid["per_prompt"])}

Judge whether the answer clearly and appropriately addresses THIS examiner prompt.
Do not reward a fluent answer that does not fit the prompt.
Do not invent content the student did not say.
If the student response is empty, award 0.

Return JSON:
{{"mark": 0, "reasoning": "one sentence citing the descriptor", "evidence": ["short phrase from the student"], "strengths": ["specific strength"], "weaknesses": ["specific weakness"], "improvements": ["specific action"]}}"""
        try:
            result = _call_json(
                ai,
                prompt,
                "You are a Pearson Edexcel 4XES2 speaking examiner. Return valid JSON only.",
                280,
                turn_audio,
            )
        except Exception as exc:
            logger.warning("AI marking failed for roleplay turn %s: %s", index, exc)
            raise MarkingUnavailable("The AI examiner did not return a valid role-play mark. No score was recorded.") from exc
        mark = _require_int(result, "mark", 0, 2)
        if not (response_text or "").strip():
            mark = 0
        elif requires_question and not analysis["asked_question"]:
            mark = 0
        descriptor = next(d["descriptor"] for d in grid["per_prompt"] if d["mark"] == mark)
        prompt_marks.append({
            "prompt_index": index,
            "mark": mark,
            "max": 2,
            "descriptor": descriptor,
            "analysis": analysis,
            "evidence": _list_field(result, "evidence") or [(response_text or "")[:240]],
            "strengths": _list_field(result, "strengths"),
            "weaknesses": _list_field(result, "weaknesses"),
            "improvements": _list_field(result, "improvements"),
            "reasoning": str(result.get("reasoning") or ""),
        })
    total = sum(item["mark"] for item in prompt_marks)
    return {
        "task": "roleplay",
        "score": total,
        "max": grid["max_marks"],
        "prompt_marks": prompt_marks,
        "justification": "AI marking using official Pearson 4XES2 Task 1 mark scheme descriptors.",
        "evidence": [item["evidence"][0] for item in prompt_marks if item.get("evidence")],
        "strengths": [s for item in prompt_marks for s in item.get("strengths") or []][:5],
        "weaknesses": [s for item in prompt_marks for s in item.get("weaknesses") or []][:5],
        "improvements": [s for item in prompt_marks for s in item.get("improvements") or []][:5],
    }


def mark_extended(task: str, turns: list[dict], scheme: dict, *, ai=None, audio=None) -> dict:
    ai = ai if ai is not None else get_ai()
    if not ai or not ai.is_available():
        raise MarkingUnavailable("No AI examiner is available, so this task was not marked.")
    key = "task2_topic_talk" if task == "topic_talk" else "task3_picture"
    grid = scheme[key]
    student_turns = _student_turns(turns)
    if not student_turns:
        return _empty_extended(task)
    analyses = [analyse_text(t.get("text", ""), t.get("metrics")) for t in student_turns]
    if audio is None:
        last_bytes, last_mime, any_audio = collect_attempt_audio(student_turns)
        audio = (last_bytes, last_mime) if any_audio else (None, None)
    audio_note = (
        "You have a recording from this task. Assess pronunciation/intonation only from that audio."
        if audio and audio[0] and ai.supports_audio()
        else "You do NOT have audio. Do not claim to have assessed pronunciation or intonation from sound."
    )
    task_label = (
        "Task 2 Topic Talk (chosen Global Issues topic)"
        if task == "topic_talk"
        else "Task 3 Picture-based conversation"
    )
    prompt = f"""Mark this IGCSE ESL (Pearson 4XES2) {task_label} performance.

QUESTION AND ANSWER TURNS:
{_format_qa(student_turns)}

COMMUNICATION AND CONTENT (0-12):
{_scheme_lines(grid["communication_and_content"])}

LINGUISTIC KNOWLEDGE AND ACCURACY (0-8):
{_scheme_lines(grid["linguistic_knowledge_and_accuracy"])}

{audio_note}
Choose a mark inside a band only if the performance matches that band.
Do not award a high band for short or off-topic answers.
Do not invent content the student did not say.

Return JSON:
{{"communication_score": 0, "linguistic_score": 0, "reasoning": "one or two sentences", "evidence": ["short supporting phrase"], "strengths": ["specific strength"], "weaknesses": ["specific weakness"], "improvements": ["specific action"]}}"""
    try:
        result = _call_json(
            ai,
            prompt,
            "You are a Pearson Edexcel 4XES2 speaking examiner. Return valid JSON only.",
            400,
            audio or (None, None),
        )
    except MarkingUnavailable:
        raise
    except Exception as exc:
        logger.warning("AI marking failed for %s: %s", task, exc)
        raise MarkingUnavailable("The AI examiner did not return a valid mark. No score was recorded.") from exc
    comm = _require_int(result, "communication_score", 0, 12)
    ling = _require_int(result, "linguistic_score", 0, 8)
    extra = {
        "reasoning": str(result.get("reasoning") or ""),
        "evidence": _list_field(result, "evidence"),
        "strengths": _list_field(result, "strengths"),
        "weaknesses": _list_field(result, "weaknesses"),
        "improvements": _list_field(result, "improvements"),
    }
    return _extended_result(task, grid, comm, ling, analyses, extra)


def mark_attempt(attempt_id: int, payload: dict, *, persist: bool = True) -> dict:
    scheme = load_scheme()
    exam_type = payload.get("exam_type", "full")
    roleplay_turns = payload.get("roleplay_student_turns") or []
    topic_turns = payload.get("topic_turns") or []
    picture_turns = payload.get("picture_turns") or []
    ai = get_ai()
    needs_ai = bool(roleplay_turns or topic_turns or picture_turns)
    if needs_ai and (not ai or not ai.is_available()):
        return marking_unavailable("No AI examiner is available. Marks were not generated.", scheme)

    audio_assessed = False
    pronunciation_assessed = False
    if ai and ai.supports_audio():
        for group in (roleplay_turns, topic_turns, picture_turns):
            data, mime, any_audio = collect_attempt_audio(group)
            if any_audio and data:
                audio_assessed = True
                pronunciation_assessed = True
                break

    try:
        roleplay = mark_roleplay(roleplay_turns, scheme, ai=ai) if roleplay_turns else _empty_roleplay(scheme)
        topic = mark_extended("topic_talk", topic_turns, scheme, ai=ai) if topic_turns else _empty_extended("topic_talk")
        picture = mark_extended("picture", picture_turns, scheme, ai=ai) if picture_turns else _empty_extended("picture")
    except MarkingUnavailable as exc:
        return marking_unavailable(str(exc), scheme)

    if exam_type == "full":
        total = roleplay["score"] + topic["score"] + picture["score"]
        max_total = 50
    elif exam_type == "roleplay":
        total = roleplay["score"]
        max_total = 10
    elif exam_type == "topic_talk":
        total = topic["score"]
        max_total = 20
    elif exam_type == "picture":
        total = picture["score"]
        max_total = 20
    else:
        total = roleplay["score"] + topic["score"] + picture["score"]
        max_total = 50

    areas = {}
    if roleplay_turns:
        areas["Role play communication"] = roleplay["score"] / 10
    if topic_turns:
        areas["Topic talk communication and development"] = topic["communication_and_content"]["score"] / 12
        areas["Topic talk linguistic accuracy"] = topic["linguistic_knowledge_and_accuracy"]["score"] / 8
    if picture_turns:
        areas["Picture-based communication and development"] = picture["communication_and_content"]["score"] / 12
        areas["Picture-based linguistic accuracy"] = picture["linguistic_knowledge_and_accuracy"]["score"] / 8

    strongest = max(areas, key=areas.get) if areas else "N/A"
    weakest = min(areas, key=areas.get) if areas else "N/A"

    result = {
        "unavailable": False,
        "retry": False,
        "disclaimer": scheme["disclaimer"],
        "roleplay": roleplay,
        "topic_talk": topic,
        "picture": picture,
        "total": total,
        "max_total": max_total,
        "strongest_area": strongest,
        "weakest_area": weakest,
        "source": scheme["source"],
        "exam_type": exam_type,
        "audio_assessed": audio_assessed,
        "pronunciation_assessed": pronunciation_assessed,
    }
    if persist:
        execute(
            """INSERT INTO markings (attempt_id, analysis_json, scores_json, justification_json, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(attempt_id) DO UPDATE SET
                 analysis_json=excluded.analysis_json,
                 scores_json=excluded.scores_json,
                 justification_json=excluded.justification_json""",
            (
                attempt_id,
                json.dumps({"roleplay": roleplay.get("prompt_marks"), "topic": topic.get("analyses"), "picture": picture.get("analyses")}),
                json.dumps({"roleplay": roleplay["score"], "topic_talk": topic["score"], "picture": picture["score"], "total": total}),
                json.dumps(result),
                datetime.now(timezone.utc).isoformat(),
            ),
        )
    return result
