# Founder Signal

A specialist agent for founders who receive more information, requests, and opportunities than they have time to process.

Founder Signal is a **commitment extraction and reconciliation workflow** — not a dashboard wrapped around an LLM. You drop in source material (email text, voice-note transcripts, meeting transcripts), the Founder Signal skill extracts commitments/deadlines/owners/decisions/follow-ups, reconciles them against a persistent commitment ledger, and emits a tiny action briefing:

**Do now · Coming up · Waiting on someone · Needs clarification**

## The flow

1. **Give Hermes the source material** — accelerator emails, co-founder messages, voice notes, meeting transcripts.
2. **Founder Signal skill** — extracts commitments, deadlines, owners, decisions, and promised follow-ups, each anchored to verbatim source evidence.
3. **Reconcile against existing commitments** — detects changes, duplicates, missing details, and approaching deadlines; retains source evidence.
4. **Deliver a tiny action brief** — Do now · Coming up · Waiting on someone · Needs clarification.

## Safety

The agent **proposes** changes; it never sends messages, accepts commitments, or marks tasks complete without your confirmation.

## First version

- **Input:** Drop in email text and a voice note or its transcript. No OAuth, no multi-account integrations.
- **Agent:** Hermes runs a dedicated Founder Signal skill with explicit instructions and structured outputs.
- **Memory:** Persistent commitment ledger (SQLite by default; MongoDB Atlas optional) with source references, due dates, status, and last-updated timestamps.
- **Output:** Concise morning briefing, with optional on-demand review.
- **Interface:** Small web UI to inspect the ledger and confirm proposed actions.

## Project structure

```
founder_signal/
  __init__.py        Package + config
  config.py          Environment-driven configuration
  models.py          Source + Commitment data models
  ledger.py          SQLite + MongoDB Atlas ledger backends
  extraction.py      Founder Signal skill (structured extraction)
  reconciliation.py  Change/duplicate/missing-detail/deadline detection
  briefing.py        Morning briefing (Do now · Coming up · …)
  cli.py             CLI ingestion point
  app.py             Flask web UI
  web/templates/     HTML templates
tests/               Test suite
```

## Setup

```bash
# Clone / open the worktree
cd /home/anthony/Projects/founder-signal/.worktrees/anthonyasbaptiste-founder-signal

# Install dependencies
pip install -r requirements.txt

# Copy env config
cp .env.example .env
# Edit .env to point MONGODB_URI at MongoDB Atlas if desired (default: SQLite)
```

## Usage

### CLI ingestion

```bash
# Pipe email text or a transcript
cat email.txt | python -m founder_signal.cli --kind email --title "Accelerator update"

# Or pass a file
python -m founder_signal.cli transcript.txt --kind transcript --title "Weekly sync"
```

### Web UI

```bash
python run.py
# Open http://127.0.0.1:5000
```

The web UI lets you:
- View the commitment ledger and morning briefing.
- Ingest new source material via a form.
- Open each commitment to review/edit its description, owner, due date, status, and verbatim evidence.
- Confirm proposed changes (nothing is applied without your action).

### Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `LEDGER_BACKEND` | `sqlite` | `sqlite` (local demo) or `mongodb` (MongoDB Atlas) |
| `LEDGER_SQLITE_PATH` | `data/founder_signal.db` | SQLite database path |
| `MONGODB_URI` | — | MongoDB Atlas connection string |
| `MONGODB_DATABASE` | `founder_signal` | Database name |
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `5000` | Web UI bind address |
| `BRIEFING_COMING_UP_DAYS` | `7` | Days ahead for "Coming up" |
| `OPENAI_API_KEY` | — | Enables OpenAI-based extraction in the skill |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama host for privacy-first extraction |
| `FOUNDER_SIGNAL_MODEL` | `gemma4:e2b-it-qat` | Ollama model to use |
| `FOUNDER_SIGNAL_USE_LLM` | `false` | Set `true` to enable LLM extraction (Ollama or OpenAI) |

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Hackathon

This is a submission for **Hacktoberfest Week 3 — theme: Slow and Steady**. The focus is a durable, local-first commitment ledger and reconciliation workflow rather than a flashy dashboard.

## License

MIT
