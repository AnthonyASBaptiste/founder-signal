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
    app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
    app.config["MAX_CONTENT_LENGTH"] = (
        (config or Config.from_env()).max_upload_mb * 1024 * 1024
    )
    config = config or Config.from_env()

    @app.errorhandler(413)
    def request_entity_too_large(error):
        flash(
            f"File too large. Maximum allowed upload size is {config.max_upload_mb} MB.",
            "error",
        )
        return redirect(url_for("ingest"))

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

    @app.route("/ingest", methods=["GET", "POST"])
    def ingest():
        if request.method == "POST":
            kind = request.form.get("kind", "email")
            title = request.form.get("title") or "web input"
            use_llm = request.form.get("use_llm") == "on"

            body: str | None = None
            saved_path: str | None = None
            transcript: str | None = None

            if kind == "email":
                # Straight email: paste text.
                body = request.form.get("body", "").strip()
                if not body:
                    flash("No email text provided.", "error")
                    return redirect(url_for("ingest"))

            elif kind in ("transcript", "voice-note"):
                # File upload.
                file = request.files.get("file")
                if not file or not file.filename:
                    flash(f"No file selected for {kind}.", "error")
                    return redirect(url_for("ingest"))
                if not _allowed_file(file.filename, config):
                    flash(
                        f"File type not allowed. Allowed: {config.upload_extensions}",
                        "error",
                    )
                    return redirect(url_for("ingest"))

                # Save to inbox folder.
                inbox_path = Path(os.path.expanduser(config.inbox_folder))
                inbox_path.mkdir(parents=True, exist_ok=True)
                safe_name = "".join(
                    c if c.isalnum() or c in "-_. " else "_" for c in file.filename
                )
                saved_path = str(inbox_path / safe_name)
                file.save(saved_path)

                if kind == "transcript":
                    # Read text file content for extraction.
                    try:
                        body = Path(saved_path).read_text(encoding="utf-8", errors="replace")
                    except Exception as exc:
                        flash(f"Could not read transcript file: {exc}", "error")
                        return redirect(url_for("ingest"))
                    if not body.strip():
                        flash("Transcript file is empty.", "error")
                        return redirect(url_for("ingest"))
                else:
                    # Voice note (audio): save file, transcribe locally if
                    # possible, then extract commitments from the transcript.
                    from .inbox import _transcribe_audio

                    transcript = _transcribe_audio(Path(saved_path))
                    if transcript:
                        body = transcript
                    else:
                        # Keep in a dedicated "needs transcription" state.
                        # Do NOT extract commitments, do NOT record an ingested source,
                        # and do NOT move into processed/.
                        needs_trans_dir = inbox_path / "needs_transcription"
                        needs_trans_dir.mkdir(parents=True, exist_ok=True)
                        dest = needs_trans_dir / safe_name
                        if dest.exists():
                            dest = needs_trans_dir / f"{Path(safe_name).stem}.{int(time.time())}{Path(safe_name).suffix}"
                        shutil.move(saved_path, str(dest))
                        flash(
                            f"Voice note '{title}' saved in 'needs transcription' state. "
                            f"Transcription is required before commitments can be extracted. "
                            f"Install openai-whisper (`pip install openai-whisper`) or upload a transcript file.",
                            "warning",
                        )
                        return redirect(url_for("index"))

            source_id = f"web:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
            source = Source(id=source_id, kind=kind, title=title, body=body)

            try:
                new_count, issues, result = _process_source(source, config, use_llm=use_llm)
                if saved_path and os.path.exists(saved_path):
                    processed_dir = inbox_path / "processed"
                    processed_dir.mkdir(parents=True, exist_ok=True)
                    dest = processed_dir / safe_name
                    if dest.exists():
                        dest = processed_dir / f"{Path(safe_name).stem}.{int(time.time())}{Path(safe_name).suffix}"
                    shutil.move(saved_path, str(dest))
                    marker = inbox_path / f"{safe_name}.done"
                    marker.write_text(
                        f"processed by web upload at {datetime.now(timezone.utc).isoformat()}\n",
                        encoding="utf-8",
                    )
                if getattr(result, "fallback_from", None):
                    flash(
                        f"Notice: LLM extraction via {result.fallback_from} unavailable; "
                        f"fell back to rule-based extraction.",
                        "warning",
                    )
                if kind == "voice-note":
                    flash(
                        f"Voice note '{title}' transcribed: {new_count} new commitment(s)",
                        "success",
                    )
                else:
                    flash(
                        f"Ingested {kind} '{title}': {new_count} new commitment(s)",
                        "success",
                    )
                    for issue in issues:
                        flash(
                            f"Review needed ({issue.kind}): {issue.description}",
                            "warning",
                        )
            except Exception as exc:  # noqa: BLE001
                flash(f"Ingestion failed: {exc}", "error")
                return redirect(url_for("ingest"))

            return redirect(url_for("index"))
        return render_template("ingest.html")

    return app


def main():
    config = Config.from_env()
    app = create_app(config)
    app.run(host=config.web_host, port=config.web_port, debug=True)


if __name__ == "__main__":
    main()
