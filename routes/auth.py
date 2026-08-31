import hashlib
import hmac
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps

from flask import current_app, flash, g, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database.database import execute, query_one
from routes import auth_bp
from security import (
    auth_is_rate_limited,
    clear_auth_failures,
    record_auth_failure,
    safe_next_path,
)

logger = logging.getLogger(__name__)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            flash("Please sign in to continue.", "info")
            return redirect(url_for("auth.login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def _now():
    return datetime.now(timezone.utc)


def _valid_password(password: str) -> bool:
    return len(password) >= 8


def _login_user(user_id) -> None:
    session.clear()
    session["user_id"] = user_id
    session["_session_version"] = str(current_app.config.get("SESSION_VERSION") or "1")
    session.permanent = True


def _owner_email() -> str:
    return (current_app.config.get("OWNER_EMAIL") or "").strip().lower()


def _private_mode() -> bool:
    return bool(current_app.config.get("PRIVATE_MODE"))


def _is_owner_email(email: str) -> bool:
    owner = _owner_email()
    candidate = (email or "").strip().lower()
    return bool(owner) and candidate == owner


def ensure_owner_account(app=None) -> None:
    """Create or refresh the single operator account used while the site is private."""
    app = app or current_app
    if not app.config.get("PRIVATE_MODE"):
        return
    email = (app.config.get("OWNER_EMAIL") or "").strip().lower()
    password = app.config.get("OWNER_PASSWORD") or ""
    name = (app.config.get("OWNER_NAME") or "Owner").strip() or "Owner"
    if not email or not EMAIL_RE.match(email) or not _valid_password(password):
        logger.warning("PRIVATE_MODE is on but OWNER_EMAIL/OWNER_PASSWORD are not set; nobody can sign in.")
        return
    existing = query_one("SELECT id FROM users WHERE email = ?", (email,))
    stamp = _now().isoformat()
    hashed = generate_password_hash(password)
    if existing:
        execute(
            "UPDATE users SET password_hash = ?, name = ?, updated_at = ? WHERE id = ?",
            (hashed, name, stamp, existing["id"]),
        )
        return
    execute(
        "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (name, email, hashed, stamp, stamp),
    )


@auth_bp.route("/signup", methods=["GET", "POST"])
def signup():
    if g.user:
        return redirect(url_for("dashboard.home"))
    if _private_mode():
        if request.method == "POST":
            record_auth_failure("signup")
            flash("New accounts are not being created yet.", "error")
            return render_template("auth/signup.html", signup_closed=True), 403
        return render_template("auth/signup.html", signup_closed=True)
    if request.method == "POST":
        if auth_is_rate_limited("signup"):
            flash("Too many account attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/signup.html"), 429
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        errors = []
        if len(name) < 2:
            errors.append("Please enter your name.")
        if not EMAIL_RE.match(email):
            errors.append("Please enter a valid email address.")
        if not _valid_password(password):
            errors.append("Password must be at least 8 characters.")
        if password != confirm:
            errors.append("Passwords do not match.")
        if query_one("SELECT id FROM users WHERE email = ?", (email,)):
            errors.append("An account with this email already exists.")
        if errors:
            record_auth_failure("signup")
            for item in errors:
                flash(item, "error")
            return render_template("auth/signup.html")
        stamp = _now().isoformat()
        execute(
            "INSERT INTO users (name, email, password_hash, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (name, email, generate_password_hash(password), stamp, stamp),
        )
        user = query_one("SELECT id FROM users WHERE email = ?", (email,))
        _login_user(user["id"])
        clear_auth_failures("signup")
        return redirect(url_for("dashboard.home"))
    return render_template("auth/signup.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if g.user:
        return redirect(url_for("dashboard.home"))
    if request.method == "POST":
        if auth_is_rate_limited("login"):
            flash("Too many sign-in attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/login.html"), 429
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        user = query_one("SELECT * FROM users WHERE email = ?", (email,))
        allowed = user is not None and check_password_hash(user["password_hash"], password)
        if _private_mode():
            allowed = allowed and _is_owner_email(email)
        # Same public message either way so the form never reveals which emails exist.
        if not allowed:
            record_auth_failure("login")
            logger.warning("Login failed for a sign-in attempt")
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html")
        _login_user(user["id"])
        clear_auth_failures("login")
        nxt = safe_next_path(request.args.get("next"), url_for("dashboard.home"))
        return redirect(nxt)
    return render_template("auth/login.html")


@auth_bp.route("/logout", methods=["GET", "POST"])
def logout():
    if request.method == "GET" and current_app.config.get("CSRF_PROTECT", True):
        return redirect(url_for("home"))
    session.clear()
    flash("You have signed out.", "info")
    return redirect(url_for("home"))


@auth_bp.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if request.method == "POST":
        if auth_is_rate_limited("forgot"):
            flash("Too many reset attempts. Please wait a few minutes and try again.", "error")
            return render_template("auth/forgot_password.html"), 429
        email = (request.form.get("email") or "").strip().lower()
        flash("If that email is registered, a reset link has been created.", "info")
        record_auth_failure("forgot")
        if _private_mode() and not _is_owner_email(email):
            return render_template("auth/forgot_password.html")
        user = query_one("SELECT * FROM users WHERE email = ?", (email,))
        if user:
            token = secrets.token_urlsafe(32)
            token_hash = hashlib.sha256(token.encode()).hexdigest()
            expires = (_now() + timedelta(hours=2)).isoformat()
            execute(
                "INSERT INTO password_resets (user_id, token_hash, expires_at, used) VALUES (?, ?, ?, 0)",
                (user["id"], token_hash, expires),
            )
            # Never put the raw token in the HTTP response. Local debug logs only.
            if current_app.config.get("DEBUG") and not current_app.config.get("IS_PRODUCTION"):
                reset_url = url_for("auth.reset_password", token=token, _external=True)
                logger.info("Password reset URL (local debug only): %s", reset_url)
    return render_template("auth/forgot_password.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    token_hash = hashlib.sha256(token.encode()).hexdigest()
    row = query_one(
        "SELECT * FROM password_resets WHERE token_hash = ? AND used = 0",
        (token_hash,),
    )
    if row is None or row["expires_at"] < _now().isoformat():
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.forgot_password"))
    if request.method == "POST":
        password = request.form.get("password") or ""
        confirm = request.form.get("confirm") or ""
        if not _valid_password(password) or password != confirm:
            flash("Enter a matching password of at least 8 characters.", "error")
            return render_template("auth/forgot_password.html", reset_mode=True, token=token)
        execute(
            "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
            (generate_password_hash(password), _now().isoformat(), row["user_id"]),
        )
        execute("UPDATE password_resets SET used = 1 WHERE id = ?", (row["id"],))
        session.clear()
        flash("Your password has been updated. Please sign in.", "success")
        return redirect(url_for("auth.login"))
    return render_template("auth/forgot_password.html", reset_mode=True, token=token)


@auth_bp.route("/account", methods=["GET", "POST"])
@login_required
def account():
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        current = request.form.get("current_password") or ""
        new = request.form.get("new_password") or ""
        user = query_one("SELECT * FROM users WHERE id = ?", (g.user["id"],))
        if name and name != user["name"]:
            execute(
                "UPDATE users SET name = ?, updated_at = ? WHERE id = ?",
                (name, _now().isoformat(), user["id"]),
            )
            flash("Your name has been updated.", "success")
        if new:
            if not check_password_hash(user["password_hash"], current):
                flash("Current password is incorrect.", "error")
            elif not _valid_password(new):
                flash("New password must be at least 8 characters.", "error")
            else:
                execute(
                    "UPDATE users SET password_hash = ?, updated_at = ? WHERE id = ?",
                    (generate_password_hash(new), _now().isoformat(), user["id"]),
                )
                flash("Your password has been changed.", "success")
        return redirect(url_for("auth.account"))
    return render_template("auth/account.html")


def hash_compare(a: str, b: str) -> bool:
    return hmac.compare_digest(a, b)
