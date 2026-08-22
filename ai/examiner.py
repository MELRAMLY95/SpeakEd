import json
from datetime import datetime, timezone

from ai.prompts import PromptBank
from ai.speech import summarise_metrics
from ai.voice import examiner_voice_payload
from ai.ai_provider import get_ai
from database.database import execute, query_all, query_one

STAGES_FULL = ["preparation", "warmup", "roleplay", "topic_talk", "picture", "complete"]
STAGE_LABELS = {
    "preparation": "Preparation",
    "warmup": "Warm-up",
    "roleplay": "Task 1: Role play",
    "topic_talk": "Task 2: Topic talk",
    "picture": "Task 3: Picture-based conversation",
    "complete": "End of assessment",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _payload(attempt) -> dict:
    return json.loads(attempt["payload_json"] or "{}")


def _save_payload(attempt_id: int, payload: dict, stage: str | None = None, status: str | None = None):
    fields = ["payload_json = ?"]
    args = [json.dumps(payload)]
    if stage:
        fields.append("stage = ?")
        args.append(stage)
    if status:
        fields.append("status = ?")
        args.append(status)
    args.append(attempt_id)
    execute(f"UPDATE attempts SET {', '.join(fields)} WHERE id = ?", args)


class ExamEngine:
    def __init__(self, bank: PromptBank | None = None):
        self.bank = bank or PromptBank()

    def start(self, user_id: int, exam_type: str, mode: str, topic_title: str = "", topic_notes: str = "") -> dict:
        exam_type = exam_type if exam_type in {"full", "roleplay", "topic_talk", "picture"} else "full"
        mode = "practice" if mode == "practice" else "full"
        payload = {
            "exam_type": exam_type,
            "mode": mode,
            "topic_title": topic_title.strip(),
            "topic_notes": topic_notes.strip(),
            "turns": [],
        }
        if exam_type in {"full", "roleplay"}:
            payload["roleplay"] = self.bank.choose_roleplay(user_id)
        if exam_type in {"full", "picture"}:
            avoid = payload.get("roleplay", {}).get("topic_area")
            payload["picture"] = self.bank.choose_picture(user_id, avoid_topic=avoid)
        if exam_type in {"full", "topic_talk"}:
            title = topic_title.strip() or "your chosen Global Issues topic"
            payload["topic_followups"] = self.bank.choose_topic_followups(user_id, title)
        if exam_type == "full":
            payload["warmup"] = self.bank.choose_warmup(user_id)
            start_stage = "preparation"
        elif exam_type == "roleplay":
            start_stage = "preparation" if mode == "full" else "roleplay"
        elif exam_type == "topic_talk":
            start_stage = "topic_talk"
        else:
            start_stage = "preparation" if mode == "full" else "picture"

        cursor = execute(
            """INSERT INTO attempts (user_id, exam_type, mode, status, stage, payload_json, started_at)
               VALUES (?, ?, ?, 'in_progress', ?, ?, ?)""",
            (user_id, exam_type, mode, start_stage, json.dumps(payload), _now()),
        )
        return self.state(cursor.lastrowid, user_id)

    def state(self, attempt_id: int, user_id: int) -> dict:
        attempt = query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, user_id))
        if attempt is None:
            return {"error": "Attempt not found."}
        payload = _payload(attempt)
        stage = attempt["stage"]
        prompt = self._current_prompt(payload, stage)
        student_count = sum(1 for t in payload.get("turns", []) if t.get("stage") == stage and t.get("speaker") == "student")
        return {
            "attempt_id": attempt["id"],
            "exam_type": attempt["exam_type"],
            "mode": attempt["mode"],
            "status": attempt["status"],
            "stage": stage,
            "stage_label": STAGE_LABELS.get(stage, stage),
            "progress": self._progress(attempt["exam_type"], stage),
            "prompt": prompt,
            "voice": examiner_voice_payload(prompt.get("spoken") or "") if prompt else None,
            "cards": {
                "roleplay": payload.get("roleplay"),
                "picture": payload.get("picture"),
                "topic_title": payload.get("topic_title"),
                "topic_notes": payload.get("topic_notes"),
            },
            "awaiting_student": bool(prompt) and stage not in {"preparation", "complete"},
            "student_turns_in_stage": student_count,
            "disclaimer": "AI-generated marks are estimates for practice purposes and are not official Pearson Edexcel marks or grades.",
        }

    def begin_speaking(self, attempt_id: int, user_id: int) -> dict:
        attempt = self._get(attempt_id, user_id)
        payload = _payload(attempt)
        if attempt["stage"] == "preparation":
            next_stage = "warmup" if attempt["exam_type"] == "full" else ("roleplay" if attempt["exam_type"] == "roleplay" else "picture")
            _save_payload(attempt_id, payload, stage=next_stage)
        return self.state(attempt_id, user_id)

    def receive_turn(self, attempt_id: int, user_id: int, transcript: str, metrics: dict | None = None) -> dict:
        attempt = self._get(attempt_id, user_id)
        if attempt["status"] != "in_progress":
            return {"error": "This attempt has finished."}
        payload = _payload(attempt)
        stage = attempt["stage"]
        metrics_summary = summarise_metrics(metrics)
        text = (transcript or "").strip()

        # THE FIX: capture which prompt is actually being answered BEFORE
        # appending the new turn. _current_prompt() determines "current" by
        # counting how many student turns already exist in this stage --
        # calling it AFTER appending (the old order) meant it counted the
        # answer that was just given and returned the NEXT prompt instead,
        # so every stored prompt_id was one question ahead of the answer it
        # was attached to. This silently broke every downstream feature that
        # pairs an answer with its question (marking prompts, feedback
        # grounding, practice notes).
        answered_prompt = self._current_prompt(payload, stage)

        payload.setdefault("turns", []).append(
            {
                "stage": stage,
                "speaker": "student",
                "text": text,
                "metrics": metrics_summary,
                "prompt_id": (answered_prompt or {}).get("id"),
                "at": _now(),
            }
        )
        execute(
            """INSERT INTO transcripts (attempt_id, stage, turn_index, speaker, prompt_id, text, duration_ms, speech_metrics_json, created_at)
               VALUES (?, ?, ?, 'student', ?, ?, ?, ?, ?)""",
            (
                attempt_id,
                stage,
                len(payload["turns"]),
                (answered_prompt or {}).get("id"),
                text,
                metrics_summary.get("duration_ms"),
                json.dumps(metrics_summary),
                _now(),
            ),
        )
        coaching = None
        if attempt["mode"] == "practice" and stage != "warmup":
            coaching = self._practice_note(text, stage, answered_prompt)
        next_stage = self._advance(payload, stage, attempt["exam_type"])
        _save_payload(attempt_id, payload, stage=next_stage)
        state = self.state(attempt_id, user_id)
        state["practice_note"] = coaching
        return state

    def finish(self, attempt_id: int, user_id: int) -> dict:
        from ai.feedback import build_feedback
        from ai.marking import mark_attempt

        attempt = self._get(attempt_id, user_id)
        payload = _payload(attempt)
        marking = mark_attempt(attempt_id, self._marking_payload(payload))
        transcripts = [dict(r) for r in query_all("SELECT * FROM transcripts WHERE attempt_id = ? ORDER BY id", (attempt_id,))]
        feedback = build_feedback(attempt_id, marking, transcripts, payload)
        execute(
            """UPDATE attempts SET status='completed', stage='complete', completed_at=?,
               roleplay_score=?, topic_talk_score=?, picture_score=?, total_score=?,
               strongest_area=?, weakest_area=? WHERE id=? AND user_id=?""",
            (
                _now(),
                marking["roleplay"]["score"] if attempt["exam_type"] in {"full", "roleplay"} else None,
                marking["topic_talk"]["score"] if attempt["exam_type"] in {"full", "topic_talk"} else None,
                marking["picture"]["score"] if attempt["exam_type"] in {"full", "picture"} else None,
                marking["total"] if attempt["exam_type"] == "full" else self._partial_total(attempt["exam_type"], marking),
                marking["strongest_area"],
                marking["weakest_area"],
                attempt_id,
                user_id,
            ),
        )
        return {"marking": marking, "feedback": feedback}

    def _partial_total(self, exam_type: str, marking: dict) -> int:
        return {
            "roleplay": marking["roleplay"]["score"],
            "topic_talk": marking["topic_talk"]["score"],
            "picture": marking["picture"]["score"],
        }.get(exam_type, marking["total"])

    def _get(self, attempt_id: int, user_id: int):
        attempt = query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, user_id))
        if attempt is None:
            raise ValueError("Attempt not found.")
        return attempt

    def _progress(self, exam_type: str, stage: str) -> dict:
        if exam_type == "full":
            order = STAGES_FULL
        elif exam_type == "roleplay":
            order = ["preparation", "roleplay", "complete"]
        elif exam_type == "topic_talk":
            order = ["topic_talk", "complete"]
        else:
            order = ["preparation", "picture", "complete"]
        index = order.index(stage) if stage in order else 0
        return {"step": index + 1, "total": len(order), "order": order}

    def _current_prompt(self, payload: dict, stage: str) -> dict | None:
        student_turns = [t for t in payload.get("turns", []) if t.get("stage") == stage and t.get("speaker") == "student"]
        n = len(student_turns)
        if stage == "preparation":
            return {
                "id": "prep",
                "spoken": (
                    "You have 10 minutes to prepare for the role play and the picture task. "
                    "You may make notes. You must not use a dictionary. When you are ready, start the examination."
                ),
                "display": "Prepare using the candidate cards. Do not write on the stimulus.",
            }
        if stage == "warmup":
            questions = payload.get("warmup") or []
            if n >= len(questions):
                return None
            q = questions[n]
            spoken = q["prompt"] if n else (
                "Before we begin the test, we are going to do a warm-up activity with some non-test questions that will not be marked. "
                + q["prompt"]
            )
            return {**q, "spoken": spoken, "display": q["prompt"], "unmarked": True}
        if stage == "roleplay":
            card = payload.get("roleplay") or {}
            prompts = card.get("examiner_prompts") or []
            if n == 0:
                intro = card.get("examiner_intro") or ""
                first = prompts[0]["spoken"] if prompts else ""
                return {
                    "id": f"{card.get('id')}-0",
                    "spoken": intro + " " + first,
                    "display": first,
                    "candidate_bullet": (card.get("candidate_prompts") or [None])[0],
                    "unseen": prompts[0].get("unseen") if prompts else False,
                    "ask_question": prompts[0].get("ask_question") if prompts else False,
                }
            if n >= len(prompts):
                return None
            p = prompts[n]
            return {
                "id": f"{card.get('id')}-{n}",
                "spoken": p["spoken"],
                "display": p["spoken"],
                "candidate_bullet": (card.get("candidate_prompts") or [None] * 5)[n],
                "unseen": p.get("unseen"),
                "ask_question": p.get("ask_question"),
            }
        if stage == "topic_talk":
            followups = payload.get("topic_followups") or []
            if n == 0:
                return {
                    "id": "topic-start",
                    "spoken": (
                        "We are now going to complete Task 2. This task is the topic talk on the topic you have chosen. "
                        "You will have 2 minutes to speak. When you have finished, I will ask you some questions about your topic talk. "
                        "You may start now."
                    ),
                    "display": "Deliver your prepared topic talk (up to 2 minutes).",
                    "timer": 120,
                }
            if n > len(followups):
                return None
            q = followups[n - 1]
            spoken = q["prompt"]
            if n == 1:
                spoken = "Thank you. You have been speaking for 2 minutes. I will now ask you some follow-up questions. " + spoken
            return {**q, "spoken": spoken, "display": q["prompt"]}
        if stage == "picture":
            card = payload.get("picture") or {}
            prompts = card.get("examiner_prompts") or []
            if n >= len(prompts):
                return None
            p = prompts[n]
            spoken = p["spoken"]
            if n == 0:
                spoken = (card.get("examiner_intro") or "") + " " + spoken
            return {**p, "spoken": spoken, "display": p["spoken"], "image": card.get("image")}
        return None

    def _advance(self, payload: dict, stage: str, exam_type: str) -> str:
        student_turns = [t for t in payload.get("turns", []) if t.get("stage") == stage and t.get("speaker") == "student"]
        n = len(student_turns)
        if stage == "warmup" and n >= len(payload.get("warmup") or []):
            return "roleplay" if exam_type == "full" else "complete"
        if stage == "roleplay":
            needed = len((payload.get("roleplay") or {}).get("examiner_prompts") or [])
            if n >= needed:
                return "topic_talk" if exam_type == "full" else "complete"
        if stage == "topic_talk":
            needed = 1 + min(4, len(payload.get("topic_followups") or []))
            if n >= needed:
                return "picture" if exam_type == "full" else "complete"
        if stage == "picture":
            needed = len((payload.get("picture") or {}).get("examiner_prompts") or [])
            if n >= needed:
                return "complete"
        return stage

    def _marking_payload(self, payload: dict) -> dict:
        turns = payload.get("turns") or []

        def student(stage):
            items = [t for t in turns if t.get("stage") == stage and t.get("speaker") == "student"]
            roleplay_card = payload.get("roleplay") or {}
            roleplay_prompts = roleplay_card.get("examiner_prompts") or []
            picture_card = payload.get("picture") or {}
            picture_prompts = picture_card.get("examiner_prompts") or []
            topic_followups = payload.get("topic_followups") or []
            out = []
            for i, t in enumerate(items):
                requires = False
                question = ""
                if stage == "roleplay" and i < len(roleplay_prompts):
                    requires = bool(roleplay_prompts[i].get("ask_question"))
                    question = roleplay_prompts[i].get("spoken", "")
                elif stage == "topic_talk":
                    prompt_id = t.get("prompt_id")
                    if prompt_id == "topic-start":
                        question = "Deliver your topic talk."
                    else:
                        question = next((q.get("prompt", "") for q in topic_followups if q.get("id") == prompt_id), "")
                elif stage == "picture":
                    prompt_id = t.get("prompt_id")
                    question = next((p.get("spoken", "") for p in picture_prompts if p.get("id") == prompt_id), "")
                out.append({
                    "text": t.get("text", ""),
                    "metrics": t.get("metrics") or {},
                    "requires_question": requires,
                    "question": question,
                })
            return out

        # Ensure we only get turns for stages that were actually attempted
        return {
            "exam_type": payload.get("exam_type", "full"),
            "roleplay_student_turns": student("roleplay") if payload.get("roleplay") else [],
            "topic_turns": student("topic_talk") if payload.get("topic_followups") else [],
            "picture_turns": student("picture") if payload.get("picture") else [],
        }

    def _practice_note(self, text: str, stage: str, prompt: dict | None = None) -> str:
        """Generate dynamic, content-aware practice feedback using AI if available."""
        ai = get_ai()
        if ai and ai.is_available():
            return self._practice_note_with_ai(text, stage, ai, prompt)
        
        # Fallback to rule-based feedback
        words = text.split()
        word_count = len(words)
        text_lower = text.lower()
        question_text = (prompt or {}).get("display") or (prompt or {}).get("spoken") or ""
        
        # Sophisticated content analysis
        feedback_messages = []
        
        # Length analysis
        if word_count < 5:
            feedback_messages.append("Your answer was very brief. Try to expand with more detail.")
        elif word_count < 10:
            feedback_messages.append("Good start, but add more information to fully develop your answer.")
        elif word_count > 30:
            feedback_messages.append("You gave a detailed response. In exams, balance detail with time management.")
        
        # Content analysis based on stage
        if stage == "roleplay":
            # Only this specific prompt's actual requirement matters -- most
            # roleplay prompts do NOT require a question, so checking for
            # "?" unconditionally on every turn (the previous behaviour)
            # produced an irrelevant note on 4 out of 5 answers.
            requires_question = bool((prompt or {}).get("ask_question"))
            if requires_question:
                if "?" in text:
                    feedback_messages.append("Good job asking your question as required by this prompt.")
                else:
                    feedback_messages.append("This prompt required you to ask a question — remember to do that next time.")
            
            if "please" in text_lower or "could you" in text_lower:
                feedback_messages.append("Polite language is appropriate for role-play situations.")
        
        elif stage == "topic_talk":
            if "because" in text_lower:
                feedback_messages.append("Good use of reasoning with 'because'.")
            elif "for example" in text_lower or "such as" in text_lower:
                feedback_messages.append("Nice use of examples to support your points.")
            else:
                feedback_messages.append("Try to add 'because' and examples to support your opinions.")
            
            if "i think" in text_lower or "in my opinion" in text_lower:
                feedback_messages.append("Clear expression of personal opinion.")
            
            if "first" in text_lower or "second" in text_lower or "finally" in text_lower:
                feedback_messages.append("Good use of sequencing words to structure your answer.")
        
        elif stage == "picture":
            if "in the picture" in text_lower or "i can see" in text_lower:
                feedback_messages.append("Good description of what you see in the image.")
            else:
                feedback_messages.append("Remember to describe what you can see in the picture.")
            
            if "might" in text_lower or "could" in text_lower or "would" in text_lower:
                feedback_messages.append("Good use of speculation about the image.")
            else:
                feedback_messages.append("Try to speculate about what might be happening using 'might' or 'could'.")
        
        if not feedback_messages:
            return "Good response. Keep practicing to improve your speaking skills."
        if question_text:
            return f"(On \"{question_text}\") " + " ".join(feedback_messages)
        return " ".join(feedback_messages)
    
    def _practice_note_with_ai(self, text: str, stage: str, ai, prompt: dict | None = None) -> str:
        """Use AI to generate personalized practice feedback."""
        stage_context = {
            "roleplay": "Task 1 Role Play: Student is in a specific role-play situation",
            "topic_talk": "Task 2 Topic Talk: Student is presenting on a chosen topic",
            "picture": "Task 3 Picture Conversation: Student is discussing a photograph"
        }.get(stage, "Speaking practice")

        question_text = (prompt or {}).get("display") or (prompt or {}).get("spoken") or "(question not available)"
        requirement_note = ""
        if stage == "roleplay" and (prompt or {}).get("ask_question"):
            requirement_note = "\nIMPORTANT: This specific prompt required the student to ask a question of the examiner."

        prompt_text = f"""You are an IGCSE English as a Second Language examiner giving brief, helpful feedback during practice.

CONTEXT: {stage_context}
EXAMINER ASKED: "{question_text}"{requirement_note}
STUDENT RESPONSE: "{text}"

Provide ONE concise, encouraging feedback comment (max 25 words) that:
- Is specific to what they said in response to THIS question (not a generic comment that could apply to any answer)
- Identifies one strength OR one area for improvement
- Is constructive and helpful
- References IGCSE criteria where relevant

Return ONLY the feedback comment, no other text."""

        try:
            return ai.generate_text(prompt_text, max_tokens=50, temperature=0.7).strip()
        except Exception as e:
            print(f"AI practice note failed: {e}")
            return "Good response. Keep practicing to improve your speaking skills."