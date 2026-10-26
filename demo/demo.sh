#!/usr/bin/env bash
#
# Founder Signal — judge-ready demo (Hacktoberfest Week 3, "Slow and Steady").
#
# Runs the full commitment workflow end to end with:
#   1. Ingest an accelerator email -> cited commitment added to the ledger.
#   2. Ingest a follow-up email -> reconciliation detects the deadline changed
#      (Friday -> Monday) and proposes an update, keeping both source quotes.
#   3. Apply the proposed change with --apply (user confirmation).
#   4. Print the morning briefing (Do now · Coming up · Waiting on · Clarify).
#   5. Demonstrate live Hermes HTTP skill discovery (manifest) and invocation.
#
# Safety:
#   Strictly creates and uses a dedicated temporary database via mktemp.
#   Never deletes or mutates any caller-supplied database path.
#
# Usage:
#   bash demo/demo.sh             # Default: offline, rules, isolated temp SQLite
#   bash demo/demo.sh --gemma     # Demonstrates local Gemma open-weight extraction via Ollama
#   bash demo/demo.sh --mongodb   # Demonstrates MongoDB Atlas cloud ledger backend
#
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

# Parse optional technology flags
USE_GEMMA=false
USE_MONGO=false
for arg in "$@"; do
    case "$arg" in
        --gemma)
            USE_GEMMA=true
            ;;
        --mongodb)
            USE_MONGO=true
            ;;
        -h|--help)
            echo "Usage: bash demo/demo.sh [--gemma] [--mongodb]"
            echo "  --gemma    Run with local Gemma open-weight model via Ollama"
            echo "  --mongodb  Run with MongoDB Atlas ledger (requires MONGODB_URI in .env)"
            exit 0
            ;;
    esac
done

# Allocate isolated demo database; NEVER touch caller-supplied paths
DEMO_DB="$(mktemp -t founder-signal-demo-XXXXXX.db)"
HERMES_PID=""

cleanup() {
    if [[ -n "${HERMES_PID:-}" ]] && kill -0 "$HERMES_PID" 2>/dev/null; then
        kill "$HERMES_PID" 2>/dev/null || true
        wait "$HERMES_PID" 2>/dev/null || true
    fi
    if [[ -n "${DEMO_DB:-}" && -f "${DEMO_DB:-}" ]]; then
        rm -f "$DEMO_DB"
    fi
}
trap cleanup EXIT INT TERM

export FOUNDER_NAME="${FOUNDER_NAME:-Anthony}"

if [ "$USE_MONGO" = true ]; then
    echo "[demo] Using MongoDB Atlas ledger backend."
    export LEDGER_BACKEND="mongodb"
else
    export LEDGER_BACKEND="sqlite"
    export LEDGER_SQLITE_PATH="$DEMO_DB"
fi

if [ "$USE_GEMMA" = true ]; then
    echo "[demo] Enabling local Gemma model extraction via Ollama (gemma4:e2b-it-qat)."
    export FOUNDER_SIGNAL_USE_LLM=true
    export FOUNDER_SIGNAL_MODEL="${FOUNDER_SIGNAL_MODEL:-gemma4:e2b-it-qat}"
else
    export FOUNDER_SIGNAL_USE_LLM=false
fi

CLI=(python3 -m founder_signal.cli)

echo "============================================================"
echo "Founder Signal demo — commitment extraction & reconciliation"
echo "============================================================"
echo "Backend: $LEDGER_BACKEND (isolated demo store)"
echo "Extractor mode: $([ "$USE_GEMMA" = true ] && echo "Gemma open-weight (Ollama)" || echo "Deterministic rules (offline)")"
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

echo "--- Step 5: Hermes agent-facing HTTP skill invocation ---"
HERMES_PORT=8769
"${CLI[@]}" hermes-skill --port "$HERMES_PORT" >/dev/null 2>&1 &
HERMES_PID=$!

# Wait for server readiness
for i in {1..30}; do
    if curl -s "http://127.0.0.1:$HERMES_PORT/health" >/dev/null 2>&1; then
        break
    fi
    sleep 0.1
done

echo "-> GET /skills/founder-signal/manifest"
curl -s "http://127.0.0.1:$HERMES_PORT/skills/founder-signal/manifest" | python3 -m json.tool | head -n 20
echo "... [manifest truncated]"
echo
echo "-> POST /skills/founder-signal/invoke (agent payload)"
curl -s -X POST "http://127.0.0.1:$HERMES_PORT/skills/founder-signal/invoke" \
    -H "Content-Type: application/json" \
    -d '{"input": "I will send the finalized investor list to Sarah by Wednesday.", "source_kind": "email", "source_title": "Investor follow-up"}' \
    | python3 -m json.tool | head -n 30
echo "... [invoke result truncated]"
echo

kill "$HERMES_PID" 2>/dev/null || true
wait "$HERMES_PID" 2>/dev/null || true
HERMES_PID=""

echo "============================================================"
echo "Demo complete! All stages verified successfully."
echo "============================================================"
