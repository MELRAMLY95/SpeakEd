from flask import Blueprint

auth_bp = Blueprint("auth", __name__)
dashboard_bp = Blueprint("dashboard", __name__)
exam_bp = Blueprint("exam", __name__)
practice_bp = Blueprint("practice", __name__)
progress_bp = Blueprint("progress", __name__)
evaluation_bp = Blueprint("evaluation", __name__)
information_bp = Blueprint("information", __name__, url_prefix="/information")
