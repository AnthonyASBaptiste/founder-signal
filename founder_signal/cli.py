"""Command-line ingestion point for Founder Signal.

Drop in email text and a voice-note transcript as input. The Founder Signal
skill extracts commitments, reconciles against the ledger, and emits a briefing.
The agent proposes; nothing is marked complete without confirmation.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Optional

from .config import Config
from .extraction import extract, to_commitments
from .ledger import open_ledger
from .models import Source
from .reconciliation import reconcile
from .briefing import generate_briefing


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

        # Persist source.
        ledger.add_source(source)

        # Run the Founder Signal skill (extraction).
        result = extract(source, use_llm=args.llm)
        print(result.summary)
        print(f"Source: {source.id} ({source.kind})")

        # Convert to proposed commitments.
        proposed = to_commitments(result, source.id)

        # Reconcile against existing ledger.
        reconciliation = reconcile(ledger, proposed, within_days=config.briefing_coming_up_days)
        print(reconciliation.summary)

        # Display issues requiring confirmation.
        for issue in reconciliation.issues:
            print(f"\n[!] {issue.kind.upper()}: {issue.description}")
            print(f"    Evidence: {issue.evidence[:120]}")
            if issue.proposed:
                print(f"    Proposed: {issue.proposed.description} | owner={issue.proposed.owner} | due={issue.proposed.due_date} | status={issue.proposed.status}")

        # Apply new commitments (proposed; user confirms via web UI or --confirm).
        added = 0
        for c in reconciliation.new_commitments:
            ledger.add_commitment(c)
            added += 1
        print(f"\nAdded {added} new commitment(s) to the ledger (status=open, awaiting your confirmation).")

        # Briefing.
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


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="founder-signal",
        description="Founder Signal — commitment extraction and reconciliation for founders.",
    )
    parser.add_argument("file", nargs="?", help="Path to email text or transcript (defaults to stdin).")
    parser.add_argument("--kind", default="email", choices=["email", "transcript", "voice-note"],
                        help="Type of source material.")
    parser.add_argument("--title", help="Title for the source material.")
    parser.add_argument("--llm", action="store_true", help="Use LLM extraction if OPENAI_API_KEY is set.")
    parser.add_argument("--confirm", action="store_true",
                        help="Confirm and persist proposed changes (default: propose only).")
    args = parser.parse_args(argv)

    config = Config.from_env()
    return _ingest(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
