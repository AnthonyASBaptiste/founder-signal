# Founder Signal

A specialist agent for founders who receive more information, requests, and opportunities than they have time to process.

Founder Signal is a **commitment extraction and reconciliation workflow** — not a dashboard wrapped around an LLM. You drop in source material (email text, voice-note transcripts, meeting transcripts), the Founder Signal skill extracts commitments/deadlines/owners/decisions/follow-ups, reconciles them against a persistent commitment ledger, and emits a tiny action briefing:

**Do now · Coming up · Waiting on someone · Needs clarification**

## The flow

1. **Give Founder Signal the source material** — accelerator emails, co-founder messages, voice notes, meeting transcripts.
2. **Founder Signal skill** — extracts commitments, deadlines, owners, decisions, and promised follow-ups, each anchored to verbatim source evidence.
3. **Reconcile against existing commitments** — detects changes, duplicates, missing details, and approaching deadlines; retains source evidence.
4. **Deliver a tiny action brief** — Do now · Coming up · Waiting on someone · Needs clarification.

## Safety

The agent **proposes** changes; it never sends messages, accepts commitments, or marks tasks complete without your confirmation.

## First version

- **Input:** Drop in email text, a voice note audio file, or a meeting transcript file. No OAuth, no multi-account integrations.
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
deploy/              systemd service + timer for periodic heartbeat
```

## Setup

```bash
# Clone the repository
git clone https://github.com/AnthonyASBaptiste/founder-signal.git
cd founder-signal

# Install dependencies
pip install -r requirements.txt

# Copy env config
cp .env.example .env
# Edit .env: set MONGODB_URI for MongoDB Atlas (default: SQLite),
# FOUNDER_NAME / FOUNDER_EMAIL, and per-account founder identity if needed.
```

## Ingestion — three ways

### 1. Web UI (type-specific inputs)

```bash
python run.py
# Open http://127.0.0.1:5000
# Click "Ingest"
```

| Type | Input | What happens |
|------|-------|--------------|
| **Email** | Paste text | Extracted for commitments immediately |
| **Meeting transcript** | File upload (`.txt`, `.md`) | Read as text, extracted for commitments |
| **Voice note** | Audio file upload (`.mp3`, `.wav`, `.m4a`, `.ogg`, `.aac`) | Saved to inbox folder; flagged "transcription needed" |

### 2. Inbox folder (drop files here)

Default: `~/Downloads/founder-signal-inbox` (override with `FOUNDER_SIGNAL_INBOX`).

Drop `.txt`, `.md`, or audio files into this folder. Run the watcher to process them:

```bash
# Scan once
python -m founder_signal.cli scan

# Watch continuously (polls every 60s)
python -m founder_signal.cli watch
```

### 3. CLI ingestion

```bash
# Pipe email text or a transcript
cat email.txt | python -m founder_signal.cli --kind email --title "Accelerator update"

# Or pass a file
python -m founder_signal.cli transcript.txt --kind transcript --title "Weekly sync"
```

### 4. Heartbeat (fetch new email via himalaya)

Fetches new email from configured himalaya accounts and processes them:

```bash
python -m founder_signal.cli heartbeat --accounts zoho,gmail
```

## Periodic heartbeat (systemd timer)

`deploy/founder-signal-heartbeat.timer` runs the heartbeat every 15 minutes:

```bash
sudo cp deploy/founder-signal-heartbeat.service deploy/founder-signal-heartbeat.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now founder-signal-heartbeat.timer
```

Before enabling, edit `deploy/founder-signal-heartbeat.service` to set
`WorkingDirectory` to your Founder Signal checkout and `EnvironmentFile` to
your `.env` location. The paths are intentionally not hard-coded to a
specific machine — adjust them for your environment.

The service runs `python -m founder_signal.cli heartbeat --accounts zoho,gmail`.
Edit the `--accounts` list in the service file or override via CLI args.

## Web UI

The web UI lets you:
- View the commitment ledger and morning briefing.
- Ingest new source material via the type-specific form.
- Open each commitment to review/edit its description, owner, due date, status, and verbatim evidence.
- Mark commitments as done / ignore / reopen (ignored items are hidden from open views).
- Confirm proposed changes (nothing is applied without your action).

## Configuration (`.env`)

| Variable | Default | Description |
|---|---|---|
| `LEDGER_BACKEND` | `sqlite` | `sqlite` (local demo) or `mongodb` (MongoDB Atlas) |
| `LEDGER_SQLITE_PATH` | `data/founder_signal.db` | SQLite database path |
| `MONGODB_URI` | — | MongoDB Atlas connection string |
| `MONGODB_DATABASE` | `founder_signal` | Database name |
| `HERMES_SKILL_HOST` | `127.0.0.1` | Hermes skill server host |
| `HERMES_SKILL_PORT` | `8765` | Hermes skill server port |
| `HERMES_SKILL_ENDPOINT` | `http://127.0.0.1:8765/skills/founder-signal` | Hermes skill invoke endpoint |
| `WEB_HOST` / `WEB_PORT` | `127.0.0.1` / `5000` | Web UI bind address |
| `BRIEFING_COMING_UP_DAYS` | `7` | Days ahead for "Coming up" |
| `FOUNDER_SIGNAL_INBOX` | `~/Downloads/founder-signal-inbox` | Inbox folder for dropped files |
| `FOUNDER_SIGNAL_MAX_UPLOAD_MB` | `25` | Max web upload size in MB |
| `FOUNDER_SIGNAL_UPLOAD_EXTENSIONS` | `txt,md,mp3,wav,m4a,ogg,aac` | Allowed upload extensions |
| `OPENAI_API_KEY` | — | Enables OpenAI-based extraction |
| `OLLAMA_HOST` | `http://localhost:11434` | Local Ollama host for privacy-first extraction |
| `FOUNDER_SIGNAL_MODEL` | `gemma4:e2b-it-qat` | Ollama model to use |
| `FOUNDER_SIGNAL_USE_LLM` | `false` | Set `true` to enable LLM extraction (Ollama or OpenAI) |
| `FOUNDER_NAME` | `Anthony` | Founder name (used to identify commitments directed at you) |
| `FOUNDER_EMAIL` | — | Founder email |
| `FOUNDER_NAME_<ACCOUNT>` | — | Per-account founder name override (e.g. `FOUNDER_NAME_ZOHO`) |
| `FOUNDER_EMAIL_<ACCOUNT>` | — | Per-account founder email override (e.g. `FOUNDER_EMAIL_ZOHO`) |

Per-account founder identity lets you use different founder names/emails for different himalaya accounts (e.g. zoho vs gmail). The account key is uppercased with `-` and `.` replaced by `_`.

## Running tests

```bash
pip install pytest
python -m pytest tests/ -v
```

## Demo

A scripted, judge-ready demo runs the full workflow offline (no API keys):

```bash
FOUNDER_NAME=Anthony bash demo/demo.sh
```

See `demo/DEMO.md` for the walkthrough, sample data, and effort-saved estimate.

## Hackathon

This is a submission for **Hacktoberfest Week 3 — theme: Slow and Steady**. The focus is a durable, local-first commitment ledger and reconciliation workflow rather than a flashy dashboard.

## License

MIT
