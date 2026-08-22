from datetime import datetime

from flask import flash, g, redirect, render_template, request, url_for

from ai.ai_provider import get_ai
from database.database import execute, query_all, query_one
from routes import information_bp
from routes.auth import login_required


@information_bp.route("/")
@login_required
def home():
    """Display all gathered information for the current user."""
    gathered = query_all(
        "SELECT * FROM gathered_info WHERE user_id = ? ORDER BY created_at DESC",
        (g.user["id"],),
    )
    return render_template("information/information.html", gathered=gathered)


@information_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Create new gathered information using AI."""
    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        if not topic:
            flash("Please enter a topic.", "error")
            return render_template("information/new.html")

        # Get AI provider and generate information
        ai = get_ai()
        if ai:
            try:
                prompt = f"Provide comprehensive information about the topic: {topic}. Include key facts, concepts, examples, and explanations that would be helpful for a student learning this subject."
                information = ai.generate_text(prompt, max_tokens=2000, temperature=0.7)
                
                if not information or len(information) < 50:
                    flash("AI could not generate sufficient information. Please try again.", "error")
                    return render_template("information/new.html")
            except Exception as e:
                print(f"AI generation error: {e}")
                flash("Error generating information. Please try again.", "error")
                return render_template("information/new.html")
        else:
            flash("AI service is not available. Please check your configuration.", "error")
            return render_template("information/new.html")

        # Store in database
        now = datetime.utcnow().isoformat()
        execute(
            "INSERT INTO gathered_info (user_id, topic, information, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (g.user["id"], topic, information, now, now),
        )

        flash("Information gathered successfully!", "success")
        return redirect(url_for("information.home"))

    return render_template("information/new.html")


@information_bp.route("/<int:info_id>")
@login_required
def view(info_id):
    """View a specific gathered information."""
    info = query_one(
        "SELECT * FROM gathered_info WHERE id = ? AND user_id = ?",
        (info_id, g.user["id"]),
    )
    if not info:
        flash("Information not found.", "error")
        return redirect(url_for("information.home"))
    return render_template("information/view.html", info=info)


@information_bp.route("/<int:info_id>/edit", methods=["GET", "POST"])
@login_required
def edit(info_id):
    """Edit gathered information."""
    info = query_one(
        "SELECT * FROM gathered_info WHERE id = ? AND user_id = ?",
        (info_id, g.user["id"]),
    )
    if not info:
        flash("Information not found.", "error")
        return redirect(url_for("information.home"))

    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        information = request.form.get("information", "").strip()

        if not topic or not information:
            flash("Topic and information are required.", "error")
            return render_template("information/edit.html", info=info)

        now = datetime.utcnow().isoformat()
        execute(
            "UPDATE gathered_info SET topic = ?, information = ?, updated_at = ? WHERE id = ? AND user_id = ?",
            (topic, information, now, info_id, g.user["id"]),
        )

        flash("Information updated successfully!", "success")
        return redirect(url_for("information.view", info_id=info_id))

    return render_template("information/edit.html", info=info)


@information_bp.route("/<int:info_id>/delete", methods=["POST"])
@login_required
def delete(info_id):
    """Delete gathered information."""
    info = query_one(
        "SELECT * FROM gathered_info WHERE id = ? AND user_id = ?",
        (info_id, g.user["id"]),
    )
    if not info:
        flash("Information not found.", "error")
        return redirect(url_for("information.home"))

    execute("DELETE FROM gathered_info WHERE id = ? AND user_id = ?", (info_id, g.user["id"]))
    flash("Information deleted successfully!", "success")
    return redirect(url_for("information.home"))
