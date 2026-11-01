"""Authentication for Founder Signal — single founder sign-in.

Protects the commitment ledger (which may contain email contents) behind a
login gate. Credentials are configured via environment variables:

    FS_ADMIN_USER        admin username (required)
    FS_ADMIN_PASSWORD    admin password (required)
    FLASK_SECRET_KEY     session signing secret (required)
    FS_SESSION_SECURE    set "true" to send session cookie only over HTTPS
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from flask import Blueprint, flash, redirect, render_template, request, session, url_for
from flask_login import (
    LoginManager,
    UserMixin,
    current_user,
    login_user,
    logout_user,
)
from werkzeug.security import check_password_hash, generate_password_hash

auth_bp = Blueprint("auth", __name__, template_folder="../web/templates")

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = "Please sign in to access Founder Signal."
login_manager.login_message_category = "info"
login_manager.session_protection = "strong"

_admin_user_cache = None


def _reset_cache_for_testing() -> None:
    """Clear the cached admin user so env var changes are picked up (tests only)."""
    global _admin_user_cache
    _admin_user_cache = None


@dataclass(frozen=True)
class AdminUser(UserMixin):
    """Single founder admin account."""

    id: str
    username: str
    password_hash: str

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)


def _admin_user() -> AdminUser | None:
    """Build (once) the single admin user from environment variables."""
    global _admin_user_cache
    if _admin_user_cache is not None:
        return _admin_user_cache
    username = os.environ.get("FS_ADMIN_USER")
    password = os.environ.get("FS_ADMIN_PASSWORD")
    if not username or not password:
        return None
    _admin_user_cache = AdminUser(
        id="admin",
        username=username,
        password_hash=generate_password_hash(password),
    )
    return _admin_user_cache


@login_manager.user_loader
def load_user(user_id: str) -> AdminUser | None:
    user = _admin_user()
    if user and user.id == user_id:
        return user
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        user = _admin_user()
        if not user:
            flash(
                "Authentication is not configured on this server. "
                "Set FS_ADMIN_USER and FS_ADMIN_PASSWORD.",
                "error",
            )
            return render_template("login.html"), 500

        if username == user.username and user.check_password(password):
            login_user(user, remember=True)
            session.permanent = True
            next_url = request.args.get("next") or url_for("dashboard")
            flash("Signed in successfully.", "success")
            return redirect(next_url)

        flash("Invalid username or password.", "error")

    return render_template("login.html")


@auth_bp.route("/logout")
def logout():
    logout_user()
    session.clear()
    flash("Signed out.", "info")
    return redirect(url_for("auth.login"))


def init_app(app) -> None:
    """Initialize Flask-Login and register the auth blueprint on the app."""
    login_manager.init_app(app)
    app.register_blueprint(auth_bp)

    @app.before_request
    def _require_login():
        # Allow auth routes, static files, the public landing page, and the error handler.
        if request.endpoint in (
            "auth.login",
            "auth.logout",
            "static",
            "index",
        ) or (request.endpoint and request.endpoint.startswith("auth.")):
            return
        if not current_user.is_authenticated:
            return redirect(url_for("auth.login", next=request.path))
