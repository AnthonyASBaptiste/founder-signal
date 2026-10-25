# Founder Signal: a local, evidence-backed commitment ledger for founders

## What it does

Founder Signal is a commitment extraction and reconciliation workflow — not a
dashboard wrapped around an LLM. Founders receive more information, requests,
and opportunities than they have time to process. Promises get scattered
across accelerator emails, co-founder messages, and voice notes, and it's easy
to lose track of what you said you'd do.

Founder Signal fixes that. You drop in source material (email text, voice-note
transcripts, meeting transcripts), and the Founder Signal skill:

1. **Extracts** commitments, deadlines, owners, decisions, and promised
   follow-ups — each anchored to verbatim source evidence.
2. **Reconciles** them against a persistent commitment ledger, detecting
   changes, duplicates, missing details, and approaching deadlines.
3. **Delivers** a tiny action briefing: Do now · Coming up · Waiting on
   someone · Needs clarification.

The key differentiator is reconciliation, not just extraction. If a deadline
moves from Friday to Monday in a follow-up email, Founder Signal detects the
change, proposes an update to the existing commitment, and retains both source
quotes as evidence. The agent proposes; you confirm. Nothing is applied
without your action.

## Demo

A scripted, offline demo walks through the full flow:

1. Ingest an accelerator email → two cited commitments added to the ledger.
2. Ingest a follow-up email → reconciliation detects the deadline changed
   (Friday → Monday) and proposes an update, keeping both source quotes.
3. Apply the change with `--apply` → the ledger is updated.
4. Morning briefing → reflects the updated commitment.

Run it locally with no API keys:

```bash
FOUNDER_NAME=Anthony bash demo/demo.sh
```

See `demo/DEMO.md` for the full walkthrough and sample data.

## Open-source AI used

Founder Signal is LLM-optional by design. The default extraction path is a
deterministic rule-based extractor that works offline with no model, no API
key, and no network. When you want LLM-powered extraction, you can plug in:

- **Ollama** — local, privacy-first LLM extraction using open-weight models
  (e.g. `gemma4:e2b-it-qat`). No data leaves your machine.
- **OpenAI** — API-based extraction when an `OPENAI_API_KEY` is present.

The stack is entirely open-source: Flask (web UI + Hermes skill endpoint),
SQLite (local ledger), and Python. The skill is also exposed as a
Hermes-compatible HTTP endpoint so Hermes can invoke Founder Signal as a
skill (see `SKILL.md`).

## Why open innovation matters

Founder Signal is local-first by default. Your commitments, source evidence,
and ledger stay on your machine — no SaaS, no OAuth, no multi-account
integrations, no data sent to a third-party API unless you explicitly opt in.
Open-source AI (Ollama, open-weight models) makes this possible: you can run
the full extraction pipeline offline, on your own hardware, with full control
over your data.

For founders, that's not just a privacy preference — it's a requirement.
Founder Signal shows that you don't need a cloud LLM or a proprietary platform
to build a useful agent. Open innovation lets founders own their commitment
ledger end to end.

## Effort saved

Without Founder Signal, tracking commitments across email threads is a manual
chore: rereading messages, copying action items into a todo list, noticing
when deadlines change, and reconciling old promises against new ones.

Estimated time spent per week on this chore: **30–60 minutes**. With Founder
Signal: **~2 minutes** to ingest the week's sources and read the morning
briefing.

**Estimated effort saved: ~25–55 minutes per week.** This is an estimate,
not a measured result — actual savings depend on email volume and how often
commitments change.

## Try it

```bash
git clone https://github.com/AnthonyASBaptiste/founder-signal.git
cd founder-signal
pip install -r requirements.txt
cp .env.example .env
FOUNDER_NAME=Anthony bash demo/demo.sh
```

Full setup instructions are in the README. The demo uses the rule-based
extractor, so it works offline with no API keys.

---

*Submission for Hacktoberfest Week 3 — "Slow and Steady". Built with
open-source AI at its core.*
