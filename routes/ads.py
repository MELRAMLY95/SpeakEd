"""Consent for non-personalized advertisements. Does not change Premium status."""

from flask import redirect, request, session, url_for

from ads import ads_enabled
from routes import ads_bp
from security import safe_next_path


@ads_bp.post("/ads/consent")
def consent():
    if ads_enabled():
        choice = (request.form.get("choice") or "").strip().lower()
        if choice in {"allow", "deny"}:
            session["ads_consent"] = choice
    return redirect(safe_next_path(request.form.get("next"), url_for("home")))
