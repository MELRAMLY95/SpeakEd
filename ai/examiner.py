import json
from datetime import datetime, timezone

from ai.prompts import PromptBank
from ai.speech import cleanup_attempt_audio, save_turn_audio, summarise_metrics
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

    def start(self, user_id: int, exam_type: str, mode: str, topic_title: str = "", topic_notes: str = "", picture_id: str = "") -> dict:
        exam_type = exam_type if exam_type in {"full", "roleplay", "topic_talk", "picture"} else "full"
        mode = "practice" if mode == "practice" else "full"
        payload = {
            "exam_type": exam_type,
            "mode": mode,
            "topic_title": topic_title.strip(),
            "topic_notes": topic_notes.strip(),
            "turns": [],
            "used_followup_ids": [],
        }
        if exam_type in {"full", "roleplay"}:
            payload["roleplay"] = self.bank.choose_roleplay(user_id)
        if exam_type in {"full", "picture"}:
            if picture_id:
                chosen = self.bank.choose_picture_by_id(picture_id)
                self.bank.record_usage(user_id, chosen, "picture")
                payload["picture"] = chosen
            else:
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
            "marking_error": payload.get("marking_error"),
            "disclaimer": "AI-generated marks are estimates for practice purposes and are not official Pearson Edexcel marks or grades.",
        }

    def begin_speaking(self, attempt_id: int, user_id: int) -> dict:
        attempt = self._get(attempt_id, user_id)
        payload = _payload(attempt)
        if attempt["stage"] == "preparation":
            next_stage = "warmup" if attempt["exam_type"] == "full" else ("roleplay" if attempt["exam_type"] == "roleplay" else "picture")
            _save_payload(attempt_id, payload, stage=next_stage)
        return self.state(attempt_id, user_id)

    def receive_turn(
        self,
        attempt_id: int,
        user_id: int,
        transcript: str,
        metrics: dict | None = None,
        *,
        audio_bytes: bytes | None = None,
        audio_mime: str | None = None,
        audio_ext: str | None = None,
    ) -> dict:
        attempt = self._get(attempt_id, user_id)
        if attempt["status"] != "in_progress":
            return {"error": "This attempt has finished.", "code": "attempt_finished", "retry": False}
        payload = _payload(attempt)
        if payload.get("turn_lock"):
            return {"error": "Your previous answer is still being processed.", "code": "duplicate_submission", "retry": True}
        payload["turn_lock"] = True
        _save_payload(attempt_id, payload)
        try:
            return self._receive_turn_unlocked(
                attempt_id,
                user_id,
                attempt,
                payload,
                transcript,
                metrics,
                audio_bytes=audio_bytes,
                audio_mime=audio_mime,
                audio_ext=audio_ext,
            )
        finally:
            latest = query_one("SELECT payload_json FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, user_id))
            if latest:
                unlocked = json.loads(latest["payload_json"] or "{}")
                unlocked["turn_lock"] = False
                execute("UPDATE attempts SET payload_json = ? WHERE id = ?", (json.dumps(unlocked), attempt_id))

    def _receive_turn_unlocked(
        self,
        attempt_id: int,
        user_id: int,
        attempt,
        payload: dict,
        transcript: str,
        metrics: dict | None,
        *,
        audio_bytes: bytes | None,
        audio_mime: str | None,
        audio_ext: str | None,
    ) -> dict:
        stage = attempt["stage"]
        metrics_summary = summarise_metrics(metrics)
        text = (transcript or "").strip()
        ai = get_ai()

        if not text and audio_bytes:
            if ai and ai.supports_audio():
                try:
                    text = (ai.transcribe_audio(audio_bytes, audio_mime or "audio/webm") or "").strip()
                except Exception:
                    text = ""
                if not text:
                    return {
                        "error": "The recording could not be transcribed. Please record your answer again.",
                        "code": "transcription_unavailable",
                        "retry": True,
                    }
            else:
                return {
                    "error": "Speech could not be transcribed, and the current AI provider cannot listen to audio. Please record again in a browser with speech recognition.",
                    "code": "transcription_unavailable",
                    "retry": True,
                }
        if not text and not audio_bytes:
            return {"error": "No speech was captured. Please record your answer and try again.", "code": "empty_response", "retry": True}

        answered_prompt = self._current_prompt(payload, stage)
        audio_path = None
        if audio_bytes and audio_ext:
            audio_path = save_turn_audio(attempt_id, audio_bytes, audio_ext)
            metrics_summary["audio_received"] = True
            metrics_summary["audio_path"] = audio_path
        elif audio_bytes:
            metrics_summary["audio_received"] = True

        payload.setdefault("turns", []).append(
            {
                "stage": stage,
                "speaker": "student",
                "text": text,
                "metrics": metrics_summary,
                "prompt_id": (answered_prompt or {}).get("id"),
                "audio_path": audio_path,
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
        if stage in {"topic_talk", "picture"}:
            self._maybe_adapt_followup(payload, stage, answered_prompt, text)
        coaching = None
        if attempt["mode"] == "practice" and stage != "warmup":
            coaching = self._practice_note(text, stage, answered_prompt)
        next_stage = self._advance(payload, stage, attempt["exam_type"])
        _save_payload(attempt_id, payload, stage=next_stage)
        state = self.state(attempt_id, user_id)
        state["practice_note"] = coaching
        return state

    def finish(self, attempt_id: int, user_id: int) -> dict:
        from ai.feedback import build_feedback, feedback_from_marking
        from ai.marking import mark_attempt

        attempt = self._get(attempt_id, user_id)
        payload = _payload(attempt)
        marking = mark_attempt(
            attempt_id,
            self._marking_payload(payload, attempt_id, exam_type=attempt["exam_type"]),
        )
        if marking.get("unavailable"):
            payload["marking_error"] = marking.get("error")
            execute(
                """UPDATE attempts SET status='marking_unavailable', stage='complete', completed_at=?,
                   roleplay_score=NULL, topic_talk_score=NULL, picture_score=NULL, total_score=NULL,
                   strongest_area=NULL, weakest_area=NULL WHERE id=? AND user_id=?""",
                (_now(), attempt_id, user_id),
            )
            _save_payload(attempt_id, payload)
            return {"marking": marking, "feedback": None, "unavailable": True}
        # Scores must be stored before feedback. A later feedback failure used to
        # flip the attempt to marking_unavailable without writing these columns,
        # so the results page showed dashes even though marking had succeeded.
        self._store_scores(attempt, marking)
        transcripts = [dict(r) for r in query_all("SELECT * FROM transcripts WHERE attempt_id = ? ORDER BY id", (attempt_id,))]
        feedback = build_feedback(attempt_id, marking, transcripts, payload)
        if feedback.get("unavailable"):
            payload["feedback_error"] = feedback.get("error")
            feedback = feedback_from_marking(attempt_id, marking, transcripts)
        payload.pop("marking_error", None)
        _save_payload(attempt_id, payload)
        cleanup_attempt_audio(attempt_id)
        return {"marking": marking, "feedback": feedback, "unavailable": False}

    def restore_scores_from_marking(self, attempt):
        """Write score columns back when marking JSON was saved but attempts were cleared.

        A previous finish() path stored markings, then a later feedback failure
        set status=marking_unavailable and nulled the score columns. Results
        therefore showed dashes even though the examiner had already marked.
        """
        if attempt is None or attempt["status"] == "in_progress":
            return attempt
        scored = any(
            attempt[key] is not None
            for key in ("roleplay_score", "topic_talk_score", "picture_score", "total_score")
        )
        if scored:
            return attempt
        marking_row = query_one("SELECT justification_json FROM markings WHERE attempt_id = ?", (attempt["id"],))
        if marking_row is None:
            return attempt
        marking = json.loads(marking_row["justification_json"] or "{}")
        if not marking or marking.get("unavailable"):
            return attempt
        self._store_scores(attempt, marking)
        return query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt["id"], attempt["user_id"]))

    def _store_scores(self, attempt, marking: dict) -> None:
        exam_type = attempt["exam_type"]
        execute(
            """UPDATE attempts SET status='completed', stage='complete', completed_at=?,
               roleplay_score=?, topic_talk_score=?, picture_score=?, total_score=?,
               strongest_area=?, weakest_area=? WHERE id=? AND user_id=?""",
            (
                _now(),
                marking["roleplay"]["score"] if exam_type in {"full", "roleplay"} else None,
                marking["topic_talk"]["score"] if exam_type in {"full", "topic_talk"} else None,
                marking["picture"]["score"] if exam_type in {"full", "picture"} else None,
                marking["total"] if exam_type == "full" else self._partial_total(exam_type, marking),
                marking["strongest_area"],
                marking["weakest_area"],
                attempt["id"],
                attempt["user_id"],
            ),
        )

    def retry_marking(self, attempt_id: int, user_id: int) -> dict:
        attempt = self._get(attempt_id, user_id)
        if not self.needs_marking(attempt):
            return {"error": "This attempt cannot be re-marked yet.", "retry": False}
        execute(
            "UPDATE attempts SET status='in_progress', stage='complete' WHERE id=? AND user_id=?",
            (attempt_id, user_id),
        )
        return self.finish(attempt_id, user_id)

    def needs_marking(self, attempt, *, has_student_speech: bool | None = None) -> bool:
        """True when a finished speaking attempt has no saved marks.

        Covers role play, topic talk, picture conversation, and the full exam,
        including attempts left in_progress after a timeout during finish().
        """
        if attempt is None:
            return False
        if attempt["exam_type"] not in {"full", "roleplay", "topic_talk", "picture"}:
            return False
        if any(
            attempt[key] is not None
            for key in ("roleplay_score", "topic_talk_score", "picture_score", "total_score")
        ):
            return False
        finished = attempt["status"] in {"marking_unavailable", "completed"} or attempt["stage"] == "complete"
        if not finished:
            return False
        if has_student_speech is None:
            has_student_speech = self._has_student_speech(attempt)
        return bool(has_student_speech)

    def _has_student_speech(self, attempt) -> bool:
        row = query_one(
            "SELECT COUNT(*) AS n FROM transcripts WHERE attempt_id = ? AND speaker = 'student'",
            (attempt["id"],),
        )
        if row and int(row["n"] or 0) > 0:
            return True
        payload = _payload(attempt)
        return any(
            t.get("speaker") == "student" and (t.get("text") or "").strip()
            for t in payload.get("turns") or []
        )

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

    def _maybe_adapt_followup(self, payload: dict, stage: str, answered_prompt: dict | None, text: str) -> None:
        """Reorder remaining bank prompts using the student's last answer when AI is available."""
        if stage == "topic_talk":
            pool = payload.get("topic_followups") or []
            student_turns = [t for t in payload.get("turns", []) if t.get("stage") == stage and t.get("speaker") == "student"]
            asked = [t.get("prompt_id") for t in student_turns if t.get("prompt_id") and t.get("prompt_id") != "topic-start"]
            remaining = [p for p in pool if p.get("id") not in asked]
            chosen = self._choose_context_prompt(stage, answered_prompt, text, remaining)
            if not chosen:
                return
            used_items = [p for p in pool if p.get("id") in asked]
            rest = [p for p in remaining if p.get("id") != chosen.get("id")]
            payload["topic_followups"] = used_items + [chosen] + rest
        elif stage == "picture":
            card = payload.get("picture") or {}
            prompts = list(card.get("examiner_prompts") or [])
            student_n = sum(1 for t in payload.get("turns", []) if t.get("stage") == stage and t.get("speaker") == "student")
            if student_n < 1 or student_n >= len(prompts):
                return
            used_prompts = prompts[:student_n]
            remaining = prompts[student_n:]
            chosen = self._choose_context_prompt(stage, answered_prompt, text, remaining)
            if not chosen:
                return
            rest = [p for p in remaining if p.get("id") != chosen.get("id")]
            card["examiner_prompts"] = used_prompts + [chosen] + rest
            payload["picture"] = card

    def _choose_context_prompt(self, stage: str, answered_prompt: dict | None, text: str, remaining: list[dict]) -> dict | None:
        if not remaining:
            return None
        ai = get_ai()
        if not ai or not ai.is_available():
            return remaining[0]
        options = [{"id": p.get("id"), "prompt": p.get("prompt") or p.get("spoken")} for p in remaining]
        last_q = (answered_prompt or {}).get("display") or (answered_prompt or {}).get("spoken") or ""
        try:
            result = ai.generate_json(
                f"""You are a 4XES2 speaking examiner choosing the NEXT question from a fixed list.
Section: {stage}
Last question: {last_q}
Student answer: {text}
Remaining allowed questions: {json.dumps(options)}
Pick the most relevant unused question. Do not invent a new question. Do not invent what the student said.
Return JSON: {{"prompt_id": "{options[0]['id']}", "reason": "short reason"}}""",
                system="Return valid JSON only.",
                max_tokens=120,
                temperature=0.2,
            )
            pid = result.get("prompt_id")
            return next((p for p in remaining if p.get("id") == pid), remaining[0])
        except Exception:
            return remaining[0]

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
            spoken = p["spoken"]
            prev = prompts[n - 1]
            if prev.get("ask_question") and prev.get("brief_reply"):
                spoken = prev["brief_reply"] + " " + spoken
            return {
                "id": f"{card.get('id')}-{n}",
                "spoken": spoken,
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

    def _marking_payload(self, payload: dict, attempt_id: int | None = None, exam_type: str | None = None) -> dict:
        turns = list(payload.get("turns") or [])
        exam_type = exam_type or payload.get("exam_type", "full")

        def student(stage):
            items = [t for t in turns if t.get("stage") == stage and t.get("speaker") == "student"]
            if not items and attempt_id:
                rows = query_all(
                    """SELECT * FROM transcripts WHERE attempt_id = ? AND stage = ? AND speaker = 'student'
                       ORDER BY turn_index, id""",
                    (attempt_id, stage),
                )
                items = []
                for row in rows:
                    metrics = {}
                    raw = row.get("speech_metrics_json")
                    if raw:
                        try:
                            metrics = json.loads(raw)
                        except json.JSONDecodeError:
                            metrics = {}
                    items.append({
                        "text": row.get("text") or "",
                        "metrics": metrics,
                        "prompt_id": row.get("prompt_id"),
                        "audio_path": metrics.get("audio_path"),
                    })
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
                    "audio_path": t.get("audio_path") or (t.get("metrics") or {}).get("audio_path"),
                    "requires_question": requires,
                    "question": question,
                })
            return out

        return {
            "exam_type": exam_type,
            "roleplay_student_turns": student("roleplay") if exam_type in {"full", "roleplay"} else [],
            "topic_turns": student("topic_talk") if exam_type in {"full", "topic_talk"} else [],
            "picture_turns": student("picture") if exam_type in {"full", "picture"} else [],
        }

    def _practice_note(self, text: str, stage: str, prompt: dict | None = None) -> str:
        ai = get_ai()
        if ai and ai.is_available():
            return self._practice_note_with_ai(text, stage, ai, prompt)
        return "Your answer was saved. Personalized practice notes need an AI examiner."

    def _practice_note_with_ai(self, text: str, stage: str, ai, prompt: dict | None = None) -> str:
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
- Is specific to what they said in response to THIS question
- Identifies one strength OR one area for improvement
- References IGCSE criteria where relevant

Return ONLY the feedback comment, no other text."""
        try:
            return ai.generate_text(prompt_text, max_tokens=50, temperature=0.7).strip()
        except Exception:
            return "Your answer was saved, but a practice note could not be generated. Continue to the next prompt."
