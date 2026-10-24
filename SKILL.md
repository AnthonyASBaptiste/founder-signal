# Founder Signal — Hermes Skill

## Name
`founder-signal`

## Description
Extracts commitments, deadlines, owners, decisions, and promised follow-ups
from founder inbound material (email, voice-note transcripts, meeting
transcripts), reconciles them against a persistent commitment ledger, and
emits a tiny action briefing:

**Do now · Coming up · Waiting on someone · Needs clarification**

Every commitment is anchored to verbatim source evidence. The agent
**proposes**; it never sends messages, accepts commitments, or marks tasks
complete without your confirmation.

## Install

1. Clone this repo and install dependencies:

   ```bash
   pip install -r requirements.txt
   cp .env.example .env
   # Adjust FOUNDER_NAME / FOUNDER_EMAIL and LEDGER_SQLITE_PATH as needed.
   ```

2. Start the Founder Signal skill endpoint:

   ```bash
   python -m founder_signal.cli hermes-skill
   # Serves http://127.0.0.1:8765/skills/founder-signal
   ```

   Configure host/port with `HERMES_SKILL_HOST` / `HERMES_SKILL_PORT`.

3. Tell Hermes about the skill. Point Hermes at the skill endpoint:

   ```
   http://127.0.0.1:8765/skills/founder-signal/invoke
   ```

   The skill manifest is available at:

   ```
   GET http://127.0.0.1:8765/skills/founder-signal/manifest
   ```

   When Hermes encounters a message containing commitments (an accelerator
   update, a co-founder note, a meeting transcript), it invokes this skill
   with the message text and receives back proposed commitments, duplicate/
   change/missing-detail/deadline issues, and a morning briefing.

## Input (POST /skills/founder-signal/invoke)

```json
{
  "input": "I will send the deck to Sarah by Friday, October 30.",
  "source_kind": "email",
  "source_title": "Accelerator update — Acme",
  "account": "gmail",
  "use_llm": false
}
```

| Field | Required | Description |
|---|---|---|
| `input` | yes | Source text to analyze. |
| `source_kind` | no | `email` \| `transcript` \| `voice-note` (default `email`). |
| `source_title` | no | Human-readable title for the source. |
| `account` | no | himalaya account for per-account founder identity. |
| `use_llm` | no | Use LLM extraction (Ollama/OpenAI) when available; otherwise rule-based. |

## Output

```json
{
  "ok": true,
  "source": { ... },
  "commitments": [
    { "id": "...", "description": "Send deck to Sarah", "owner": "me",
      "due_date": "2026-10-30", "direction": "user_committing",
      "evidence": "I will send the deck to Sarah by Friday, October 30.",
      "confidence": 0.6, "status": "open" }
  ],
  "decisions": [],
  "follow_ups": [],
  "summary": "Extracted 1 commitment(s) ...",
  "reconciliation": {
    "new_commitments": [ ... ],
    "issues": [
      { "kind": "change", "commitment_id": "...", "description": "...",
        "proposed": { ... }, "evidence": "..." }
    ],
    "summary": "1 new commitment(s), 1 issue(s) needing review."
  },
  "briefing": {
    "do_now": [], "coming_up": [], "waiting_on": [], "needs_clarification": [],
    "summary": "..."
  }
}
```

## Demo

See `demo/demo.sh` for a reproducible, scripted demo of Hermes invoking the
Founder Signal skill end to end: ingest → cited commitment → reconciliation
issue (deadline moved Friday → Monday) → morning briefing.

## Safety

The skill proposes changes only. Applying a proposed change (e.g. a moved
deadline) requires your confirmation — in the CLI, `founder-signal ingest
--apply`; in the web UI, open the commitment and confirm/edit it.
