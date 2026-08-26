import json
from datetime import datetime, timezone

from flask import abort, g, redirect, render_template, request, url_for

from ai.feedback import recurring_themes
from ai.prompts import PromptBank
from database.database import execute, query_all, query_one
from routes import evaluation_bp
from routes.auth import login_required


def _bounded_int(raw, lo: int = 0, hi: int = 5) -> int:
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        abort(400)
    return max(lo, min(hi, value))


@evaluation_bp.route("/evaluation")
@login_required
def home():
    themes = recurring_themes(g.user["id"])
    latest = query_one(
        """SELECT a.*, f.examiner_comments, f.strengths_json, f.weaknesses_json, s.confidence, s.fluency,
                  s.difficulty, s.struggled_with, s.improve_next, s.satisfaction
           FROM attempts a
           LEFT JOIN feedback f ON f.attempt_id = a.id
           LEFT JOIN self_evaluations s ON s.attempt_id = a.id
           WHERE a.user_id = ? AND a.status = 'completed'
           ORDER BY a.completed_at DESC""",
        (g.user["id"],),
    )
    bank = PromptBank()
    skill = "development"
    if themes["recurring_weaknesses"]:
        joined = " ".join(themes["recurring_weaknesses"]).lower()
        if "accur" in joined:
            skill = "accuracy"
        elif "pict" in joined or "specul" in joined:
            skill = "speculation"
    coach = bank.choose_coach_prompts(skill)
    comparison = None
    if latest:
        comparison = {
            "student": latest["struggled_with"],
            "ai": latest["weaknesses_json"],
            "confidence": latest["confidence"],
            "weakest": latest["weakest_area"],
        }
    return render_template(
        "evaluation/evaluation.html",
        latest=latest,
        themes=themes,
        coach=coach,
        comparison=comparison,
        strengths=json.loads(latest["strengths_json"]) if latest and latest["strengths_json"] else [],
        weaknesses=json.loads(latest["weaknesses_json"]) if latest and latest["weaknesses_json"] else [],
    )


@evaluation_bp.route("/evaluation/<int:attempt_id>", methods=["GET", "POST"])
@login_required
def self_eval(attempt_id):
    attempt = query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, g.user["id"]))
    if attempt is None:
        abort(404)
    existing = query_one("SELECT * FROM self_evaluations WHERE attempt_id = ?", (attempt_id,))
    if request.method == "POST":
        execute(
            """INSERT INTO self_evaluations
               (attempt_id, confidence, fluency, difficulty, struggled_with, improve_next, satisfaction, student_notes, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(attempt_id) DO UPDATE SET
                 confidence=excluded.confidence,
                 fluency=excluded.fluency,
                 difficulty=excluded.difficulty,
                 struggled_with=excluded.struggled_with,
                 improve_next=excluded.improve_next,
                 satisfaction=excluded.satisfaction,
                 student_notes=excluded.student_notes""",
            (
                attempt_id,
                _bounded_int(request.form.get("confidence")),
                _bounded_int(request.form.get("fluency")),
                _bounded_int(request.form.get("difficulty")),
                (request.form.get("struggled_with") or "")[:500],
                (request.form.get("improve_next") or "")[:500],
                _bounded_int(request.form.get("satisfaction")),
                (request.form.get("student_notes") or "")[:800],
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        return redirect(url_for("evaluation.home"))
    return render_template("evaluation/evaluation.html", attempt=attempt, existing=existing, form_only=True)
