from flask import g, jsonify, redirect, render_template, request, url_for
import json
import logging

from ai.examiner import ExamEngine
from ai.speech import SpeechError, process_upload
from database.database import query_one
from routes import exam_bp
from routes.auth import login_required
from services.image_fetcher import get_image_fetcher

logger = logging.getLogger(__name__)

engine = ExamEngine()
image_fetcher = get_image_fetcher()


def _owned(attempt_id: int):
    return query_one("SELECT * FROM attempts WHERE id = ? AND user_id = ?", (attempt_id, g.user["id"]))


@exam_bp.route("/exam")
@login_required
def intro():
    return render_template("exam/intro.html")


@exam_bp.route("/exam/start", methods=["POST"])
@login_required
def start():
    exam_type = request.form.get("exam_type") or "full"
    mode = request.form.get("mode") or "full"
    topic = request.form.get("topic_title") or ""
    notes = request.form.get("topic_notes") or ""
    picture_id = request.form.get("picture_id") or ""
    state = engine.start(g.user["id"], exam_type, mode, topic, notes, picture_id)
    return redirect(url_for("exam.room", attempt_id=state["attempt_id"]))


@exam_bp.route("/exam/refresh-images", methods=["POST"])
@login_required
def refresh_images():
    """Refresh all image URLs to get new random images."""
    new_urls = image_fetcher.refresh_all_images()
    return jsonify({"success": True, "urls": new_urls})


@exam_bp.route("/exam/<int:attempt_id>")
@login_required
def room(attempt_id):
    attempt = _owned(attempt_id)
    if attempt is None:
        return redirect(url_for("dashboard.home"))
    template = {
        "preparation": "exam/intro.html",
        "warmup": "exam/warmup.html",
        "roleplay": "exam/roleplay.html",
        "topic_talk": "exam/topic_talk.html",
        "picture": "exam/picture_conversation.html",
        "complete": "exam/results.html",
    }.get(attempt["stage"], "exam/warmup.html")
    if attempt["status"] == "completed":
        return redirect(url_for("exam.results", attempt_id=attempt_id))
    state = engine.state(attempt_id, g.user["id"])
    
    # Inject dynamic image URLs for picture conversation
    if state and state.get("stage") == "picture" and state.get("cards"):
        try:
            picture_card = state["cards"].get("picture")
            if picture_card and isinstance(picture_card, dict) and picture_card.get("image"):
                # Extract topic from image path or use the picture card's topic
                original_image = picture_card["image"]
                if "homes" in original_image:
                    picture_card["image"] = image_fetcher.get_image_for_topic("homes")
                elif "tourism" in original_image:
                    picture_card["image"] = image_fetcher.get_image_for_topic("tourism")
                elif "school" in original_image:
                    picture_card["image"] = image_fetcher.get_image_for_topic("school")
                elif "work" in original_image:
                    picture_card["image"] = image_fetcher.get_image_for_topic("work")
        except Exception as e:
            print(f"Error injecting image URLs: {e}")
            # Continue without image injection
    
    return render_template(template, attempt=attempt, state=state)


@exam_bp.route("/exam/<int:attempt_id>/begin", methods=["POST"])
@login_required
def begin(attempt_id):
    if _owned(attempt_id) is None:
        return jsonify({"error": "Not found"}), 404
    state = engine.begin_speaking(attempt_id, g.user["id"])
    if request.accept_mimetypes.best == "application/json" or request.is_json:
        return jsonify(state)
    return redirect(url_for("exam.room", attempt_id=attempt_id))


@exam_bp.route("/exam/<int:attempt_id>/state")
@login_required
def state(attempt_id):
    if _owned(attempt_id) is None:
        return jsonify({"error": "Not found"}), 404
    return jsonify(engine.state(attempt_id, g.user["id"]))


@exam_bp.route("/exam/<int:attempt_id>/turn", methods=["POST"])
@login_required
def turn(attempt_id):
    if _owned(attempt_id) is None:
        return jsonify({"error": "Not found"}), 404
    audio_bytes = None
    audio_mime = None
    audio_ext = None
    if request.files.get("audio"):
        try:
            metrics = json.loads(request.form.get("metrics") or "{}")
        except json.JSONDecodeError:
            metrics = {}
        transcript = (request.form.get("transcript") or "")[:4000]
        try:
            processed = process_upload(request.files["audio"], metrics)
        except SpeechError as exc:
            return jsonify(exc.as_dict()), 400
        audio_bytes = processed["bytes"]
        audio_mime = processed["mime"]
        audio_ext = processed["ext"]
        metrics["audio_received"] = True
    else:
        data = request.get_json(silent=True) or {}
        transcript = (data.get("transcript") or "")[:4000]
        metrics = data.get("metrics") or {}
    try:
        result = engine.receive_turn(
            attempt_id,
            g.user["id"],
            transcript,
            metrics,
            audio_bytes=audio_bytes,
            audio_mime=audio_mime,
            audio_ext=audio_ext,
        )
    except Exception:
        # Log the full traceback server-side; the browser gets no internal detail.
        logger.exception("Saving turn failed for attempt %s", attempt_id)
        return jsonify({"error": "The answer could not be saved. Please retry.", "code": "database_failure", "retry": True}), 500
    if result.get("error"):
        status = 409 if result.get("code") == "duplicate_submission" else 400
        return jsonify(result), status
    if result.get("stage") == "complete":
        finished = engine.finish(attempt_id, g.user["id"])
        result["redirect"] = url_for("exam.results", attempt_id=attempt_id)
        result["unavailable"] = bool(finished.get("unavailable"))
        if finished.get("unavailable"):
            result["error"] = (finished.get("marking") or {}).get("error") or (finished.get("feedback") or {}).get("error")
    return jsonify(result)


@exam_bp.route("/exam/<int:attempt_id>/retry-marking", methods=["POST"])
@login_required
def retry_marking(attempt_id):
    if _owned(attempt_id) is None:
        return redirect(url_for("dashboard.home"))
    engine.retry_marking(attempt_id, g.user["id"])
    return redirect(url_for("exam.results", attempt_id=attempt_id))


@exam_bp.route("/exam/<int:attempt_id>/results")
@login_required
def results(attempt_id):
    attempt = _owned(attempt_id)
    if attempt is None:
        return redirect(url_for("dashboard.home"))
    if attempt["status"] == "in_progress":
        engine.finish(attempt_id, g.user["id"])
        attempt = _owned(attempt_id)
    marking_row = query_one("SELECT * FROM markings WHERE attempt_id = ?", (attempt_id,))
    feedback_row = query_one("SELECT * FROM feedback WHERE attempt_id = ?", (attempt_id,))
    marking = json.loads(marking_row["justification_json"]) if marking_row else {}
    feedback = None
    if feedback_row:
        feedback = {
            "strengths": json.loads(feedback_row["strengths_json"]),
            "weaknesses": json.loads(feedback_row["weaknesses_json"]),
            "lost_marks": json.loads(feedback_row["lost_marks_json"]),
            "recommendations": json.loads(feedback_row["recommendations_json"]),
            "examiner_comments": feedback_row["examiner_comments"],
        }
    state = engine.state(attempt_id, g.user["id"])
    return render_template("exam/results.html", attempt=attempt, marking=marking, feedback=feedback, state=state)


@exam_bp.route("/exam/<int:attempt_id>/feedback")
@login_required
def feedback(attempt_id):
    return redirect(url_for("exam.results", attempt_id=attempt_id))
