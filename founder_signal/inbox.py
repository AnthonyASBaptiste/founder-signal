"""Inbox folder watcher and heartbeat email checker for Founder Signal.

Monitors a configurable inbox folder for new files (email text, voice-note
transcripts, meeting transcripts) and processes them through the Founder Signal
skill. Also supports a heartbeat mode that fetches new email via the himalaya
CLI and feeds it into the same pipeline.

The agent proposes; it never sends messages, accepts commitments, or marks
tasks complete without confirmation.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from .config import Config
from .ledger import open_ledger
from .models import Source, Commitment, ProcessingLog
from .extraction import extract, to_commitments
from .reconciliation import reconcile, build_pending_change
from .briefing import generate_briefing
from .notifications import notify_urgent_commitment, notify_morning_briefing, send_discord_alert

HIMALAYA_BIN = os.environ.get("HIMALAYA_BIN", "himalaya")
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")


def resolve_himalaya_bin(bin_name: Optional[str] = None) -> Optional[str]:
    """Find the himalaya executable via exact path, PATH lookup, or standard install dirs."""
    candidate = bin_name or os.environ.get("HIMALAYA_BIN", "himalaya")
    if os.path.isabs(candidate) and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
        return candidate
    found = shutil.which(candidate)
    if found:
        return found
    for fallback in [
        Path.home() / ".local" / "bin" / candidate,
        Path("/usr/local/bin") / candidate,
        Path("/usr/bin") / candidate,
    ]:
        if fallback.is_file() and os.access(fallback, os.X_OK):
            return str(fallback)
    return None

# Optional local transcription for voice notes. Requires pip install
# openai-whisper (and ffmpeg on the system). When unavailable, audio files
# are saved to the inbox with a "transcription needed" note.
_whisper_model = None


def _transcribe_audio(file_path: Path) -> Optional[str]:
    """Transcribe an audio file with openai-whisper (local, offline).

    Returns the transcript text, or None if whisper is not installed or
    transcription fails.
    """
    global _whisper_model
    try:
        import whisper  # type: ignore
    except ImportError:
        return None
    if _whisper_model is None:
        try:
            _whisper_model = whisper.load_model("base")
        except Exception:
            return None
    try:
        result = _whisper_model.transcribe(str(file_path))
        return (result.get("text") or "").strip() or None
    except Exception:
        return None


def _extract_pdf_text(file_path: Path) -> Optional[str]:
    """Extract text from a PDF file using pdftotext."""
    pdftotext = shutil.which("pdftotext")
    if pdftotext:
        try:
            res = subprocess.run([pdftotext, str(file_path), "-"], capture_output=True, text=True, timeout=30)
            if res.returncode == 0:
                text = res.stdout.strip()
                if text:
                    return text
        except Exception:
            pass
    return None


class InboxWatcher:
    """Watch an inbox folder and process new files through Founder Signal."""

    def __init__(self, config: Config):
        self.config = config
        self.inbox_path = Path(os.path.expanduser(config.inbox_folder))
        self.processed_path = self.inbox_path / "processed"
        self.ledger = open_ledger(config)
        self.himalaya_bin = resolve_himalaya_bin(
            getattr(config, "himalaya_bin", None) or os.environ.get("HIMALAYA_BIN", "himalaya")
        )

    def ensure_dirs(self) -> None:
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)

    def _file_received_at(self, file_path: Path) -> Optional[datetime]:
        """Best-effort timestamp for when a file appeared in the inbox.

        Uses the file's modification time as a proxy for "date received."
        """
        try:
            return datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            return None

    # Text extensions that can be read directly for extraction.
    TEXT_EXTENSIONS = {".txt", ".md"}
    # Audio extensions recognized as voice notes (need transcription before extraction).
    AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}
    # Video extensions recognized as meeting recordings (need transcription before extraction).
    VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
    # Document extensions
    DOC_EXTENSIONS = {".pdf"}

    def scan(self) -> int:
        """Scan the inbox for new files and process them.

        Text files (.txt, .md) and documents (.pdf) are extracted. Audio files
        (.mp3, .wav, .m4a, .ogg, .aac) are recognized as voice notes and
        transcribed locally before extraction.

        Processed files are removed from the inbox, and redundant items
        already recorded in the database are skipped and cleaned up.

        Returns the number of files processed.
        """
        self.ensure_dirs()
        processed = 0
        for file_path in sorted(self.inbox_path.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.name.endswith(".done"):
                file_path.unlink(missing_ok=True)
                continue
            # Deduplication: if already processed and recorded in DB, remove and skip
            if self.ledger.has_processed_file(file_path.name):
                file_path.unlink(missing_ok=True)
                continue
            ext = file_path.suffix.lower()
            if (
                ext not in self.TEXT_EXTENSIONS
                and ext not in self.AUDIO_EXTENSIONS
                and ext not in self.VIDEO_EXTENSIONS
                and ext not in self.DOC_EXTENSIONS
            ):
                continue
            try:
                self.process_file(file_path)
                processed += 1
            except Exception as exc:  # noqa: BLE001
                # One bad file must not stop the rest of the batch.
                log = ProcessingLog(
                    id=f"log:{file_path.name}:{int(datetime.now(timezone.utc).timestamp())}",
                    filename=file_path.name,
                    kind=ext.lstrip("."),
                    received_at=self._file_received_at(file_path),
                    status="error",
                    error_message=str(exc),
                )
                try:
                    self.ledger.add_processing_log(log)
                except Exception:  # noqa: BLE001
                    pass
                print(
                    f"[founder-signal] {file_path.name}: error processing: {exc}",
                    file=sys.stderr,
                )
        return processed

    def process_file(self, file_path: Path, account: Optional[str] = None) -> None:
        """Process a single inbox file through extraction, reconciliation, briefing."""
        ext = file_path.suffix.lower()
        received_at = self._file_received_at(file_path)

        def _record_log(status: str, source_id: Optional[str] = None,
                        commitment_count: int = 0, error_message: Optional[str] = None) -> None:
            log = ProcessingLog(
                id=f"log:{file_path.name}:{int(datetime.now(timezone.utc).timestamp())}",
                filename=file_path.name,
                kind=ext.lstrip("."),
                source_id=source_id,
                received_at=received_at,
                status=status,
                commitment_count=commitment_count,
                error_message=error_message,
            )
            try:
                self.ledger.add_processing_log(log)
            except Exception:  # noqa: BLE001
                pass

        # Audio files (voice notes) and video files (meeting recordings):
        # transcribe locally if possible, then extract commitments from the
        # transcript like any other source.
        if ext in self.AUDIO_EXTENSIONS or ext in self.VIDEO_EXTENSIONS:
            kind = "voice-note" if ext in self.AUDIO_EXTENSIONS else "video"
            transcript = _transcribe_audio(file_path)
            if transcript:
                title = file_path.stem
                source_id = (
                    f"inbox:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
                )
                source = Source(id=source_id, kind=kind, title=title, body=transcript)

                result = extract(
                    source,
                    use_llm=self.config.use_llm,
                    config=self.config,
                    account=account,
                )
                source.extractor = result.extractor
                self.ledger.add_source(source)

                proposed = to_commitments(result, source.id)
                reconciliation = reconcile(
                    self.ledger,
                    proposed,
                    within_days=self.config.briefing_coming_up_days,
                )

                for c in reconciliation.new_commitments:
                    self.ledger.add_commitment(c)

                for issue in reconciliation.issues:
                    if issue.kind == "change" and issue.proposed is not None:
                        existing_c = self.ledger.get_commitment(issue.commitment_id)
                        if existing_c:
                            existing_c.pending_change = build_pending_change(existing_c, issue.proposed, issue.description)
                            self.ledger.update_commitment(existing_c)

                _record_log("ok", source_id, len(reconciliation.new_commitments))
                self._mark_done(file_path)
                self._check_urgent_commitments(reconciliation.new_commitments, title)
                print(
                    f"[founder-signal] {file_path.name}: transcribed {kind}, "
                    f"{len(reconciliation.new_commitments)} new commitment(s), "
                    f"{len(reconciliation.issues)} issue(s) needing review."
                )
            else:
                needs_trans_dir = self.inbox_path / "needs_transcription"
                needs_trans_dir.mkdir(parents=True, exist_ok=True)
                dest = needs_trans_dir / file_path.name
                if dest.exists():
                    dest = needs_trans_dir / f"{file_path.stem}.{int(time.time())}{file_path.suffix}"
                shutil.move(str(file_path), str(dest))
                _record_log("needs_transcription", error_message="transcription required")
                print(
                    f"[founder-signal] {file_path.name}: moved to needs_transcription/. "
                    f"Transcription is needed before commitments can be extracted. "
                    f"Install openai-whisper (pip install openai-whisper) for "
                    f"automatic transcription."
                )
            return

        # Document files (PDF): extract text, then extract commitments
        if ext in self.DOC_EXTENSIONS:
            kind = "document"
            text = _extract_pdf_text(file_path)
            if not text or not text.strip():
                _record_log("error", error_message="Could not extract text from PDF")
                return
            title = file_path.stem
            source_id = f"inbox:doc:{title}:{int(datetime.now(timezone.utc).timestamp())}"
            source = Source(id=source_id, kind=kind, title=title, body=text)
            result = extract(
                source,
                use_llm=self.config.use_llm,
                config=self.config,
                account=account,
            )
            source.extractor = result.extractor
            self.ledger.add_source(source)

            proposed = to_commitments(result, source.id)
            reconciliation = reconcile(
                self.ledger,
                proposed,
                within_days=self.config.briefing_coming_up_days,
            )

            for c in reconciliation.new_commitments:
                self.ledger.add_commitment(c)

            for issue in reconciliation.issues:
                if issue.kind == "change" and issue.proposed is not None:
                    existing_c = self.ledger.get_commitment(issue.commitment_id)
                    if existing_c:
                        existing_c.pending_change = build_pending_change(existing_c, issue.proposed, issue.description)
                        self.ledger.update_commitment(existing_c)

            _record_log("ok", source_id, len(reconciliation.new_commitments))
            self._mark_done(file_path)
            self._check_urgent_commitments(reconciliation.new_commitments, title)
            print(
                f"[founder-signal] {file_path.name}: extracted PDF document, "
                f"{len(reconciliation.new_commitments)} new commitment(s), "
                f"{len(reconciliation.issues)} issue(s) needing review."
            )
            return

        body = file_path.read_text(encoding="utf-8", errors="replace")
        if not body.strip():
            _record_log("ok", commitment_count=0)
            self._mark_done(file_path)
            return

        kind = self._guess_kind(file_path)
        title = file_path.stem
        source_id = f"inbox:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
        source = Source(id=source_id, kind=kind, title=title, body=body)

        result = extract(source, use_llm=self.config.use_llm, config=self.config, account=account)
        source.extractor = result.extractor
        self.ledger.add_source(source)

        proposed = to_commitments(result, source.id)
        reconciliation = reconcile(
            self.ledger, proposed, within_days=self.config.briefing_coming_up_days
        )

        for c in reconciliation.new_commitments:
            self.ledger.add_commitment(c)

        for issue in reconciliation.issues:
            if issue.kind == "change" and issue.proposed is not None:
                existing_c = self.ledger.get_commitment(issue.commitment_id)
                if existing_c:
                    existing_c.pending_change = build_pending_change(existing_c, issue.proposed, issue.description)
                    self.ledger.update_commitment(existing_c)

        _record_log("ok", source_id, len(reconciliation.new_commitments))
        self._mark_done(file_path)
        self._check_urgent_commitments(reconciliation.new_commitments, title)

        print(
            f"[founder-signal] Processed {file_path.name}: "
            f"{len(reconciliation.new_commitments)} new commitment(s), "
            f"{len(reconciliation.issues)} issue(s) needing review."
        )

    def _check_urgent_commitments(self, commitments: list[Commitment], source_title: str) -> None:
        """Trigger urgent Discord & desktop alerts if any commitment is due soon."""
        try:
            settings = self.ledger.get_settings()
            target = settings.get("discord_alerts_target", "discord:alerts-and-logs")
            app_url = settings.get("app_url", "http://127.0.0.1:5000")
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
            for c in commitments:
                if c.due_date and c.due_date in (today, tomorrow):
                    notify_urgent_commitment(c, source_title=source_title, target=target, app_url=app_url)
        except Exception as exc:
            print(f"[founder-signal] Error sending urgent alerts: {exc}", file=sys.stderr)

    def _guess_kind(self, file_path: Path) -> str:
        name = file_path.name.lower()
        if "voice" in name or "memo" in name:
            return "voice-note"
        if "meeting" in name or "transcript" in name:
            return "transcript"
        return "email"

    def _mark_done(self, file_path: Path) -> None:
        """Remove processed item from inbox after recording in database."""
        dest = self.processed_path / file_path.name
        if dest.exists():
            dest = self.processed_path / f"{file_path.stem}.{int(time.time())}{file_path.suffix}"
        try:
            shutil.move(str(file_path), str(dest))
        except OSError:
            file_path.unlink(missing_ok=True)

    def heartbeat_email(
        self,
        accounts: Optional[list[str]] = None,
        days: Optional[int] = None,
    ) -> int:
        """Fetch new VIP email via himalaya and write to the inbox folder.

        Filters envelopes by VIP senders, domains, and keywords from settings
        so promotional emails and newsletters are never downloaded or extracted.
        Returns the number of emails fetched.
        """
        himalaya = self.himalaya_bin or resolve_himalaya_bin()
        if not himalaya:
            target = getattr(self.config, "himalaya_bin", HIMALAYA_BIN)
            print(f"[founder-signal] himalaya not found at {target}", file=sys.stderr)
            return 0

        self.ensure_dirs()
        accounts = accounts or self._himalaya_accounts()
        if not accounts:
            print("[founder-signal] No himalaya accounts configured.", file=sys.stderr)
            return 0

        settings = self.ledger.get_settings()
        only_scan_vip = settings.get("only_scan_vip", True)
        include_directly_addressed = settings.get("include_directly_addressed", True)
        auto_ignore_bulk = settings.get("auto_ignore_bulk", True)

        vip_emails = {e.lower().strip() for e in settings.get("vip_emails", [])}
        vip_domains = {d.lower().strip().lstrip("@") for d in settings.get("vip_domains", [])}
        for person in settings.get("vip_people", []):
            if person.get("email"):
                vip_emails.add(person["email"].lower().strip())
            if person.get("domain"):
                vip_domains.add(person["domain"].lower().strip().lstrip("@"))
        vip_keywords = [k.lower().strip() for k in settings.get("vip_keywords", [])]

        excluded_senders = {e.lower().strip() for e in settings.get("excluded_senders", [])}
        excluded_domains = {d.lower().strip().lstrip("@") for d in settings.get("excluded_domains", [])}

        lookback_days = days if days is not None else getattr(self.config, "heartbeat_days", 3)
        since = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        fetched = 0

        for account in accounts:
            try:
                # Search envelopes received since lookback date, output as JSON.
                result = subprocess.run(
                    [
                        himalaya,
                        "envelope",
                        "search",
                        "-a",
                        account,
                        "--json",
                        f"after {since}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=120,
                )
                if result.returncode != 0:
                    print(
                        f"[founder-signal] himalaya envelope search failed for {account}: "
                        f"{result.stderr.strip()}",
                        file=sys.stderr,
                    )
                    continue

                envelopes = self._parse_envelope_json(result.stdout)
                for env in envelopes:
                    msg_id = env.get("id")
                    if not msg_id:
                        continue
                    safe_id = "".join(
                        c if c.isalnum() or c in "-_" else "_" for c in str(msg_id)
                    )
                    file_name = f"email-{account}-{safe_id}.txt"

                    # Skip if already recorded in ledger
                    if self.ledger.has_processed_file(file_name):
                        continue

                    # Check VIP criteria against envelope headers
                    from_entries = env.get("from") or []
                    to_entries = env.get("to") or []
                    subject = (env.get("subject") or "").lower()

                    sender_emails = [f.get("email", "").lower() for f in from_entries if f.get("email")]
                    sender_names = [f.get("name", "").lower() for f in from_entries if f.get("name")]
                    recipient_emails = [t.get("email", "").lower() for t in to_entries if t.get("email")]

                    # 1. Bulk / Automated ignore rule
                    if auto_ignore_bulk:
                        if any("noreply" in se or "no-reply" in se or "donotreply" in se or "mailer-daemon" in se for se in sender_emails):
                            self.ledger.increment_excluded_count(1)
                            continue

                    # 2. Learned/approved exclusion rules
                    if any(se in excluded_senders for se in sender_emails) or any(
                        any(se.endswith(f"@{ed}") or se.endswith(f".{ed}") for ed in excluded_domains)
                        for se in sender_emails
                    ):
                        self.ledger.increment_excluded_count(1)
                        continue

                    # 3. Check VIP Match
                    is_vip = False
                    for se in sender_emails:
                        if se in vip_emails:
                            is_vip = True
                            break
                        for vd in vip_domains:
                            if se.endswith(f"@{vd}") or se.endswith(f".{vd}"):
                                is_vip = True
                                break
                        if is_vip:
                            break

                    # Also check if recipient is a VIP or founder
                    if not is_vip:
                        for re in recipient_emails:
                            if re in vip_emails:
                                is_vip = True
                                break

                    # Also check keywords in subject or sender
                    if not is_vip and vip_keywords:
                        search_text = f"{subject} {' '.join(sender_names)} {' '.join(sender_emails)}"
                        for kw in vip_keywords:
                            if kw in search_text:
                                is_vip = True
                                break

                    # 4. Check directly addressed rule
                    is_directly_addressed = False
                    if include_directly_addressed and recipient_emails:
                        founder_email = (settings.get("founder_email") or "").lower().strip()
                        if founder_email:
                            if founder_email in recipient_emails and len(recipient_emails) <= 5:
                                is_directly_addressed = True
                        else:
                            if len(recipient_emails) <= 2 and not any("marketing" in se or "newsletter" in se or "events" in se or "webinar" in se for se in sender_emails):
                                is_directly_addressed = True

                    # If envelope has no sender or recipient info (e.g. synthetic test envelope), treat as VIP
                    if not sender_emails and not recipient_emails:
                        is_vip = True

                    if only_scan_vip and not is_vip and not is_directly_addressed:
                        # Excluded by VIP filter: increment predictable counter
                        self.ledger.increment_excluded_count(1)
                        continue

                    body = self._fetch_message_body(account, str(msg_id))
                    if body:
                        self._write_email_to_inbox(account, str(msg_id), body)
                        fetched += 1
                        file_path = self.inbox_path / file_name
                        if file_path.exists():
                            self.process_file(file_path, account=account)
            except subprocess.TimeoutExpired:
                print(f"[founder-signal] himalaya timed out for {account}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[founder-signal] error fetching {account}: {exc}", file=sys.stderr)

        print(f"[founder-signal] Heartbeat fetched {fetched} VIP email(s).")
        return fetched

    def _himalaya_accounts(self) -> list[str]:
        env = os.environ.get("FOUNDER_SIGNAL_HIMALAYA_ACCOUNTS", "")
        if env:
            return [a.strip() for a in env.split(",") if a.strip()]
        himalaya = self.himalaya_bin or resolve_himalaya_bin()
        if not himalaya:
            return []
        # Try to discover accounts from himalaya config.
        try:
            result = subprocess.run(
                [himalaya, "account", "list"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return [
                    line.split()[0]
                    for line in result.stdout.strip().splitlines()
                    if line.strip() and not line.startswith("┌")
                    and not line.startswith("│") and not line.startswith("└")
                    and not line.startswith("╞") and not line.startswith("═")
                ]
        except Exception:
            pass
        return []

    def _parse_envelope_json(self, output: str) -> list[dict]:
        """Parse himalaya envelope search --json output into a list of envelope dicts."""
        import json

        try:
            data = json.loads(output)
        except json.JSONDecodeError:
            return []
        if isinstance(data, dict):
            return data.get("envelopes", [])
        if isinstance(data, list):
            return data
        return []

    def _fetch_message_body(self, account: str, msg_id: str) -> Optional[str]:
        himalaya = self.himalaya_bin or resolve_himalaya_bin()
        if not himalaya:
            return None
        try:
            result = subprocess.run(
                [himalaya, "message", "read", "-a", account, msg_id],
                capture_output=True,
                text=True,
                timeout=60,
            )
            if result.returncode != 0:
                return None
            return result.stdout
        except Exception:
            return None

    def _write_email_to_inbox(self, account: str, msg_id: str, body: str) -> None:
        safe_id = "".join(c if c.isalnum() or c in "-_" else "_" for c in msg_id)
        file_name = f"email-{account}-{safe_id}.txt"
        file_path = self.inbox_path / file_name
        if not file_path.exists():
            header = f"From: himalaya/{account}\nMessage-ID: {msg_id}\nReceived: {datetime.now(timezone.utc).isoformat()}\n\n"
            file_path.write_text(header + body, encoding="utf-8")

    def generate_briefing(self):
        """Generate the morning briefing from the ledger."""
        return generate_briefing(self.ledger, coming_up_days=self.config.briefing_coming_up_days)

    def deliver_briefing(self, briefing, target: Optional[str] = None) -> bool:
        """Deliver the briefing via hermes send or write to file.

        Returns True on success.
        """
        target = target or os.environ.get("FOUNDER_SIGNAL_DELIVER_TO", "discord")

        lines = [
            "🔔 Founder Signal — Morning Briefing",
            f"Generated: {briefing.generated_at.strftime('%Y-%m-%d %H:%M')}",
            "",
            f"{briefing.summary}",
            "",
        ]

        if briefing.do_now:
            lines.append("## Do now")
            for c in briefing.do_now:
                lines.append(f"• {c.description} [due {c.due_date or '—'}]")
                if c.evidence:
                    lines.append(f'  Evidence: "{c.evidence[:120]}"')
            lines.append("")

        if briefing.coming_up:
            lines.append("## Coming up")
            for c in briefing.coming_up:
                lines.append(f"• {c.description} [due {c.due_date}]")
            lines.append("")

        if briefing.waiting_on:
            lines.append("## Waiting on someone")
            for c in briefing.waiting_on:
                lines.append(f"• {c.description} (owner: {c.owner}) [due {c.due_date or '—'}]")
            lines.append("")

        if briefing.needs_clarification:
            lines.append("## Needs clarification")
            for c in briefing.needs_clarification:
                missing = []
                if not c.owner:
                    missing.append("owner")
                if not c.due_date:
                    missing.append("due date")
                lines.append(f"• {c.description} (missing: {', '.join(missing)})")
            lines.append("")

        lines.append("---")
        lines.append("The agent proposes; nothing is marked complete without your confirmation.")
        message = "\n".join(lines)

        if target == "discord":
            return self._deliver_discord(message)
        if target == "file":
            return self._deliver_file(message)
        if target == "none":
            print(message)
            return True
        print(f"[founder-signal] Unknown delivery target: {target}", file=sys.stderr)
        return False

    def _deliver_discord(self, message: str) -> bool:
        settings = self.ledger.get_settings()
        target = settings.get("discord_alerts_target", "discord:alerts-and-logs")
        return send_discord_alert(message, target=target)

    def _deliver_file(self, message: str) -> bool:
        out_path = Path(
            os.path.expanduser(
                os.environ.get(
                    "FOUNDER_SIGNAL_BRIEFING_FILE", "~/founder-signal-briefing.md"
                )
            )
        )
        out_path.write_text(message, encoding="utf-8")
        print(f"[founder-signal] Briefing written to {out_path}.")
        return True

    def close(self) -> None:
        self.ledger.close()


def run_watcher(config: Config, once: bool = False, interval_seconds: int = 60) -> None:
    """Run the inbox watcher loop.

    Args:
        config: Founder Signal configuration.
        once: If True, scan once and exit.
        interval_seconds: Polling interval in seconds.
    """
    watcher = InboxWatcher(config)
    try:
        if once:
            count = watcher.scan()
            print(f"[founder-signal] Scan complete: {count} file(s) processed.")
        else:
            print(f"[founder-signal] Watching {watcher.inbox_path} (interval {interval_seconds}s). Ctrl+C to stop.")
            while True:
                count = watcher.scan()
                if count:
                    print(f"[founder-signal] Processed {count} file(s).")
                time.sleep(interval_seconds)
    finally:
        watcher.close()


def run_heartbeat(
    config: Config,
    accounts: Optional[list[str]] = None,
    days: Optional[int] = None,
) -> None:
    """Run a single heartbeat check: processes local inbox files AND checks VIP emails.

    Args:
        config: Founder Signal configuration.
        accounts: himalaya accounts to check (defaults to config/env).
        days: Optional number of lookback days (defaults to config.heartbeat_days).
    """
    watcher = InboxWatcher(config)
    try:
        local_count = watcher.scan()
        if local_count:
            print(f"[founder-signal] Processed {local_count} local inbox file(s).")
        fetched = watcher.heartbeat_email(accounts, days=days)
        print(f"[founder-signal] Heartbeat complete: {fetched} VIP email(s) fetched and processed.")
    finally:
        watcher.close()


def run_briefing(config: Config, target: Optional[str] = None) -> None:
    """Generate and deliver the morning briefing.

    Args:
        config: Founder Signal configuration.
        target: Delivery target (discord, file, none).
    """
    watcher = InboxWatcher(config)
    try:
        briefing = watcher.generate_briefing()
        print(briefing.summary)
        settings = watcher.ledger.get_settings()
        target = target or settings.get("discord_alerts_target", "discord:alerts-and-logs")
        app_url = settings.get("app_url", "http://127.0.0.1:5000")
        notify_morning_briefing(briefing, target=target, app_url=app_url)
    finally:
        watcher.close()
