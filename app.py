import logging

from flask import Flask, g, render_template

from config import Config, validate_runtime_config
from database.database import close_db, engine_kind, init_db, query_one
from routes.auth import auth_bp
from routes.dashboard import dashboard_bp
from routes.evaluation import evaluation_bp
from routes.exam import exam_bp
from routes.information import information_bp
from routes.practice import practice_bp
from routes.progress import progress_bp


logger = logging.getLogger(__name__)


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)
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

    @app.before_request
    def load_user():
        from flask import session

        g.user = None
        user_id = session.get("user_id")
        if user_id:
            g.user = query_one("SELECT id, name, email, created_at FROM users WHERE id = ?", (user_id,))

    @app.context_processor
    def inject_globals():
        return {
            "current_user": g.get("user"),
            "disclaimer": (
                "AI-generated marks are estimates for practice purposes and are not official Pearson Edexcel marks or grades."
            ),
        }

    @app.route("/")
    def home():
        return render_template("home.html")

    @app.route("/privacy")
    def privacy():
        return render_template("privacy.html")

    with app.app_context():
        init_db()

    return app


app = create_app()

if __name__ == "__main__":
    app.run(debug=app.config.get("DEBUG", True))
