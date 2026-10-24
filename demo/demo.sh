#!/usr/bin/env bash
#
# Founder Signal — judge-ready demo (Hacktoberfest Week 3, "Slow and Steady").
#
# Runs the full commitment workflow end to end with the rule-based extractor
# (no API keys, no network, works offline):
#
#   1. Ingest an accelerator email -> cited commitment added to the ledger.
#   2. Ingest a follow-up email -> reconciliation detects the deadline changed
#      (Friday -> Monday) and proposes an update, keeping both source quotes.
#   3. Apply the proposed change with --apply (the user confirms).
#   4. Print the morning briefing (Do now · Coming up · Waiting on · Clarify).
#
# Usage:
#   cd <repo>
#   FOUNDER_NAME=Anthony bash demo/demo.sh
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

export LEDGER_BACKEND=sqlite
export LEDGER_SQLITE_PATH="${LEDGER_SQLITE_PATH:-/tmp/founder-signal-demo.db}"
export FOUNDER_NAME="${FOUNDER_NAME:-Anthony}"
export FOUNDER_SIGNAL_USE_LLM=false

rm -f "$LEDGER_SQLITE_PATH"

CLI=(python -m founder_signal.cli)

echo "============================================================"
echo "Founder Signal demo — commitment extraction & reconciliation"
echo "============================================================"
echo

echo "--- Step 1: ingest accelerator email (new commitment) ---"
"${CLI[@]}" ingest demo/samples/accelerator-update.txt \
    --kind email --title "Accelerator update — Acme"
echo

echo "--- Step 2: ingest follow-up (deadline moved Friday -> Monday) ---"
"${CLI[@]}" ingest demo/samples/schedule-change.txt \
    --kind email --title "Re: deck timeline"
echo

echo "--- Step 3: apply the proposed change (user confirmation) ---"
"${CLI[@]}" ingest demo/samples/schedule-change.txt \
    --kind email --title "Re: deck timeline" --apply
echo

echo "--- Step 4: morning briefing ---"
"${CLI[@]}" briefing --target none
echo

echo "Demo complete. Ledger: $LEDGER_SQLITE_PATH"
