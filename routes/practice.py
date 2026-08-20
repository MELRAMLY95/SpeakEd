from flask import g, jsonify, redirect, render_template, request, url_for

from ai.examiner import ExamEngine
from routes import practice_bp
from routes.auth import login_required
from services.image_fetcher import get_image_fetcher

engine = ExamEngine()
image_fetcher = get_image_fetcher()


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
    """Picture conversation practice with dynamic images."""
    # Get all picture cards with dynamic image URLs
    import json
    try:
        with open("data/prompts/picture_conversation.json", "r") as f:
            cards_data = json.load(f)
        
        # Handle different JSON structures
        cards = cards_data.get("cards", [])
        if not cards and isinstance(cards_data, list):
            cards = cards_data
        
        # Inject dynamic image URLs
        for card in cards:
            if isinstance(card, dict) and card.get("image"):
                if "homes" in card["image"]:
                    card["image"] = image_fetcher.get_image_for_topic("homes")
                elif "tourism" in card["image"]:
                    card["image"] = image_fetcher.get_image_for_topic("tourism")
                elif "school" in card["image"]:
                    card["image"] = image_fetcher.get_image_for_topic("school")
                elif "work" in card["image"]:
                    card["image"] = image_fetcher.get_image_for_topic("work")
        
        return render_template("practice/picture_conversation.html", cards=cards)
    except Exception as e:
        print(f"Error loading picture data: {e}")
        # Return fallback data
        return render_template("practice/picture_conversation.html", cards=[])


@practice_bp.route("/practice/refresh-images", methods=["POST"])
@login_required
def refresh_images():
    """Refresh all image URLs to get new random images."""
    new_urls = image_fetcher.refresh_all_images()
    return jsonify({"success": True, "urls": new_urls})


@practice_bp.route("/practice/start", methods=["POST"])
@login_required
def start():
    section = request.form.get("section") or "roleplay"
    topic = request.form.get("topic_title") or ""
    notes = request.form.get("topic_notes") or ""
    state = engine.start(g.user["id"], section, "practice", topic, notes)
    return redirect(url_for("exam.room", attempt_id=state["attempt_id"]))
