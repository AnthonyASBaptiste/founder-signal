# Founder Signal Demo

Judge-ready demo for Hacktoberfest Week 3 — "Slow and Steady".

This demo runs the full commitment extraction → reconciliation → briefing
workflow end to end, offline, with no API keys. It uses the deterministic
rule-based extractor so it works on any machine.

## What the demo shows

1. **Ingest an accelerator email** — two commitments are extracted and added
   to the local commitment ledger, each anchored to verbatim source evidence.
2. **Ingest a follow-up email** — reconciliation detects that a deadline has
   changed (Friday → Monday) and proposes an update, retaining both source
   quotes as evidence.
3. **Apply the change** — with `--apply`, the user confirms and the ledger is
   updated. The agent proposes; nothing is applied without confirmation.
4. **Morning briefing** — a concise "Do now · Coming up · Waiting on someone ·
   Needs clarification" brief reflects the updated commitment.

## How to run

```bash
cd <repo-directory>
FOUNDER_NAME=Anthony bash demo/demo.sh
```

The script:
- Creates a fresh SQLite ledger at `/tmp/founder-signal-demo.db`
- Runs `python -m founder_signal.cli ingest` for each sample email
- Runs the second ingest twice: once without `--apply` (to show the proposed
  change), once with `--apply` (to confirm it)
- Prints the morning briefing after each step

No network, no API keys, no LLM required. The rule-based extractor runs
offline.

## Sample data

- `demo/samples/accelerator-update.txt` — accelerator update email with two
  action items (deck to Sarah, investor list).
- `demo/samples/schedule-change.txt` — follow-up email moving the deck
  deadline from Friday to Monday.

## Effort saved (estimate)

Without Founder Signal, a founder would need to:

- Reread each accelerator email and co-founder update to find action items
- Manually copy commitments into a todo list or CRM
- Notice when a deadline changes across multiple email threads
- Reconcile the new date against the old commitment
- Remember to check what's due this week

Estimated time spent per week on this "commitment tracking" chore: **30–60
minutes** (reading, copying, reconciling, following up).

With Founder Signal: **~2 minutes** to ingest the week's sources and read the
morning briefing.

**Estimated effort saved: ~25–55 minutes per week** (clearly labeled as an
estimate, not a measured result). Actual savings depend on email volume and
how many commitments change week to week.

## Open-source AI used

- **Rule-based extractor** (deterministic, no model required) — works offline
- **Ollama** (optional) — local, privacy-first LLM extraction via
  `gemma4:e2b-it-qat` (open-weight model)
- **OpenAI** (optional) — API-based extraction when an API key is present
- **Flask** — web UI and Hermes skill endpoint
- **SQLite** — local commitment ledger

## Hermes integration

Founder Signal exposes a Hermes-compatible skill endpoint:

```bash
python -m founder_signal.cli hermes-skill
```

Serves `GET /skills/founder-signal/manifest`, `POST /skills/founder-signal/invoke`,
and `GET /health`. See `SKILL.md` for the full manifest and install instructions.
