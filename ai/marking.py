import json
import re
import random
from datetime import datetime, timezone
from pathlib import Path

from database.database import execute
from ai.ai_provider import get_ai

SCHEME_PATH = Path(__file__).resolve().parents[1] / "data" / "mark_scheme" / "4XES2_mark_scheme.json"

FILLERS = {"um", "uh", "er", "erm", "like", "you know", "kind of", "sort of"}
DEVELOPMENT = {"because", "for example", "for instance", "therefore", "however", "although", "so that", "since", "due to"}
COMPLEX = {"because", "although", "which", "that", "if", "when", "while", "whereas", "unless", "despite", "despite", "providing that"}
WEAK_EXPRESSIONS = {"i think", "maybe", "perhaps", "i guess", "probably", "kind of", "sort of"}
STRONG_EXPRESSIONS = {"certainly", "definitely", "clearly", "obviously", "undoubtedly", "without doubt"}
CONNECTORS = {"moreover", "furthermore", "in addition", "additionally", "on the other hand", "consequently", "as a result"}


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
    
    # More sophisticated analysis
    avg_word_length = sum(len(w) for w in words) / len(words) if words else 0
    sentence_variety = len(set(len(s.split()) for s in sentences)) if sentences else 0
    lower_words = set(words)
    has_examples = (
        any(phrase in clean.lower() for phrase in ["for example", "for instance", "such as"])
        or "like" in lower_words
    )
    # NOTE: "as" and "so" must be matched as whole words, not substrings —
    # `"as" in clean.lower()` used to match inside "was", "reason", "phase",
    # "increase" etc. and made has_reasoning true almost regardless of
    # content, which silently inflated communication scores.
    has_reasoning = (
        any(phrase in clean.lower() for phrase in ["because", "since", "due to"])
        or "as" in lower_words
        or "so" in lower_words
    )
    has_comparison = any(c in clean.lower() for c in ["more than", "less than", "better than", "worse than", "compared to"])
    has_speculation = any(s in clean.lower() for s in ["might", "could", "would", "perhaps", "maybe", "probably"])
    
    # Calculate complexity score
    complexity_score = (
        (complex_hits * 2) + 
        (connector_hits * 1.5) + 
        (development_hits * 1) + 
        (strong_hits * 1.5) - 
        (weak_hits * 1) - 
        (fillers * 0.5)
    )
    
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
        "complexity_score": round(complexity_score, 2),
    }


def _band_from_score(bands: list[dict], score: int) -> dict:
    for band in bands:
        if band["min"] <= score <= band["max"]:
            return band
    return bands[-1]


def _clip(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def mark_roleplay_with_ai(turns: list[dict], scheme: dict) -> dict:
    """Use AI to mark roleplay responses according to the exact 4XES2 markscheme."""
    ai = get_ai()
    if not ai or not ai.is_available():
        # Fallback to rule-based marking
        return mark_roleplay(turns, scheme)
    
    grid = scheme["task1_roleplay"]
    prompt_marks = []
    
    for index, turn in enumerate(turns[:5], start=1):
        response_text = turn.get("text", "")
        requires_question = turn.get("requires_question", False)
        
        # Build prompt using EXACT markscheme descriptors
        prompt = f"""You are an expert IGCSE English as a Second Language examiner marking Pearson Edexcel 4XES2 Unit 4 Speaking - Task 1 Role Play.

STUDENT RESPONSE: "{response_text}"

REQUIREMENT: {"The student MUST ask a question at the end." if requires_question else "No question required for this prompt."}

OFFICIAL PEARSON 4XES2 MARKING CRITERIA (apply EXACTLY these descriptors):

2 marks:
- Clearly communicated
- Appropriate within the context of the role play
- Unambiguous
- Pronunciation supports clear communication

1 mark:
- Partially clear/ambiguous OR partially appropriate within the context of the role play
- Pronunciation may affect clarity of communication

0 marks:
- No rewardable communication
- Highly ambiguous OR pronunciation prevents communication

MARKING INSTRUCTIONS:
- If a question was required but not asked, award 0 marks regardless of other quality
- Assess clarity of communication (is the message clear and unambiguous?)
- Assess appropriateness to the role-play context (does it fit the situation?)
- Assess pronunciation impact (does it support or hinder communication?)
- Use the EXACT descriptors above to determine the mark

Return ONLY a JSON object with this format:
{{"mark": 0/1/2, "reasoning": "brief explanation referencing the official descriptors above"}}"""

        try:
            ai_response = ai.generate_text(prompt, max_tokens=300, temperature=0.2, json_mode=True)
            # Parse JSON from AI response (still strip fences defensively —
            # some providers/models wrap JSON in ```json even in json_mode)
            ai_response = ai_response.strip()
            if ai_response.startswith("```json"):
                ai_response = ai_response[7:]
            if ai_response.endswith("```"):
                ai_response = ai_response[:-3]
            result = json.loads(ai_response)
            mark = _clip(int(result.get("mark", 1)), 0, 2)
            descriptor = next(d["descriptor"] for d in grid["per_prompt"] if d["mark"] == mark)
        except Exception as e:
            print(f"AI marking failed for roleplay turn {index}: {e}")
            # Fall back to the same well-calibrated rule-based logic used
            # when no AI is configured at all, instead of a weaker duplicate.
            # Calling the pure rule-based function (not mark_roleplay) avoids
            # re-entering the AI path and looping if the AI keeps failing.
            single = _mark_roleplay_rule_based([turn], scheme)
            mark = single["prompt_marks"][0]["mark"]
            descriptor = single["prompt_marks"][0]["descriptor"]
        
        prompt_marks.append({
            "prompt_index": index,
            "mark": mark,
            "max": 2,
            "descriptor": descriptor,
            "analysis": analyse_text(response_text, turn.get("metrics")),
            "evidence": response_text[:240],
        })
    
    total = sum(item["mark"] for item in prompt_marks)
    return {
        "task": "roleplay",
        "score": total,
        "max": grid["max_marks"],
        "prompt_marks": prompt_marks,
        "justification": "AI-assisted marking using official Pearson 4XES2 Task 1 mark scheme descriptors.",
    }


def mark_roleplay(turns: list[dict], scheme: dict) -> dict:
    """Use AI to mark roleplay responses according to the markscheme."""
    ai = get_ai()
    if ai and ai.is_available():
        return mark_roleplay_with_ai(turns, scheme)
    return _mark_roleplay_rule_based(turns, scheme)


def _mark_roleplay_rule_based(turns: list[dict], scheme: dict) -> dict:
    """Pure rule-based roleplay marking aligned with 4XES2 descriptors.

    Called directly (never via mark_roleplay) so that a failed AI call can
    fall back here without risking recursing back into the AI path again.
    """
    grid = scheme["task1_roleplay"]
    prompt_marks = []
    for index, turn in enumerate(turns[:5], start=1):
        analysis = analyse_text(turn.get("text", ""), turn.get("metrics"))
        
        # Aligned with 4XES2 descriptors
        word_count = analysis["word_count"]
        asked_question = analysis["asked_question"]
        requires_question = turn.get("requires_question")
        complexity = analysis["complexity_score"]
        filler_ratio = analysis["filler_count"] / max(word_count, 1)
        
        # Base mark determination using the ACTUAL 4XES2 Task 1 criteria:
        # clarity, appropriateness to context, unambiguity, pronunciation.
        # (Not "complexity" -- that's a Topic Talk / Picture linguistic-range
        # concept. A role-play answer like "I go to the cinema about twice a
        # month with my sister" is clear and complete and should score 2/2
        # even though it has no connectors like "because" or "however".)
        if word_count == 0:
            mark = 0  # No rewardable communication
        elif requires_question and not asked_question:
            mark = 0  # Required question missing -- fails the prompt regardless of quality
        elif word_count == 1:
            mark = 0  # A single word is too ambiguous to reliably answer a role-play prompt
        elif filler_ratio > 0.4:
            mark = 0  # Overwhelmed by fillers/hesitation -- communication breaks down
        elif word_count < 4 or filler_ratio > 0.2:
            mark = 1  # Partially clear / partially appropriate, or fillers affect clarity
        else:
            mark = 2  # Clear, complete, appropriate response to the prompt
        
        descriptor = next(d["descriptor"] for d in grid["per_prompt"] if d["mark"] == mark)
        prompt_marks.append(
            {
                "prompt_index": index,
                "mark": mark,
                "max": 2,
                "descriptor": descriptor,
                "analysis": analysis,
                "evidence": (turn.get("text") or "")[:240],
            }
        )
    total = sum(item["mark"] for item in prompt_marks)
    return {
        "task": "roleplay",
        "score": total,
        "max": grid["max_marks"],
        "prompt_marks": prompt_marks,
        "justification": (
            "Rule-based marking aligned with Pearson 4XES2 Task 1 descriptors: "
            "clearly communicated, appropriate, unambiguous, pronunciation supports communication."
        ),
    }


def _communication_score(analyses: list[dict], picture: bool) -> int:
    """Rule-based communication scoring aligned with 4XES2 descriptors."""
    if not analyses:
        return 0
    
    words = sum(a["word_count"] for a in analyses)
    avg_complexity = sum(a["complexity_score"] for a in analyses) / len(analyses)
    has_examples = sum(1 for a in analyses if a["has_examples"])
    has_reasoning = sum(1 for a in analyses if a["has_reasoning"])
    has_comparison = sum(1 for a in analyses if a["has_comparison"])
    has_speculation = sum(1 for a in analyses if a["has_speculation"])
    extended = sum(1 for a in analyses if a["word_count"] >= 25)
    short = sum(1 for a in analyses if a["word_count"] < 8)
    weak_lang = sum(1 for a in analyses if a["weak_expressions"] > 1)
    
    # Aligned with 4XES2 Communication & Content descriptors
    score = 0
    
    # Base score from extended sequences and detailed information
    if words >= 200 and extended >= 4 and short <= 1:
        score = 11  # 10-12 band: consistently extended sequences
    elif words >= 150 and extended >= 3:
        score = 8   # 7-9 band: usually extended sequences
    elif words >= 100 and extended >= 2:
        score = 5   # 4-6 band: some extended sequences
    elif words >= 60 and extended >= 1:
        score = 2   # 1-3 band: occasionally extended
    elif words >= 30:
        score = 1   # 1-3 band: limited but some extended
    else:
        score = 0   # 0 marks: no rewardable material
    
    # Adjustments for quality (aligned with descriptors)
    if avg_complexity > 3:
        score = min(12, score + 1)  # Better structures = clearer communication
    elif avg_complexity < 0.5:
        score = max(0, score - 2)  # Poor structures = message breaks down
    
    # Spontaneity indicators (reasoning, examples, speculation)
    if has_reasoning >= 2:
        score = min(12, score + 1)  # Spontaneous interaction
    if has_examples >= 2:
        score = min(12, score + 1)  # Detailed information
    if picture and has_speculation >= 1:
        score = min(12, score + 1)  # Picture: goes beyond description
    if picture and has_comparison >= 1:
        score = min(12, score + 1)  # Picture: development
    
    # Penalties for breakdown in communication
    if weak_lang >= 2:
        score = max(0, score - 2)  # Message breaks down
    if short >= 3:
        score = max(0, score - 2)  # Limited communication
    
    # Picture-specific: description vs development
    if picture and words < 50:
        score = max(0, score - 2)  # Limited development
    
    return _clip(score, 0, 12)


def _linguistic_score(analyses: list[dict]) -> int:
    """Rule-based linguistic scoring aligned with 4XES2 descriptors."""
    if not analyses:
        return 0
    
    words = sum(a["word_count"] for a in analyses) or 1
    diversity = sum(a["lexical_diversity"] for a in analyses) / len(analyses)
    complex_rate = sum(a["complex_markers"] for a in analyses) / words
    connector_rate = sum(a["connector_hits"] for a in analyses) / words
    avg_word_length = sum(a["avg_word_length"] for a in analyses) / len(analyses)
    sentence_variety = sum(a["sentence_variety"] for a in analyses) / len(analyses)
    strong_ratio = sum(a["strong_expressions"] for a in analyses) / words
    weak_ratio = sum(a["weak_expressions"] for a in analyses) / words
    filler_ratio = sum(a["filler_count"] for a in analyses) / words
    
    # Aligned with 4XES2 Linguistic Knowledge & Accuracy descriptors
    score = 0
    
    # Base score from vocabulary range and structure variety
    if diversity >= 0.7 and complex_rate >= 0.06 and words >= 120:
        score = 7  # 7-8 band: wide range of vocabulary, wide range of structures
    elif diversity >= 0.6 and complex_rate >= 0.05 and words >= 100:
        score = 6  # 5-6 band: range appropriate for most, good range of structures
    elif diversity >= 0.5 and complex_rate >= 0.04 and words >= 80:
        score = 5  # 5-6 band: appropriate vocabulary, good range
    elif diversity >= 0.4 and complex_rate >= 0.03 and words >= 50:
        score = 3  # 3-4 band: appropriate for some, adequate but predictable
    elif diversity >= 0.3 and words >= 30:
        score = 2  # 1-2 band: limited vocabulary
    elif diversity >= 0.2 and words >= 15:
        score = 1  # 1-2 band: limited range
    else:
        score = 0  # 0 marks: no rewardable material
    
    # Adjustments for linguistic quality (aligned with descriptors)
    if connector_rate >= 0.03:
        score = min(8, score + 1)  # Complex structures used effectively
    if strong_ratio >= 0.02:
        score = min(8, score + 1)  # Vocabulary consistently appropriate
    if avg_word_length >= 4.5:
        score = min(8, score + 1)  # Good vocabulary range
    if sentence_variety >= 4:
        score = min(8, score + 1)  # Wide range of structures
    
    # Significant penalties for poor linguistic quality (aligned with descriptors)
    if weak_ratio >= 0.04:
        score = max(0, score - 2)  # Frequent errors, both major and minor
    if filler_ratio >= 0.2:
        score = max(0, score - 2)  # Lapses in accuracy
    if diversity < 0.3:
        score = max(0, score - 1)  # Limited vocabulary
    if complex_rate < 0.02:
        score = max(0, score - 1)  # Limited structures, repetitive
    
    # Bonus for excellent linguistic features (7-8 band criteria)
    if diversity >= 0.75 and complex_rate >= 0.08:
        score = min(8, score + 1)  # Wide range, few lapses
    if connector_rate >= 0.05 and strong_ratio >= 0.03:
        score = min(8, score + 1)  # Consistently accurate, occasional minor errors
    
    return _clip(score, 0, 8)


def mark_extended_with_ai(task: str, turns: list[dict], scheme: dict) -> dict:
    """Use AI to mark extended tasks (topic talk or picture) according to exact 4XES2 markscheme."""
    ai = get_ai()
    if not ai or not ai.is_available():
        # Fallback to rule-based marking
        return mark_extended(task, turns, scheme)
    
    key = "task2_topic_talk" if task == "topic_talk" else "task3_picture"
    grid = scheme[key]
    analyses = [analyse_text(t.get("text", ""), t.get("metrics")) for t in turns if t.get("speaker") == "student"]
    
    # Get all student responses
    student_responses = [t.get("text", "") for t in turns if t.get("speaker") == "student"]
    all_responses_text = "\n\n".join([f"Response {i+1}: {r}" for i, r in enumerate(student_responses)])
    
    # Build prompt with exact markscheme descriptors
    if task == "topic_talk":
        comm_criteria = """10-12 marks (Communication and Content):
- Communicates detailed information relevant to the topic and questions
- Consistently extended sequences of speech
- Speaks and responds with ease to questions spontaneously, resulting in natural interaction
- Communication is clear with occasional ambiguity
- Pronunciation and intonation are consistently accurate and intelligible

7-9 marks:
- Communicates detailed information relevant to the topic and questions
- Usually with extended sequences of speech
- Speaks and responds to most questions spontaneously, resulting in mostly natural interaction
- Communication is generally clear but with some ambiguity
- Pronunciation and intonation are intelligible and mostly accurate

4-6 marks:
- Communicates information relevant to the topic and questions
- Some extended sequences of speech
- Speaks and responds to some questions spontaneously, interacting naturally for parts of the conversation
- Some examples of clear communication, the message sometimes breaks down
- Pronunciation and intonation are intelligible; inaccuracies sometimes impact clarity of communication

1-3 marks:
- Communicates straightforward information in relation to the topic and questions
- Occasionally extended sequences of speech
- Occasionally able to speak and respond spontaneously with some examples of natural interaction although often stilted
- Limited examples of clear communication, the message often breaks down
- Pronunciation and intonation are mostly intelligible; inaccuracies frequently affect clarity of communication

0 marks:
- No rewardable material

LINGUISTIC KNOWLEDGE AND ACCURACY:

7-8 marks:
- Wide range of vocabulary that is consistently appropriate to the task
- Wide range of straightforward and complex structures that are used effectively and appropriately with a few lapses
- Consistently accurate vocabulary and structures; occasional minor errors

5-6 marks:
- Range of vocabulary is appropriate for most of the response
- Good range of straightforward and some complex structures that are generally used effectively and appropriately
- Vocabulary and structures are accurate for most of the response; mostly minor errors with occasional major errors

3-4 marks:
- Range of vocabulary is appropriate for some of the response
- Adequate but predictable range of straightforward structures that are sometimes used effectively and appropriately
- Some accurate vocabulary and structures; errors occur, some of which are major

1-2 marks:
- Range of vocabulary is limited
- Limited range of simple structures, likely to be repetitive
- Limited accuracy of vocabulary and structures; frequent errors, both major and minor

0 marks:
- No rewardable material"""
        
        task_context = "Task 2 Topic Talk - Student is presenting on a chosen topic from Global Issues"
    else:
        comm_criteria = """10-12 marks (Communication and Content):
- Describes the picture and responds to questions in a consistently fluent and developed manner
- Speaks and responds with ease to questions spontaneously, resulting in natural interaction
- Communication is clear with occasional ambiguity
- Pronunciation and intonation are consistently accurate and intelligible

7-9 marks:
- Describes the picture and responds to questions in a mostly developed and fluent manner, with minimal hesitation and minimal prompting necessary
- Speaks and responds to most questions spontaneously, resulting in mostly natural interaction
- Communication is generally clear but with some ambiguity
- Pronunciation and intonation are intelligible and mostly accurate

4-6 marks:
- Describes the picture and responds to questions with occasional development, some hesitation, some prompting necessary
- Speaks and responds to some questions spontaneously, interacting naturally for parts of the conversation
- Some examples of clear communication, the message sometimes breaks down
- Pronunciation and intonation are intelligible; inaccuracies sometimes impact clarity of communication

1-3 marks:
- Describes the picture and responds to questions with limited development; hesitation is apparent and prompting is often necessary
- Occasionally able to speak and respond spontaneously, with some examples of natural interaction although often stilted
- Limited examples of clear communication, the message often breaks down
- Pronunciation and intonation are mostly intelligible; inaccuracies frequently affect clarity of communication

0 marks:
- No rewardable material

LINGUISTIC KNOWLEDGE AND ACCURACY:
(Same as Topic Talk - 7-8, 5-6, 3-4, 1-2, 0 marks)"""
        
        task_context = "Task 3 Picture Conversation - Student is discussing a photograph"
    
    prompt = f"""You are an expert IGCSE English as a Second Language examiner marking Pearson Edexcel 4XES2 Unit 4 Speaking - {task_context}.

STUDENT RESPONSES:
{all_responses_text}

OFFICIAL PEARSON 4XES2 MARKING CRITERIA (apply EXACTLY these descriptors):

{comm_criteria}

MARKING INSTRUCTIONS:
- Assess Communication and Content (12 marks max) using the descriptors above
- Assess Linguistic Knowledge and Accuracy (8 marks max) using the descriptors above
- Use the EXACT descriptors to determine the appropriate band
- Consider: vocabulary range, sentence structures, accuracy, fluency, spontaneity, pronunciation

Return ONLY a JSON object with this format:
{{"communication_score": 0-12, "linguistic_score": 0-8, "reasoning": "brief explanation referencing the official descriptors"}}"""

    try:
        ai_response = ai.generate_text(prompt, max_tokens=400, temperature=0.2, json_mode=True)
        ai_response = ai_response.strip()
        if ai_response.startswith("```json"):
            ai_response = ai_response[7:]
        if ai_response.endswith("```"):
            ai_response = ai_response[:-3]
        result = json.loads(ai_response)
        comm = _clip(int(result.get("communication_score", 4)), 0, 12)
        ling = _clip(int(result.get("linguistic_score", 2)), 0, 8)
    except Exception as e:
        print(f"AI marking failed for {task}: {e}")
        # Fallback to the pure rule-based scorers directly.
        comm = _communication_score(analyses, picture=task == "picture")
        ling = _linguistic_score(analyses)
    
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
        "justification": "AI-assisted marking using official Pearson 4XES2 mark scheme descriptors.",
    }


def mark_extended(task: str, turns: list[dict], scheme: dict) -> dict:
    """Use AI to mark extended tasks according to the markscheme."""
    ai = get_ai()
    if ai and ai.is_available():
        return mark_extended_with_ai(task, turns, scheme)
    
    # Fallback to rule-based marking aligned with 4XES2 descriptors
    key = "task2_topic_talk" if task == "topic_talk" else "task3_picture"
    grid = scheme[key]
    
    # Get student turns for this specific task
    task_turns = [t for t in turns if t.get("speaker") == "student"]
    
    # If no turns, return 0 but with proper structure
    if not task_turns:
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
        }
    
    analyses = [analyse_text(t.get("text", ""), t.get("metrics")) for t in task_turns]
    comm = _communication_score(analyses, picture=task == "picture")
    ling = _linguistic_score(analyses)
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
        "justification": (
            "Rule-based marking aligned with Pearson 4XES2 Task 2/3 descriptors: "
            "Communication (extended sequences, spontaneity, fluency) and Linguistic (vocabulary range, structures, accuracy)."
        ),
    }


def mark_attempt(attempt_id: int, payload: dict) -> dict:
    scheme = load_scheme()
    
    # Get the exam type from payload
    exam_type = payload.get("exam_type", "full")
    
    # Only mark the tasks that were actually attempted
    roleplay_turns = payload.get("roleplay_student_turns") or []
    topic_turns = payload.get("topic_turns") or []
    picture_turns = payload.get("picture_turns") or []
    
    # Mark only attempted tasks using AI if available
    roleplay = mark_roleplay(roleplay_turns, scheme) if roleplay_turns else {"score": 0, "max": 10, "prompt_marks": [], "justification": "Role play not attempted"}
    topic = mark_extended("topic_talk", topic_turns, scheme) if topic_turns else {"score": 0, "max": 20, "communication_and_content": {"score": 0, "max": 12}, "linguistic_knowledge_and_accuracy": {"score": 0, "max": 8}, "justification": "Topic talk not attempted"}
    picture = mark_extended("picture", picture_turns, scheme) if picture_turns else {"score": 0, "max": 20, "communication_and_content": {"score": 0, "max": 12}, "linguistic_knowledge_and_accuracy": {"score": 0, "max": 8}, "justification": "Picture conversation not attempted"}
    
    # Calculate total based on attempted tasks
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
    
    # Calculate areas only for attempted tasks
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
    }
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