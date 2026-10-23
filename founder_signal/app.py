"""Flask web interface for Founder Signal.

Inspect the commitment ledger, review proposed changes, and confirm actions.
The agent proposes; the user confirms.
"""

from __future__ import annotations

import os
from flask import Flask, render_template, request, redirect, url_for, flash

from .config import Config
from .ledger import open_ledger
from .models import Commitment
from .reconciliation import reconcile
from .briefing import generate_briefing


def create_app(config: Config | None = None) -> Flask:
    template_folder = os.path.join(os.path.dirname(__file__), "web", "templates")
    app = Flask(__name__, template_folder=template_folder)
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    config = config or Config.from_env()

    @app.route("/")
    def index():
        ledger = open_ledger(config)
        try:
            briefing = generate_briefing(ledger, coming_up_days=config.briefing_coming_up_days)
            commitments = ledger.list_commitments()
        finally:
            ledger.close()
        return render_template("index.html", briefing=briefing, commitments=commitments)

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
                    flash("Commitment confirmed.", "success")
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

    @app.route("/ingest", methods=["GET", "POST"])
    def ingest():
        if request.method == "POST":
            body = request.form.get("body", "").strip()
            kind = request.form.get("kind", "email")
            title = request.form.get("title") or "web input"
            if not body:
                flash("No input provided.", "error")
                return redirect(url_for("ingest"))
            from datetime import datetime, timezone
            from .extraction import extract, to_commitments
            from .models import Source

            source_id = f"web:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
            source = Source(id=source_id, kind=kind, title=title, body=body)
            ledger = open_ledger(config)
            try:
                ledger.add_source(source)
                result = extract(source, use_llm=False)
                proposed = to_commitments(result, source.id)
                reconciliation = reconcile(ledger, proposed, within_days=config.briefing_coming_up_days)
                for c in reconciliation.new_commitments:
                    ledger.add_commitment(c)
                flash(f"Ingested {kind} '{title}': {reconciliation.summary}", "success")
                for issue in reconciliation.issues:
                    flash(f"Review needed ({issue.kind}): {issue.description}", "warning")
            finally:
                ledger.close()
            return redirect(url_for("index"))
        return render_template("ingest.html")

    return app


def main():
    config = Config.from_env()
    app = create_app(config)
    app.run(host=config.web_host, port=config.web_port, debug=True)


if __name__ == "__main__":
    main()
