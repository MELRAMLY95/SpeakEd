import json
from datetime import datetime, timezone

from database.database import execute, query_all
from ai.ai_provider import get_ai


def _qa_blocks(transcripts: list[dict], payload: dict | None = None) -> str:
    payload = payload or {}
    blocks = []
    for row in transcripts:
        if row.get("speaker") != "student":
            continue
        question = row.get("prompt_id") or ""
        text = (row.get("text") or "").strip() or "(no response)"
        stage = row.get("stage") or ""
        blocks.append(f"Section: {stage}\nPrompt id: {question}\nStudent: {text}")
    if not blocks:
        topic = payload.get("topic_title") or ""
        return f"(no student speech captured)\nTopic: {topic}"
    return "\n\n".join(blocks)


def build_feedback(attempt_id: int, marking: dict, transcripts: list[dict], payload: dict | None = None) -> dict:
    if marking.get("unavailable"):
        return {
            "unavailable": True,
            "retry": True,
            "error": marking.get("error") or "Feedback was not generated because marking was unavailable.",
            "strengths": [],
            "weaknesses": [],
            "lost_marks": [],
            "recommendations": [],
            "examiner_comments": marking.get("error") or "",
            "next_step": "Retry marking when the AI examiner is available.",
        }
    ai = get_ai()
    if not ai or not ai.is_available():
        return {
            "unavailable": True,
            "retry": True,
            "error": "No AI examiner is available, so personalized feedback was not generated.",
            "strengths": [],
            "weaknesses": [],
            "lost_marks": [],
            "recommendations": [],
            "examiner_comments": "",
            "next_step": "Retry when an AI provider is configured.",
        }
    return build_feedback_with_ai(attempt_id, marking, transcripts, ai, payload)


def build_feedback_with_ai(attempt_id: int, marking: dict, transcripts: list[dict], ai, payload: dict | None = None) -> dict:
    qa = _qa_blocks(transcripts, payload)
    audio_note = (
        "Pronunciation/intonation may be mentioned only if marking.audio_assessed is true."
        if marking.get("audio_assessed")
        else "Do not claim pronunciation was assessed; the model did not receive audio."
    )
    prompt = f"""You are an IGCSE English as a Second Language examiner giving personalized feedback aligned with Pearson 4XES2.

STUDENT QUESTION/ANSWER RECORD:
{qa}

PERFORMANCE SCORES:
- Role play (Task 1): {marking.get('roleplay', {}).get('score', 0)}/10 marks
- Topic talk (Task 2): {marking.get('topic_talk', {}).get('score', 0)}/20 marks
- Picture conversation (Task 3): {marking.get('picture', {}).get('score', 0)}/20 marks
- Total score: {marking.get('total', 0)}/{marking.get('max_total', 50)} marks

{audio_note}

Use the student's actual words. Different answers must produce different feedback.
Do not invent things they did not say.
Do not give generic comments such as "Good job! Try to improve your vocabulary."

Return JSON:
{{"strengths": ["specific strength with evidence", "specific strength", "specific strength"], "weaknesses": ["specific weakness with evidence", "specific weakness", "specific weakness"], "recommendations": ["actionable improvement", "actionable improvement", "actionable improvement"]}}"""

    try:
        result = ai.generate_json(
            prompt,
            system="You are a Pearson Edexcel 4XES2 examiner. Return valid JSON only.",
            max_tokens=800,
            temperature=0.4,
        )
        strengths = result.get("strengths") or []
        weaknesses = result.get("weaknesses") or []
        recommendations = result.get("recommendations") or []
        if not isinstance(strengths, list) or not isinstance(weaknesses, list) or not isinstance(recommendations, list):
            raise ValueError("Feedback JSON lists were missing")
        strengths = [str(s) for s in strengths if str(s).strip()]
        weaknesses = [str(s) for s in weaknesses if str(s).strip()]
        recommendations = [str(s) for s in recommendations if str(s).strip()]
        if not strengths or not weaknesses or not recommendations:
            raise ValueError("Feedback JSON was incomplete")
    except Exception as exc:
        return {
            "unavailable": True,
            "retry": True,
            "error": f"The AI examiner did not return valid feedback. {exc}",
            "strengths": [],
            "weaknesses": [],
            "lost_marks": [],
            "recommendations": [],
            "examiner_comments": "",
            "next_step": "Retry feedback after marking succeeds.",
        }

    lost = []
    student_bits = [t["text"] for t in transcripts if t.get("speaker") == "student"]
    evidence = " ".join(student_bits)[:500]
    comments = (
        f"{marking['disclaimer']}\n\n"
        f"Strongest area: {marking['strongest_area']}. "
        f"Weakest area: {marking['weakest_area']}.\n\n"
        f"{'Audio was used in marking.' if marking.get('audio_assessed') else 'Audio was not used in marking; assessment is based on the transcript.'}\n\n"
        f"Evidence from your responses: {evidence or 'No student speech was captured.'}"
    )
    payload_out = {
        "unavailable": False,
        "strengths": strengths,
        "weaknesses": weaknesses,
        "lost_marks": lost,
        "recommendations": recommendations,
        "examiner_comments": comments,
        "next_step": recommendations[0],
    }
    execute(
        """INSERT INTO feedback (attempt_id, strengths_json, weaknesses_json, lost_marks_json, recommendations_json, examiner_comments, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(attempt_id) DO UPDATE SET
             strengths_json=excluded.strengths_json,
             weaknesses_json=excluded.weaknesses_json,
             lost_marks_json=excluded.lost_marks_json,
             recommendations_json=excluded.recommendations_json,
             examiner_comments=excluded.examiner_comments""",
        (
            attempt_id,
            json.dumps(strengths),
            json.dumps(weaknesses),
            json.dumps(lost),
            json.dumps(recommendations),
            comments,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    return payload_out


def recurring_themes(user_id: int) -> dict:
    rows = query_all(
        """SELECT f.weaknesses_json, f.recommendations_json, a.weakest_area
           FROM feedback f
           JOIN attempts a ON a.id = f.attempt_id
           WHERE a.user_id = ? AND a.status = 'completed'
           ORDER BY a.completed_at DESC LIMIT 12""",
        (user_id,),
    )
    counts = {}
    recs = []
    for row in rows:
        for item in json.loads(row["weaknesses_json"] or "[]"):
            counts[item] = counts.get(item, 0) + 1
        recs.extend(json.loads(row["recommendations_json"] or "[]"))
        if row["weakest_area"]:
            counts[row["weakest_area"]] = counts.get(row["weakest_area"], 0) + 1
    recurring = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return {
        "recurring_weaknesses": [k for k, v in recurring if v >= 2][:5],
        "recommended_practice": list(dict.fromkeys(recs))[:5],
    }
