import json

from flask import abort, g, render_template

from database.database import query_all, query_one
from routes import progress_bp
from routes.auth import login_required
from routes.dashboard import _stats


@progress_bp.route("/progress")
@login_required
def home():
    stats = _stats(g.user["id"])
    return render_template("progress/progress.html", stats=stats)


@progress_bp.route("/history")
@login_required
def history():
    rows = query_all(
        "SELECT * FROM attempts WHERE user_id = ? ORDER BY started_at DESC",
        (g.user["id"],),
    )
    return render_template("progress/history.html", attempts=rows)


@progress_bp.route("/history/<int:attempt_id>")
@login_required
def attempt(attempt_id):
    row = query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, g.user["id"]))
    if row is None:
        abort(404)
    transcripts = query_all(
        "SELECT * FROM transcripts WHERE attempt_id = ? ORDER BY id",
        (attempt_id,),
    )
    marking_row = query_one("SELECT * FROM markings WHERE attempt_id = ?", (attempt_id,))
    feedback_row = query_one("SELECT * FROM feedback WHERE attempt_id = ?", (attempt_id,))
    self_eval = query_one("SELECT * FROM self_evaluations WHERE attempt_id = ?", (attempt_id,))
    marking = json.loads(marking_row["justification_json"]) if marking_row else {}
    feedback = None
    if feedback_row:
        feedback = {
            "strengths": json.loads(feedback_row["strengths_json"]),
            "weaknesses": json.loads(feedback_row["weaknesses_json"]),
            "recommendations": json.loads(feedback_row["recommendations_json"]),
            "examiner_comments": feedback_row["examiner_comments"],
        }
    return render_template(
        "progress/attempt.html",
        attempt=row,
        transcripts=transcripts,
        marking=marking,
        feedback=feedback,
        self_eval=self_eval,
    )
