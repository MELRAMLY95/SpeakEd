import json

from flask import g, render_template

from ai.grades import estimate_grade
from database.database import query_all, query_one
from routes import dashboard_bp
from routes.auth import login_required


def _stats(user_id: int) -> dict:
    rows = query_all(
        "SELECT * FROM attempts WHERE user_id = ? AND status = 'completed' ORDER BY completed_at DESC",
        (user_id,),
    )
    full = [r for r in rows if r["exam_type"] == "full" and r["total_score"] is not None]
    scores = [r["total_score"] for r in full]
    latest = scores[0] if scores else None
    average = round(sum(scores) / len(scores), 1) if scores else None
    highest = max(scores) if scores else None
    improvement = None
    if len(scores) >= 2:
        improvement = scores[0] - scores[-1]
    areas = {}
    for row in full:
        if row["strongest_area"]:
            areas[row["strongest_area"]] = areas.get(row["strongest_area"], 0) + 1
    weakest_counts = {}
    for row in full:
        if row["weakest_area"]:
            weakest_counts[row["weakest_area"]] = weakest_counts.get(row["weakest_area"], 0) + 1
    return {
        "attempts": rows,
        "completed": len(rows),
        "latest": latest,
        "latest_grade": estimate_grade(latest, exam_type="full"),
        "average": average,
        "highest": highest,
        "highest_grade": estimate_grade(highest, exam_type="full"),
        "improvement": improvement,
        "strongest": max(areas, key=areas.get) if areas else None,
        "weakest": max(weakest_counts, key=weakest_counts.get) if weakest_counts else None,
        "recent": rows[:5],
        "chart_labels": [r["completed_at"][:10] if r["completed_at"] else "" for r in reversed(full[-8:])],
        "chart_scores": [r["total_score"] for r in reversed(full[-8:])],
    }


@dashboard_bp.route("/dashboard")
@login_required
def home():
    stats = _stats(g.user["id"])
    return render_template("dashboard/dashboard.html", stats=stats)
