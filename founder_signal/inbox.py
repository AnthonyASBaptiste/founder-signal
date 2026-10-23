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
from .models import Source, Commitment
from .extraction import extract, to_commitments
from .reconciliation import reconcile
from .briefing import generate_briefing

HIMALAYA_BIN = "/home/anthony/.local/bin/himalaya"
HERMES_BIN = "/home/anthony/.local/bin/hermes"


class InboxWatcher:
    """Watch an inbox folder and process new files through Founder Signal."""

    def __init__(self, config: Config):
        self.config = config
        self.inbox_path = Path(
            os.path.expanduser(
                os.environ.get("FOUNDER_SIGNAL_INBOX", "~/founder-signal-inbox")
            )
        )
        self.processed_path = self.inbox_path / "processed"
        self.ledger = open_ledger(config)

    def ensure_dirs(self) -> None:
        self.inbox_path.mkdir(parents=True, exist_ok=True)
        self.processed_path.mkdir(parents=True, exist_ok=True)

    def scan(self) -> int:
        """Scan the inbox for new files and process them.

        Returns the number of files processed.
        """
        self.ensure_dirs()
        processed = 0
        for file_path in sorted(self.inbox_path.iterdir()):
            if not file_path.is_file():
                continue
            if file_path.suffix.lower() not in (".txt", ".md"):
                continue
            if file_path.name.endswith(".done"):
                continue
            self.process_file(file_path)
            processed += 1
        return processed

    def process_file(self, file_path: Path) -> None:
        """Process a single inbox file through extraction, reconciliation, briefing."""
        body = file_path.read_text(encoding="utf-8", errors="replace")
        if not body.strip():
            self._mark_done(file_path)
            return

        kind = self._guess_kind(file_path)
        title = file_path.stem
        source_id = f"inbox:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
        source = Source(id=source_id, kind=kind, title=title, body=body)

        # Persist source.
        self.ledger.add_source(source)

        # Run the Founder Signal skill (extraction).
        result = extract(source, use_llm=False)

        # Convert to proposed commitments and reconcile.
        proposed = to_commitments(result, source.id)
        reconciliation = reconcile(
            self.ledger, proposed, within_days=self.config.briefing_coming_up_days
        )

        # Add new commitments to the ledger (proposed; awaiting confirmation).
        for c in reconciliation.new_commitments:
            self.ledger.add_commitment(c)

        # Mark file as processed.
        self._mark_done(file_path)

        print(
            f"[founder-signal] Processed {file_path.name}: "
            f"{len(reconciliation.new_commitments)} new commitment(s), "
            f"{len(reconciliation.issues)} issue(s) needing review."
        )

    def _guess_kind(self, file_path: Path) -> str:
        name = file_path.name.lower()
        if "voice" in name or "memo" in name:
            return "voice-note"
        if "meeting" in name or "transcript" in name:
            return "transcript"
        return "email"

    def _mark_done(self, file_path: Path) -> None:
        dest = self.processed_path / file_path.name
        if dest.exists():
            dest = self.processed_path / f"{file_path.stem}.{int(time.time())}{file_path.suffix}"
        shutil.move(str(file_path), str(dest))
        # Write a .done marker alongside the original location for audit.
        marker = self.inbox_path / f"{file_path.name}.done"
        marker.write_text(
            f"processed at {datetime.now(timezone.utc).isoformat()}\n",
            encoding="utf-8",
        )

    def heartbeat_email(self, accounts: Optional[list[str]] = None) -> int:
        """Fetch new email via himalaya and write to the inbox folder.

        Returns the number of emails fetched.
        """
        if not os.path.exists(HIMALAYA_BIN):
            print(f"[founder-signal] himalaya not found at {HIMALAYA_BIN}", file=sys.stderr)
            return 0

        self.ensure_dirs()
        accounts = accounts or self._himalaya_accounts()
        if not accounts:
            print("[founder-signal] No himalaya accounts configured.", file=sys.stderr)
            return 0

        since = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        fetched = 0

        for account in accounts:
            try:
                # Search envelopes received since yesterday, output as JSON.
                result = subprocess.run(
                    [
                        HIMALAYA_BIN,
                        "envelope",
                        "search",
                        "-a",
                        account,
                        "--json",
                        f"after {since}",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
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
                    # Skip if already in inbox.
                    safe_id = "".join(
                        c if c.isalnum() or c in "-_" else "_" for c in str(msg_id)
                    )
                    file_name = f"email-{account}-{safe_id}.txt"
                    if (self.inbox_path / file_name).exists():
                        continue
                    body = self._fetch_message_body(account, str(msg_id))
                    if body:
                        self._write_email_to_inbox(account, str(msg_id), body)
                        fetched += 1
            except subprocess.TimeoutExpired:
                print(f"[founder-signal] himalaya timed out for {account}", file=sys.stderr)
            except Exception as exc:  # noqa: BLE001
                print(f"[founder-signal] error fetching {account}: {exc}", file=sys.stderr)

        print(f"[founder-signal] Heartbeat fetched {fetched} email(s).")
        return fetched

    def _himalaya_accounts(self) -> list[str]:
        env = os.environ.get("FOUNDER_SIGNAL_HIMALAYA_ACCOUNTS", "")
        if env:
            return [a.strip() for a in env.split(",") if a.strip()]
        # Try to discover accounts from himalaya config.
        try:
            result = subprocess.run(
                [HIMALAYA_BIN, "account", "list"],
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
        try:
            result = subprocess.run(
                [HIMALAYA_BIN, "message", "read", "-a", account, msg_id],
                capture_output=True,
                text=True,
                timeout=30,
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
        try:
            result = subprocess.run(
                [HERMES_BIN, "send", "--to", "discord", "--subject", "Founder Signal Briefing"],
                input=message,
                text=True,
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0:
                print("[founder-signal] Briefing delivered to Discord.")
                return True
            print(
                f"[founder-signal] Discord delivery failed: {result.stderr.strip()}",
                file=sys.stderr,
            )
            return False
        except Exception as exc:  # noqa: BLE001
            print(f"[founder-signal] Discord delivery error: {exc}", file=sys.stderr)
            return False

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


def run_heartbeat(config: Config, accounts: Optional[list[str]] = None) -> None:
    """Run a single heartbeat email check.

    Args:
        config: Founder Signal configuration.
        accounts: himalaya accounts to check (defaults to config/env).
    """
    watcher = InboxWatcher(config)
    try:
        fetched = watcher.heartbeat_email(accounts)
        # After fetching, process any new inbox files.
        count = watcher.scan()
        print(f"[founder-signal] Heartbeat complete: {fetched} email(s) fetched, {count} file(s) processed.")
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
        watcher.deliver_briefing(briefing, target=target)
    finally:
        watcher.close()
