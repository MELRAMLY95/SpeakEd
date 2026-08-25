from datetime import datetime
import logging
import re

from flask import flash, g, redirect, render_template, request, url_for

from ai.ai_provider import get_ai
from database.database import execute, query_all, query_one
from routes import information_bp
from routes.auth import login_required

logger = logging.getLogger(__name__)

MIN_INFORMATION_CHARS = 80
INFORMATION_SYSTEM = (
    "You write study notes for IGCSE ESL students. Use plain text with short headings "
    "and bullet points. Do not use markdown, hashtags, tables, or HTML."
)


def _plain_text(information: str) -> str:
    """Turn model markdown into readable plain text without destroying lists."""
    text = (information or "").replace("\r\n", "\n")
    text = re.sub(r"(?m)^#{1,6}\s*", "", text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"__([^_]+)__", r"\1", text)
    text = re.sub(r"`([^`]+)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"(?m)^\s*[-*+]\s+", "• ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _safe_ai_error(exc: Exception) -> str:
    text = str(exc)
    text = re.sub(r"key=[^&\s]+", "key=REDACTED", text, flags=re.I)
    return text[:400]


def _manual_template(topic: str) -> str:
    return (
        f"Information about {topic}\n\n"
        "Key Facts:\n"
        f"[Add key facts about {topic} here]\n\n"
        "Important Concepts:\n"
        f"[Explain important concepts related to {topic}]\n\n"
        "Examples:\n"
        f"[Provide examples that help understand {topic}]\n\n"
        "Explanations:\n"
        f"[Add detailed explanations that would be helpful for learning about {topic}]\n\n"
        "Additional Notes:\n"
        f"[Add any other relevant information about {topic}]"
    )


@information_bp.route("/")
@login_required
def home():
    """Display all gathered information for the current user."""
    search_query = request.args.get("search", "").strip()

    if search_query:
        gathered = query_all(
            "SELECT * FROM gathered_info WHERE user_id = ? AND (topic LIKE ? OR information LIKE ?) ORDER BY created_at DESC",
            (g.user["id"], f"%{search_query}%", f"%{search_query}%"),
        )
    else:
        gathered = query_all(
            "SELECT * FROM gathered_info WHERE user_id = ? ORDER BY created_at DESC",
            (g.user["id"],),
        )

    return render_template("information/information.html", gathered=gathered, search_query=search_query)


@information_bp.route("/new", methods=["GET", "POST"])
@login_required
def new():
    """Create new gathered information using AI."""
    if request.method == "POST":
        topic = request.form.get("topic", "").strip()
        if not topic:
            flash("Please enter a topic.", "error")
            return render_template("information/new.html")

        ai = get_ai()
        information = None
        if ai and ai.is_available():
            prompt = (
                f"Provide comprehensive information about the topic: {topic}. "
                "Include key facts, concepts, examples, and explanations that would be helpful "
                "for a student preparing IGCSE ESL speaking. Use plain text without markdown "
                "formatting, hashtags, or special characters. Organize the information with "
                "clear headings and bullet points for readability."
            )
            try:
                information = _plain_text(
                    ai.generate_text(
                        prompt,
                        max_tokens=4096,
                        temperature=0.7,
                        system=INFORMATION_SYSTEM,
                    )
                )
            except Exception as exc:
                logger.warning("AI information generation failed for %r: %s", topic, exc)
                flash(
                    "Could not generate information. "
                    f"{_safe_ai_error(exc)} "
                    "Try again in a minute, or pick a shorter topic.",
                    "error",
                )
                return render_template("information/new.html", topic=topic)

            if len(information) < MIN_INFORMATION_CHARS:
                flash("AI could not generate enough information. Please try again.", "error")
                return render_template("information/new.html", topic=topic)
        else:
            information = _manual_template(topic)
            flash(
                "AI is not available, so a template was created for you to fill in. "
                "Configure Gemini or Z.AI to generate notes automatically.",
                "info",
            )

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
