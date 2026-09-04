from flask import current_app, flash, g, jsonify, redirect, render_template, request, url_for

from ai.examiner import ExamEngine
from ai.prompts import PromptBank
from routes import practice_bp
from routes.auth import login_required
from plans import PRACTICE_EXAM
from security import consume_rate
from subscriptions import consume_usage
from services.image_fetcher import attach_picture_media, get_image_fetcher

engine = ExamEngine()
image_fetcher = get_image_fetcher()
prompt_bank = PromptBank()


@practice_bp.route("/practice")
@login_required
def home():
    return render_template("practice/practice.html")


@practice_bp.route("/practice/roleplay")
@login_required
def roleplay():
    return render_template("practice/roleplay.html")


@practice_bp.route("/practice/topic-talk")
@login_required
def topic_talk():
    return render_template("practice/topic_talk.html")


@practice_bp.route("/practice/picture")
@login_required
def picture():
    """Picture conversation practice with 4XES2 topic photographs."""
    cards = []
    for card in prompt_bank.picture.get("cards") or []:
        if not isinstance(card, dict):
            continue
        cards.append(attach_picture_media(card))
    return render_template("practice/picture_conversation.html", cards=cards)


@practice_bp.route("/practice/refresh-images", methods=["POST"])
@login_required
def refresh_images():
    """Refresh all image URLs to get new random images."""
    if consume_rate("refresh_images", str(g.user["id"]), 20, 3600):
        return jsonify({"success": False, "error": "Please wait before refreshing images again."}), 429
    new_urls = image_fetcher.refresh_all_images()
    return jsonify({"success": True, "urls": new_urls})


@practice_bp.route("/practice/start", methods=["POST"])
@login_required
def start():
    if consume_rate(
        "exam_start",
        str(g.user["id"]),
        int(current_app.config.get("EXAM_START_MAX") or 40),
        float(current_app.config.get("EXAM_START_WINDOW") or 3600),
    ):
        flash("Please wait before starting another attempt.", "error")
        return redirect(url_for("practice.home"))
    if not consume_usage(g.user, PRACTICE_EXAM):
        flash("You have used this month's Free speaking attempts. Upgrade to Premium for more practice this month.", "error")
        return redirect(url_for("billing.pricing"))
    section = request.form.get("section") or "roleplay"
    topic = request.form.get("topic_title") or ""
    notes = request.form.get("topic_notes") or ""
    picture_id = request.form.get("picture_id") or ""
    state = engine.start(g.user["id"], section, "practice", topic, notes, picture_id)
    return redirect(url_for("exam.room", attempt_id=state["attempt_id"]))
