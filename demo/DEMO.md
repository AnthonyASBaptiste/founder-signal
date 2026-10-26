# Founder Signal Demo

Judge-ready demo for Hacktoberfest Week 3 — "Slow and Steady".

This demo runs the full commitment extraction → reconciliation → briefing → Hermes skill invocation workflow end to end.

## What the demo shows

1. **Ingest an accelerator email** — two commitments are extracted and added to an isolated demo ledger, each anchored to verbatim source evidence.
2. **Ingest a follow-up email** — reconciliation detects that a deadline has changed (Friday → Monday) and proposes an update, retaining both source quotes as evidence.
3. **Apply the change** — with `--apply`, the user confirms and the ledger is updated. The agent proposes; nothing is applied without confirmation.
4. **Morning briefing** — a concise "Do now · Coming up · Waiting on someone · Needs clarification" brief reflects the updated commitment.
5. **Hermes HTTP skill integration** — starts the agent-facing Hermes skill server, queries `GET /skills/founder-signal/manifest` for skill discovery, and performs a live `POST /skills/founder-signal/invoke` call to demonstrate how autonomous agents interact with Founder Signal over HTTP.

## How to run

### 1. Default (Offline, Zero-Config, Local Temp Database)
Runs completely offline with deterministic rules and an isolated temporary SQLite database:

```bash
FOUNDER_NAME=Anthony bash demo/demo.sh
```

**Database Safety**: The demo script creates a unique temporary database file using `mktemp -t founder-signal-demo-XXXXXX.db` and registers an exit trap to clean it up upon completion. It **never deletes or mutates** any caller-supplied database path or existing production ledger.

### 2. Optional: Run with Local Gemma Open-Weight Model
If you have [Ollama](https://ollama.com/) running with Google's Gemma model (`gemma4:e2b-it-qat`):

```bash
bash demo/demo.sh --gemma
```

### 3. Optional: Run with MongoDB Atlas Cloud Ledger
If you have configured `MONGODB_URI` in `.env`:

```bash
bash demo/demo.sh --mongodb
```

## Sample data

- `demo/samples/accelerator-update.txt` — accelerator update email with two action items (deck to Sarah, investor list).
- `demo/samples/schedule-change.txt` — follow-up email moving the deck deadline from Friday to Monday.

## Effort saved (estimate)

Without Founder Signal, a founder would need to:

- Reread each accelerator email and co-founder update to find action items
- Manually copy commitments into a todo list or CRM
- Notice when a deadline changes across multiple email threads
- Reconcile the new date against the old commitment
- Remember to check what's due this week

Estimated time spent per week on this "commitment tracking" chore: **30–60 minutes** (reading, copying, reconciling, following up).

With Founder Signal: **~2 minutes** to ingest the week's sources and read the morning briefing.

**Estimated effort saved: ~25–55 minutes per week** (clearly labeled as an estimate, not a measured result). Actual savings depend on email volume and how many commitments change week to week.

## Open-source AI used

- **Rule-based extractor** (deterministic, no model required) — works offline
- **Ollama** — local, privacy-first LLM extraction via `gemma4:e2b-it-qat` (open-weight model)
- **OpenAI** (optional) — API-based extraction when an API key is present
- **Flask** — web UI and Hermes skill endpoint
- **SQLite & MongoDB Atlas** — local zero-config and cloud cluster commitment ledgers

## Hermes integration

Founder Signal exposes a Hermes-compatible skill endpoint:

```bash
python3 -m founder_signal.cli hermes-skill
```

Serves:
- `GET /skills/founder-signal/manifest`: Schema and system prompt instructions for Hermes.
- `POST /skills/founder-signal/invoke`: Ingestion, extraction, and briefing execution for Hermes agents.
- `GET /health`: Health-check endpoint.

See `SKILL.md` for the full manifest and installation instructions.
