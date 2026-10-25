"""Command-line interface for Founder Signal.

Ingest email text and voice-note transcripts, run the Founder Signal skill,
reconcile against the ledger, and deliver a morning briefing.

The agent proposes; nothing is marked complete without confirmation.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional, Sequence

from .config import Config
from .ledger import open_ledger
from .models import Source
from .extraction import extract, to_commitments
from .reconciliation import reconcile
from .briefing import generate_briefing
from .inbox import InboxWatcher, run_watcher, run_heartbeat, run_briefing


def _read_text(path: Optional[str]) -> str:
    if path:
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def _ingest(args, config: Config) -> int:
    ledger = open_ledger(config)
    try:
        body = _read_text(args.file)
        if not body.strip():
            print("Error: no input provided.", file=sys.stderr)
            return 1

        kind = args.kind
        title = args.title or (args.file or "stdin")
        source_id = f"{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}"
        source = Source(id=source_id, kind=kind, title=title, body=body)

        ledger.add_source(source)
        result = extract(source, use_llm=args.llm, config=config)
        print(result.summary)
        print(f"Source: {source.id} ({source.kind})")

        proposed = to_commitments(result, source.id)
        reconciliation = reconcile(ledger, proposed, within_days=config.briefing_coming_up_days)
        print(reconciliation.summary)

        for issue in reconciliation.issues:
            print(f"\n[!] {issue.kind.upper()}: {issue.description}")
            print(f"    Evidence: {issue.evidence[:120]}")
            if issue.proposed:
                print(
                    f"    Proposed: {issue.proposed.description} | "
                    f"owner={issue.proposed.owner} | due={issue.proposed.due_date} | "
                    f"status={issue.proposed.status}"
                )

        added = 0
        for c in reconciliation.new_commitments:
            ledger.add_commitment(c)
            added += 1

        applied = 0
        if args.apply:
            for issue in reconciliation.issues:
                if issue.kind == "change" and issue.proposed is not None:
                    ledger.update_commitment(issue.proposed)
                    applied += 1
            print(
                f"\nAdded {added} new commitment(s); applied {applied} proposed change(s) "
                f"to the ledger (status=open, awaiting your confirmation)."
            )
        else:
            print(f"\nAdded {added} new commitment(s) to the ledger (status=open, awaiting your confirmation).")

        briefing = generate_briefing(ledger, coming_up_days=config.briefing_coming_up_days)
        print("\n" + "=" * 50)
        print("MORNING BRIEFING")
        print("=" * 50)
        print(briefing.summary)
        print("\n-- Do now --")
        for c in briefing.do_now:
            print(f"  • {c.description} [due {c.due_date}] (source {c.source_id})")
        print("\n-- Coming up --")
        for c in briefing.coming_up:
            print(f"  • {c.description} [due {c.due_date}] (source {c.source_id})")
        print("\n-- Waiting on someone --")
        for c in briefing.waiting_on:
            print(f"  • {c.description} (owner {c.owner}) (source {c.source_id})")
        print("\n-- Needs clarification --")
        for c in briefing.needs_clarification:
            missing = []
            if not c.owner:
                missing.append("owner")
            if not c.due_date:
                missing.append("due date")
            print(f"  • {c.description} (missing: {', '.join(missing)}) (source {c.source_id})")

        return 0
    finally:
        ledger.close()


def _scan(args, config: Config) -> int:
    watcher = InboxWatcher(config)
    try:
        count = watcher.scan()
        print(f"[founder-signal] Scan complete: {count} file(s) processed.")
        return 0
    finally:
        watcher.close()


def _heartbeat(args, config: Config) -> int:
    accounts = args.accounts.split(",") if args.accounts else None
    run_heartbeat(config, accounts=accounts)
    return 0


def _briefing(args, config: Config) -> int:
    run_briefing(config, target=args.target)
    return 0


def _watch(args, config: Config) -> int:
    run_watcher(config, once=args.once, interval_seconds=args.interval)
    return 0


def _hermes_skill(args, config: Config) -> int:
    """Serve the Founder Signal Hermes skill endpoint."""
    from .hermes_skill import run_skill_server

    host = args.host or config.hermes_skill_host
    port = args.port or config.hermes_skill_port
    run_skill_server(config, host=host, port=port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="founder-signal",
        description="Founder Signal — commitment extraction and reconciliation for founders.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Ingest email text or a transcript from stdin or a file.")
    p_ingest.add_argument("file", nargs="?", help="Path to email text or transcript (defaults to stdin).")
    p_ingest.add_argument("--kind", default="email", choices=["email", "transcript", "voice-note"],
                          help="Type of source material.")
    p_ingest.add_argument("--title", help="Title for the source material.")
    p_ingest.add_argument("--llm", action="store_true", help="Use LLM extraction if OPENAI_API_KEY is set.")
    p_ingest.add_argument(
        "--apply", action="store_true",
        help="Apply proposed changes (e.g. moved deadlines) to the ledger. Without this, changes are only reported."
    )
    p_ingest.set_defaults(func=_ingest)

    p_scan = sub.add_parser("scan", help="Scan the inbox folder for new files and process them.")
    p_scan.set_defaults(func=_scan)

    p_hb = sub.add_parser("heartbeat", help="Fetch new email via himalaya and process through Founder Signal.")
    p_hb.add_argument("--accounts", help="Comma-separated himalaya accounts to check (overrides env).")
    p_hb.set_defaults(func=_heartbeat)

    p_brief = sub.add_parser("briefing", help="Generate and deliver the morning briefing.")
    p_brief.add_argument("--target", default=None, choices=["discord", "file", "none"],
                         help="Delivery target (overrides FOUNDER_SIGNAL_DELIVER_TO).")
    p_brief.set_defaults(func=_briefing)

    p_watch = sub.add_parser("watch", help="Continuously watch the inbox folder for new files.")
    p_watch.add_argument("--once", action="store_true", help="Scan once and exit.")
    p_watch.add_argument("--interval", type=int, default=60, help="Polling interval in seconds.")
    p_watch.set_defaults(func=_watch)

    p_hermes = sub.add_parser(
        "hermes-skill",
        help="Serve the Founder Signal skill as a Hermes-invokable HTTP endpoint.",
    )
    p_hermes.add_argument(
        "--host", default=None, help="Bind host (default: HERMES_SKILL_HOST or 127.0.0.1)."
    )
    p_hermes.add_argument(
        "--port", type=int, default=None, help="Bind port (default: HERMES_SKILL_PORT or 8765)."
    )
    p_hermes.set_defaults(func=_hermes_skill)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args_list = list(sys.argv[1:] if argv is None else argv)
    known_commands = {"ingest", "scan", "heartbeat", "briefing", "watch", "-h", "--help"}
    if args_list and args_list[0] not in known_commands:
        args_list.insert(0, "ingest")
    args = parser.parse_args(args_list)
    config = Config.from_env()
    return args.func(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
