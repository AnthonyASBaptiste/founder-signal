"""Hermes skill endpoint for the Founder Signal skill.

Exposes the Founder Signal extraction + reconciliation workflow as an HTTP
skill that a Hermes agent can invoke:

  GET  /skills/founder-signal/manifest   skill manifest (name, description, schema)
  POST /skills/founder-signal/invoke     run extraction + reconciliation on source text
  GET  /health                           health check

Run standalone:

    python -m founder_signal.cli hermes-skill

The agent proposes; the user confirms. This endpoint only proposes
commitments — it never sends messages or marks anything complete.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from flask import Flask, jsonify, request

from .config import Config
from .ledger import open_ledger
from .models import Source
from .extraction import SKILL_SYSTEM_PROMPT, extract, to_commitments
from .reconciliation import reconcile
from .briefing import generate_briefing

SKILL_NAME = "founder-signal"
SKILL_PATH = "skills/founder-signal"

SKILL_DESCRIPTION = (
    "Founder Signal skill: extracts commitments, deadlines, owners, "
    "decisions, and follow-ups from founder inbound material (email, "
    "voice-note transcripts, meeting transcripts), reconciles them against "
    "a persistent commitment ledger, and emits a tiny action briefing "
    "(Do now · Coming up · Waiting on someone · Needs clarification). "
    "Every commitment is anchored to verbatim source evidence. "
    "The agent proposes; the user confirms."
)

MANIFEST_INPUT_SCHEMA = {
    "type": "object",
    "required": ["input"],
    "properties": {
        "input": {
            "type": "string",
            "description": "Source text to analyze (email body or voice-note/meeting transcript).",
        },
        "source_kind": {
            "type": "string",
            "enum": ["email", "transcript", "voice-note"],
            "default": "email",
            "description": "Type of source material.",
        },
        "source_title": {
            "type": "string",
            "description": "Human-readable title for the source material.",
        },
        "account": {
            "type": "string",
            "description": "Optional himalaya account for per-account founder identity.",
        },
        "use_llm": {
            "type": "boolean",
            "default": False,
            "description": "Use LLM extraction (Ollama/OpenAI) when available; otherwise rule-based.",
        },
    },
}

MANIFEST_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "ok": {"type": "boolean"},
        "source": {"type": "object"},
        "commitments": {
            "type": "array",
            "items": {"type": "object"},
            "description": "Proposed commitments (status=open, awaiting confirmation).",
        },
        "decisions": {"type": "array", "items": {"type": "string"}},
        "follow_ups": {"type": "array", "items": {"type": "string"}},
        "summary": {"type": "string"},
        "reconciliation": {
            "type": "object",
            "description": "Change/duplicate/missing-detail/deadline detection vs the ledger.",
        },
        "briefing": {
            "type": "object",
            "description": "Morning briefing: Do now · Coming up · Waiting on someone · Needs clarification.",
        },
    },
}


def _manifest(endpoint: str) -> dict:
    return {
        "name": SKILL_NAME,
        "description": SKILL_DESCRIPTION,
        "endpoint": endpoint,
        "instructions": SKILL_SYSTEM_PROMPT,
        "input": MANIFEST_INPUT_SCHEMA,
        "output": MANIFEST_OUTPUT_SCHEMA,
    }


def create_skill_app(config: Optional[Config] = None) -> Flask:
    config = config or Config.from_env()
    app = Flask(__name__)

    @app.get(f"/{SKILL_PATH}/manifest")
    def manifest():
        host = request.host_url.rstrip("/")
        return jsonify(
            _manifest(f"{host}/{SKILL_PATH}/invoke")
        )

    @app.post(f"/{SKILL_PATH}/invoke")
    def invoke():
        data = request.get_json(silent=True) or {}
        text = data.get("input")
        if not text or not str(text).strip():
            return jsonify({"ok": False, "error": "input is required"}), 400

        kind = data.get("source_kind") or "email"
        title = data.get("source_title") or "hermes input"
        account = data.get("account")
        use_llm = bool(data.get("use_llm", False))

        source = Source(
            id=f"hermes:{kind}:{title}:{int(datetime.now(timezone.utc).timestamp())}",
            kind=kind,
            title=title,
            body=str(text),
        )

        ledger = open_ledger(config)
        try:
            ledger.add_source(source)
            result = extract(
                source, use_llm=use_llm, config=config, account=account
            )
            proposed = to_commitments(result, source.id)
            reconciliation = reconcile(
                ledger, proposed, within_days=config.briefing_coming_up_days
            )
            for c in reconciliation.new_commitments:
                ledger.add_commitment(c)
            for issue in reconciliation.issues:
                if issue.kind == "change" and issue.proposed is not None:
                    existing_c = ledger.get_commitment(issue.commitment_id)
                    if existing_c:
                        existing_c.pending_change = {
                            "due_date": issue.proposed.due_date,
                            "owner": issue.proposed.owner,
                            "evidence": issue.proposed.evidence,
                            "description": issue.description,
                        }
                        ledger.update_commitment(existing_c)
            briefing = generate_briefing(
                ledger, coming_up_days=config.briefing_coming_up_days
            )
        finally:
            ledger.close()

        return jsonify(
            {
                "ok": True,
                "source": source.to_dict(),
                "commitments": [c.to_dict() for c in proposed],
                "decisions": result.decisions,
                "follow_ups": result.follow_ups,
                "summary": result.summary,
                "reconciliation": {
                    "new_commitments": [
                        c.to_dict() for c in reconciliation.new_commitments
                    ],
                    "issues": [
                        {
                            "kind": issue.kind,
                            "commitment_id": issue.commitment_id,
                            "description": issue.description,
                            "proposed": (
                                issue.proposed.to_dict()
                                if issue.proposed is not None
                                else None
                            ),
                            "evidence": issue.evidence,
                            "requires_confirmation": issue.requires_confirmation,
                        }
                        for issue in reconciliation.issues
                    ],
                    "summary": reconciliation.summary,
                },
                "briefing": {
                    "do_now": [c.to_dict() for c in briefing.do_now],
                    "coming_up": [c.to_dict() for c in briefing.coming_up],
                    "waiting_on": [c.to_dict() for c in briefing.waiting_on],
                    "needs_clarification": [
                        c.to_dict() for c in briefing.needs_clarification
                    ],
                    "summary": briefing.summary,
                    "generated_at": briefing.generated_at.isoformat(),
                },
            }
        )

    @app.get("/health")
    def health():
        return jsonify({"ok": True, "skill": SKILL_NAME})

    return app


def run_skill_server(config: Config, host: str, port: int) -> None:
    """Serve the Founder Signal Hermes skill endpoint."""
    app = create_skill_app(config)
    print(
        f"[founder-signal] Hermes skill endpoint serving at "
        f"http://{host}:{port}/{SKILL_PATH}/invoke"
    )
    app.run(host=host, port=port)
