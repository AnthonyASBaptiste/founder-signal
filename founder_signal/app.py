"""Flask web interface for Founder Signal.

Inspect the commitment ledger, review proposed changes, and confirm actions.
The agent proposes; the user confirms.
"""

from __future__ import annotations

import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from flask import Flask, render_template, request, redirect, url_for, flash

from .config import Config
from .ledger import open_ledger
from .models import Commitment, Source
from .reconciliation import reconcile, build_pending_change
from .briefing import generate_briefing
from .notifications import notify_morning_briefing, send_discord_alert
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
                    existing_c.pending_change = build_pending_change(existing_c, issue.proposed, issue.description)
                    ledger.update_commitment(existing_c)
        return len(reconciliation.new_commitments), reconciliation.issues, result
    finally:
        ledger.close()


def _extract_sender_from_source(source: Optional[Source]) -> Optional[str]:
    """Extract sender email or domain identifier from source metadata for rule suggestions."""
    if not source:
        return None
    text = f"{source.title}\n{source.body}"
    match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z0-9-.]+", text)
    if match:
        return match.group(0).lower()
    if "@" in source.id:
        match = re.search(r"[\w.+-]+@[\w-]+\.[a-zA-Z0-9-.]+", source.id)
        if match:
            return match.group(0).lower()
    return None


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
        return redirect(url_for("dashboard"))

    @app.route("/")
    def index():
        """Public product landing page."""
        return render_template("landing.html")

    @app.route("/dashboard")
    def dashboard():
        ledger = open_ledger(config)
        try:
            settings = ledger.get_settings()
            due_soon_days = int(settings.get("due_soon_days", config.briefing_coming_up_days or 3))
            briefing = generate_briefing(ledger, coming_up_days=due_soon_days)
            commitments = ledger.list_commitments()
            sources = {s.id: s for s in ledger.list_sources()}
        finally:
            ledger.close()

        # Group commitments by source_id for topic/email grouping
        groups = []
        ungrouped = []
        for c in commitments:
            src = sources.get(c.source_id)
            if src:
                groups.append((src, c))
            else:
                ungrouped.append(c)

        # Build ordered list of (source, [commitments]) tuples
        source_groups: dict[str, tuple[Source, list[Commitment]]] = {}
        for src, c in groups:
            if src.id not in source_groups:
                source_groups[src.id] = (src, [])
            source_groups[src.id][1].append(c)

        # Sort groups by source received_at (newest first), then by commitment due date
        ordered_groups = sorted(
            source_groups.values(),
            key=lambda item: (
                item[0].received_at.isoformat() if item[0].received_at else "",
                item[0].created_at.isoformat(),
            ),
            reverse=True,
        )

        inbox_path = Path(os.path.expanduser(config.inbox_folder))
        needs_trans_dir = inbox_path / "needs_transcription"
        needs_transcription_count = (
            len([f for f in needs_trans_dir.iterdir() if f.is_file()])
            if needs_trans_dir.exists()
            else 0
        )

        # Categorize for the Small Daily Action List (Item 2)
        open_commitments = [c for c in commitments if c.status == "open"]
        pending_proposals = [c for c in open_commitments if c.pending_change]
        proposal_ids = {c.id for c in pending_proposals}
        do_now = [c for c in briefing.do_now if c.id not in proposal_ids]
        do_now_ids = {c.id for c in do_now}

        # New commitments: open commitments needing attention not in do_now or proposals
        new_commitments = [
            c for c in open_commitments
            if c.id not in proposal_ids and c.id not in do_now_ids
        ]

        # History / Settled: done, ignore, waiting, deferred
        history_commitments = [
            c for c in commitments
            if c.status in ("done", "ignore", "waiting", "deferred")
        ]

        # Filter predictability & rule suggestions (Items 1 & 6)
        excluded_count = settings.get("excluded_count", 0)
        pending_rules = [
            r for r in settings.get("suggested_rules", [])
            if r.get("status") == "pending"
        ]

        return render_template(
            "index.html",
            briefing=briefing,
            commitments=commitments,
            do_now=do_now,
            pending_proposals=pending_proposals,
            new_commitments=new_commitments,
            history_commitments=history_commitments,
            pending_rules=pending_rules,
            excluded_count=excluded_count,
            settings=settings,
            source_groups=ordered_groups,
            ungrouped_commitments=ungrouped,
            needs_transcription_count=needs_transcription_count,
        )

    @app.route("/commitments/<commitment_id>", methods=["GET", "POST"])
    def commitment_detail(commitment_id):
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                flash("Commitment not found.", "error")
                return redirect(url_for("dashboard"))
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
                return redirect(url_for("dashboard"))
            new_status = request.form.get("status")
            if new_status not in ("open", "done", "waiting", "deferred", "ignore"):
                flash("Invalid status.", "error")
                return redirect(url_for("commitment_detail", commitment_id=commitment_id))
            commitment.status = new_status
            ledger.update_commitment(commitment)

            if new_status == "ignore":
                source = ledger.get_source(commitment.source_id)
                sender = _extract_sender_from_source(source)
                if sender:
                    ledger.record_dismissal(sender, title=source.title if source else None)

            flash(f"Commitment marked as {new_status}.", "success")
        finally:
            ledger.close()
        return redirect(request.form.get("next") or url_for("dashboard"))

    @app.route("/api/commitments/<commitment_id>/status", methods=["POST"])
    def api_commitment_status(commitment_id):
        """Asynchronous JSON status update endpoint for instant optimistic UI."""
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                return {"success": False, "error": "Commitment not found"}, 404
            data = request.get_json(silent=True) or request.form
            new_status = data.get("status")
            if new_status not in ("open", "done", "waiting", "deferred", "ignore"):
                return {"success": False, "error": "Invalid status"}, 400
            commitment.status = new_status
            ledger.update_commitment(commitment)

            suggested_rule = None
            if new_status == "ignore":
                source = ledger.get_source(commitment.source_id)
                sender = _extract_sender_from_source(source)
                if sender:
                    suggested_rule = ledger.record_dismissal(sender, title=source.title if source else None)

            return {
                "success": True,
                "id": commitment_id,
                "status": new_status,
                "suggested_rule": suggested_rule,
            }
        finally:
            ledger.close()

    @app.route("/api/commitments/<commitment_id>/accept_proposal", methods=["POST"])
    def api_accept_proposal(commitment_id):
        """Accept a proposed change in-place without page reload."""
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                return {"success": False, "error": "Commitment not found"}, 404
            if not commitment.pending_change:
                return {"success": False, "error": "No pending change"}, 400
            p = commitment.pending_change
            if "due_date" in p and p["due_date"] is not None:
                commitment.due_date = p["due_date"]
            if "owner" in p and p["owner"] is not None:
                commitment.owner = p["owner"]
            if p.get("evidence"):
                commitment.evidence = p["evidence"]
            commitment.pending_change = None
            ledger.update_commitment(commitment)
            return {
                "success": True,
                "id": commitment_id,
                "due_date": commitment.due_date,
                "owner": commitment.owner,
            }
        finally:
            ledger.close()

    @app.route("/api/commitments/<commitment_id>/reject_proposal", methods=["POST"])
    def api_reject_proposal(commitment_id):
        """Reject a proposed change in-place without page reload."""
        ledger = open_ledger(config)
        try:
            commitment = ledger.get_commitment(commitment_id)
            if not commitment:
                return {"success": False, "error": "Commitment not found"}, 404
            commitment.pending_change = None
            ledger.update_commitment(commitment)
            return {"success": True, "id": commitment_id}
        finally:
            ledger.close()

    @app.route("/api/rules/<rule_id>/accept", methods=["POST"])
    def api_accept_rule(rule_id):
        """Accept a suggested rule learned from user dismissals."""
        ledger = open_ledger(config)
        try:
            ok = ledger.accept_suggested_rule(rule_id)
            if not ok:
                return {"success": False, "error": "Rule not found or already processed"}, 404
            return {"success": True, "rule_id": rule_id}
        finally:
            ledger.close()

    @app.route("/api/rules/<rule_id>/dismiss", methods=["POST"])
    def api_dismiss_rule(rule_id):
        """Dismiss a suggested rule without applying it."""
        ledger = open_ledger(config)
        try:
            ok = ledger.dismiss_suggested_rule(rule_id)
            if not ok:
                return {"success": False, "error": "Rule not found or already processed"}, 404
            return {"success": True, "rule_id": rule_id}
        finally:
            ledger.close()

    @app.route("/api/settings/reset_excluded", methods=["POST"])
    def api_reset_excluded():
        """Reset excluded message counter."""
        ledger = open_ledger(config)
        try:
            ledger.reset_excluded_count()
            return {"success": True, "excluded_count": 0}
        finally:
            ledger.close()

    @app.route("/ingest", methods=["GET", "POST"])
    def ingest():
        if request.method == "POST":
            kind = request.form.get("kind", "text")
            title = request.form.get("title") or "Web Upload"
            body = request.form.get("body", "")
            use_llm = config.use_llm

            inbox_path = Path(os.path.expanduser(config.inbox_folder))
            inbox_path.mkdir(parents=True, exist_ok=True)

            if "file" in request.files and request.files["file"].filename:
                file = request.files["file"]
                safe_name = "".join(c if c.isalnum() or c in "-_. " else "_" for c in file.filename)
                saved_path = inbox_path / safe_name
                file.save(str(saved_path))
                title = file.filename
                ext = saved_path.suffix.lower()

                if ext in {".mp3", ".wav", ".m4a", ".ogg", ".aac"}:
                    kind = "voice-note"
                    from .inbox import _transcribe_audio
                    transcript = _transcribe_audio(saved_path)
                    if transcript:
                        body = transcript
                    else:
                        flash("Audio uploaded, but local transcription failed. Saved to inbox.", "warning")
                        return redirect(url_for("dashboard"))
                elif ext == ".pdf":
                    kind = "document"
                    from .inbox import _extract_pdf_text
                    pdf_text = _extract_pdf_text(saved_path)
                    if pdf_text:
                        body = pdf_text
                    else:
                        flash("Could not extract text from uploaded PDF.", "error")
                        return redirect(url_for("dashboard"))
                else:
                    try:
                        body = saved_path.read_text(encoding="utf-8", errors="replace")
                    except Exception as exc:
                        flash(f"Error reading file: {exc}", "error")
                        return redirect(url_for("dashboard"))

                saved_path.unlink(missing_ok=True)

            if not body or not body.strip():
                flash("No text content provided for ingestion.", "error")
                return redirect(url_for("ingest"))

            source_id = f"web:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
            source = Source(id=source_id, kind=kind, title=title, body=body)

            try:
                new_count, issues, result = _process_source(source, config, use_llm=use_llm)
                flash(f"Ingested '{title}': {new_count} commitment(s) extracted.", "success")
                return redirect(url_for("dashboard"))
            except Exception as exc:
                flash(f"Ingestion error: {exc}", "error")
                return redirect(url_for("ingest"))

        return render_template("ingest.html")

    @app.route("/settings", methods=["GET", "POST"])
    def settings_view():
        ledger = open_ledger(config)
        try:
            settings = ledger.get_settings()
            if request.method == "POST":
                action = request.form.get("action")
                if action == "save":
                    vip_emails = [e.strip().lower() for e in request.form.get("vip_emails", "").splitlines() if e.strip()]
                    vip_domains = [d.strip().lower().lstrip("@") for d in request.form.get("vip_domains", "").splitlines() if d.strip()]
                    vip_keywords = [k.strip() for k in request.form.get("vip_keywords", "").splitlines() if k.strip()]
                    discord_target = request.form.get("discord_alerts_target", "discord:alerts-and-logs").strip()
                    app_url = request.form.get("app_url", "https://founder-signal.builtbyanthony.tech").strip()

                    # Scan rules
                    only_scan_vip = bool(request.form.get("only_scan_vip"))
                    include_directly_addressed = bool(request.form.get("include_directly_addressed"))
                    auto_ignore_bulk = bool(request.form.get("auto_ignore_bulk"))

                    # Categorized VIP People list
                    vip_people = []
                    # 1. Co-founders
                    cofounder_names = request.form.getlist("cofounder_name")
                    cofounder_emails = request.form.getlist("cofounder_email")
                    for name, email in zip(cofounder_names, cofounder_emails):
                        clean_e = email.strip().lower()
                        if clean_e:
                            vip_people.append({"name": name.strip() or "Co-founder", "role": "co-founder", "email": clean_e})
                            if clean_e not in vip_emails:
                                vip_emails.append(clean_e)

                    # 2. Mentors
                    mentor_names = request.form.getlist("mentor_name")
                    mentor_emails = request.form.getlist("mentor_email")
                    for name, email in zip(mentor_names, mentor_emails):
                        clean_e = email.strip().lower()
                        if clean_e:
                            vip_people.append({"name": name.strip() or "Mentor", "role": "mentor", "email": clean_e})
                            if clean_e not in vip_emails:
                                vip_emails.append(clean_e)

                    # 3. Key Partners / Accelerators
                    partner_names = request.form.getlist("partner_name")
                    partner_domains = request.form.getlist("partner_domain")
                    for name, domain in zip(partner_names, partner_domains):
                        clean_d = domain.strip().lower().lstrip("@")
                        if clean_d:
                            vip_people.append({"name": name.strip() or "Partner", "role": "key partner", "domain": clean_d})
                            if clean_d not in vip_domains:
                                vip_domains.append(clean_d)

                    # Digest & schedule settings
                    digest_enabled = bool(request.form.get("digest_enabled"))
                    digest_time = request.form.get("digest_time", "08:00").strip()
                    digest_threshold_only = bool(request.form.get("digest_threshold_only"))
                    try:
                        due_soon_days = int(request.form.get("due_soon_days") or 3)
                    except ValueError:
                        due_soon_days = 3
                    try:
                        check_interval_mins = int(request.form.get("check_interval_mins") or 15)
                    except ValueError:
                        check_interval_mins = 15

                    settings["vip_people"] = vip_people
                    settings["vip_emails"] = vip_emails
                    settings["vip_domains"] = vip_domains
                    settings["vip_keywords"] = vip_keywords
                    settings["only_scan_vip"] = only_scan_vip
                    settings["include_directly_addressed"] = include_directly_addressed
                    settings["auto_ignore_bulk"] = auto_ignore_bulk
                    settings["digest_enabled"] = digest_enabled
                    settings["digest_time"] = digest_time
                    settings["digest_threshold_only"] = digest_threshold_only
                    settings["due_soon_days"] = due_soon_days
                    settings["check_interval_mins"] = check_interval_mins
                    settings["discord_alerts_target"] = discord_target
                    settings["app_url"] = app_url

                    ledger.update_settings(settings)
                    flash("Settings saved successfully.", "success")
                elif action == "reset_excluded":
                    ledger.reset_excluded_count()
                    flash("Excluded message counter reset to 0.", "info")
                elif action == "remove_exclusion":
                    pattern = request.form.get("pattern", "").lower().strip()
                    if pattern:
                        if "@" in pattern:
                            ex = settings.get("excluded_senders", [])
                            if pattern in ex:
                                ex.remove(pattern)
                        else:
                            ex = settings.get("excluded_domains", [])
                            if pattern in ex:
                                ex.remove(pattern)
                        ledger.update_settings(settings)
                        flash(f"Removed '{pattern}' from exclusion list.", "info")
                elif action == "test_discord":
                    from .notifications import send_discord_alert
                    target = request.form.get("discord_alerts_target", "discord:alerts-and-logs").strip()
                    ok = send_discord_alert("🔔 [Founder Signal] Test notification from settings page.", target=target)
                    if ok:
                        flash(f"Test alert sent to {target}!", "success")
                    else:
                        flash(f"Failed to send test alert to {target}.", "error")
                elif action == "test_digest":
                    due_days = int(settings.get("due_soon_days", 3))
                    briefing = generate_briefing(ledger, coming_up_days=due_days)
                    commitments = ledger.list_commitments()
                    pending_proposals_count = len([c for c in commitments if c.status == "open" and c.pending_change])
                    target = request.form.get("discord_alerts_target") or settings.get("discord_alerts_target")
                    app_url = request.form.get("app_url") or settings.get("app_url")
                    ok = notify_morning_briefing(
                        briefing,
                        target=target,
                        app_url=app_url,
                        threshold_only=False,
                        pending_proposals_count=pending_proposals_count,
                    )
                    if ok:
                        flash(f"Test morning briefing sent to {target}!", "success")
                    else:
                        flash(f"Failed to send briefing to {target}.", "error")
                elif action == "clear_ledger":
                    ledger.clear_ledger()
                    flash("Ledger cleared successfully. All past commitments and sources removed.", "info")
                return redirect(url_for("settings_view"))
        finally:
            ledger.close()
        return render_template("settings.html", settings=settings)

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
