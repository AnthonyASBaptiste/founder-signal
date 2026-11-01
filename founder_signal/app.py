"""Flask web interface for Founder Signal.

Inspect the commitment ledger, review proposed changes, and confirm actions.
The agent proposes; the user confirms.
"""

from __future__ import annotations

import os
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from flask import Flask, render_template, request, redirect, url_for, flash

from .config import Config
from .ledger import open_ledger
from .models import Commitment, Source
from .reconciliation import reconcile
from .briefing import generate_briefing
from . import auth


def _allowed_file(filename: str, config: Config) -> bool:
    ext = filename.rsplit(".", 1)[1].lower() if "." in filename else ""
    allowed = {e.strip().lower() for e in config.upload_extensions.split(",")}
    return ext in allowed


def _process_source(source, config: Config, use_llm: bool = False) -> tuple[int, list, object]:
    """Run extraction + reconciliation for a source, add commitments to ledger.

    Returns (new_commitment_count, issues, extraction_result).
    """
    from .extraction import extract, to_commitments

    ledger = open_ledger(config)
    try:
        result = extract(source, use_llm=use_llm, config=config)
        source.extractor = result.extractor
        ledger.add_source(source)
        proposed = to_commitments(result, source.id)
        reconciliation = reconcile(
            ledger, proposed, within_days=config.briefing_coming_up_days
        )
        for c in reconciliation.new_commitments:
            ledger.add_commitment(c)
        for issue in reconciliation.issues:
            if issue.kind == "change" and issue.proposed is not None:
                existing_c = ledger.get_commitment(issue.commitment_id)
                if existing_c:
                    existing_c.pending_change = {
                        "due_date": issue.proposed.due_date,
                        "owner": issue.proposed.owner,
                        "evidence": issue.proposed.evidence,
                        "description": issue.description,
                    }
                    ledger.update_commitment(existing_c)
        return len(reconciliation.new_commitments), reconciliation.issues, result
    finally:
        ledger.close()


def create_app(config: Config | None = None) -> Flask:
    template_folder = os.path.join(os.path.dirname(__file__), "web", "templates")
    app = Flask(__name__, template_folder=template_folder)
    config = config or Config.from_env()
    app.config["SECRET_KEY"] = config.flask_secret_key
    app.config["MAX_CONTENT_LENGTH"] = config.max_upload_mb * 1024 * 1024
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = config.session_cookie_secure
    app.config["PERMANENT_SESSION_LIFETIME"] = 7 * 24 * 60 * 60  # 7 days

    auth.init_app(app)

    @app.errorhandler(413)
    def request_entity_too_large(error):
        flash(
            f"File too large. Maximum allowed upload size is {config.max_upload_mb} MB.",
            "error",
        )
        return redirect(url_for("index"))

    @app.route("/")
    def index():
        ledger = open_ledger(config)
        try:
            briefing = generate_briefing(ledger, coming_up_days=config.briefing_coming_up_days)
            commitments = ledger.list_commitments()
        finally:
            ledger.close()
        inbox_path = Path(os.path.expanduser(config.inbox_folder))
        needs_trans_dir = inbox_path / "needs_transcription"
        needs_transcription_count = (
            len([f for f in needs_trans_dir.iterdir() if f.is_file()])
            if needs_trans_dir.exists()
            else 0
        )
        return render_template(
            "index.html",
            briefing=briefing,
            commitments=commitments,
            needs_transcription_count=needs_transcription_count,
        )

    @app.route("/commitments/<commitment_id>", methods=["GET", "POST"])
    def commitment_detail(commitment_id):
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                flash("Commitment not found.", "error")
                return redirect(url_for("index"))
            source = ledger.get_source(commitment.source_id)
            if request.method == "POST":
                action = request.form.get("action")
                if action == "update":
                    commitment.description = request.form.get("description", commitment.description)
                    commitment.owner = request.form.get("owner") or None
                    commitment.due_date = request.form.get("due_date") or None
                    commitment.status = request.form.get("status", commitment.status)
                    commitment.evidence = request.form.get("evidence", commitment.evidence)
                    ledger.update_commitment(commitment)
                    flash("Commitment updated.", "success")
                elif action == "confirm":
                    # Mark as confirmed (still open, but acknowledged).
                    ledger.update_commitment(commitment)
                    flash("Commitment confirmed.", "success")
                elif action == "accept_proposal":
                    if commitment.pending_change:
                        p = commitment.pending_change
                        if "due_date" in p and p["due_date"] is not None:
                            commitment.due_date = p["due_date"]
                        if "owner" in p and p["owner"] is not None:
                            commitment.owner = p["owner"]
                        if p.get("evidence"):
                            commitment.evidence = p["evidence"]
                        commitment.pending_change = None
                        ledger.update_commitment(commitment)
                        flash("Proposed change accepted and applied.", "success")
                elif action == "reject_proposal":
                    commitment.pending_change = None
                    ledger.update_commitment(commitment)
                    flash("Proposed change rejected.", "info")
                return redirect(url_for("commitment_detail", commitment_id=commitment_id))
        finally:
            ledger.close()
        return render_template("commitment.html", commitment=commitment, source=source)

    @app.route("/commitments/<commitment_id>/status", methods=["POST"])
    def commitment_status(commitment_id):
        """Quick status change: mark done, ignore, reopen, etc."""
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                flash("Commitment not found.", "error")
                return redirect(url_for("index"))
            new_status = request.form.get("status")
            if new_status not in ("open", "done", "waiting", "deferred", "ignore"):
                flash("Invalid status.", "error")
                return redirect(url_for("commitment_detail", commitment_id=commitment_id))
            commitment.status = new_status
            ledger.update_commitment(commitment)
            flash(f"Commitment marked as {new_status}.", "success")
        finally:
            ledger.close()
        return redirect(request.form.get("next") or url_for("index"))

    @app.route("/briefing")
    def briefing_view():
        ledger = open_ledger(config)
        try:
            briefing = generate_briefing(ledger, coming_up_days=config.briefing_coming_up_days)
        finally:
            ledger.close()
        return render_template("briefing.html", briefing=briefing)

    @app.route("/log")
    def processing_log():
        ledger = open_ledger(config)
        try:
            logs = ledger.list_processing_logs()
        finally:
            ledger.close()
        return render_template("log.html", logs=logs)

    return app


def main():
    config = Config.from_env()
    app = create_app(config)
    app.run(host=config.web_host, port=config.web_port, debug=True)


if __name__ == "__main__":
    main()
