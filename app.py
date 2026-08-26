import logging

from flask import Flask, g, jsonify, render_template, request, send_from_directory

from config import Config, validate_runtime_config
from database.database import close_db, engine_kind, init_db, query_one
from routes.ads import ads_bp
from routes.auth import auth_bp
from routes.billing import billing_bp
from routes.dashboard import dashboard_bp
from routes.evaluation import evaluation_bp
from routes.exam import exam_bp
from routes.information import information_bp
from routes.practice import practice_bp
from routes.progress import progress_bp
from security import apply_production_security, apply_security_headers, csrf_protect, csrf_token, redact_secrets


logger = logging.getLogger(__name__)


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
    apply_production_security(app)
    validate_runtime_config(app.config)
    logger.info(
        "SpeakEd starting with %s database (production=%s)",
        engine_kind(app.config.get("DATABASE_URL")),
        bool(app.config.get("IS_PRODUCTION")),
    )
    app.teardown_appcontext(close_db)

    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(exam_bp)
    app.register_blueprint(practice_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(evaluation_bp)
    app.register_blueprint(information_bp)
    app.register_blueprint(ads_bp)
    app.register_blueprint(billing_bp)

    @app.before_request
    def load_user():
        from flask import session

        g.user = None
        user_id = session.get("user_id")
        if user_id:
            g.user = query_one(
                "SELECT id, name, email, created_at, is_premium FROM users WHERE id = ?",
                (user_id,),
            )

    @app.before_request
    def enforce_csrf():
        return csrf_protect()

    @app.context_processor
    def inject_globals():
        from ads import adsense_script_allowed, build_ad_slot, publisher_id
        from subscriptions import is_premium

        show_adsense_script = adsense_script_allowed()
        return {
            "current_user": g.get("user"),
            "csrf_token": csrf_token(),
            "ad_context": build_ad_slot,
            "is_premium": is_premium(g.get("user")),
            "show_adsense_script": show_adsense_script,
            "adsense_client_id": publisher_id() if show_adsense_script else "",
            "disclaimer": (
                "AI-generated marks are estimates for practice purposes and are not official Pearson Edexcel marks or grades."
            ),
        }

    @app.after_request
    def set_security_headers(response):
        return apply_security_headers(response)

    if not app.config.get("TESTING"):
        @app.errorhandler(404)
        def not_found(_error):
            if _wants_json():
                return jsonify({"error": "Not found.", "code": "not_found"}), 404
            return ("Not found.", 404)

        @app.errorhandler(500)
        def server_error(error):
            logger.exception("Unhandled server error: %s", redact_secrets(error))
            if _wants_json():
                return jsonify({"error": "Something went wrong. Please try again.", "code": "server_error"}), 500
            return ("Something went wrong. Please try again.", 500)

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    @app.route("/ads.txt")
    @app.route("/ad.txt")
    def ads_txt():
        return send_from_directory(
            app.static_folder,
            "ads.txt",
            mimetype="text/plain; charset=utf-8",
        )

    with app.app_context():
        init_db()

    return app


def _wants_json() -> bool:
    if request.is_json:
        return True
    return (request.accept_mimetypes.best or "") == "application/json"


app = create_app()

if __name__ == "__main__":
    app.run(debug=bool(app.config.get("DEBUG")))
