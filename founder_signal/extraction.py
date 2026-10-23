"""Founder Signal skill: structured extraction of commitments from source material.

Given email text or a voice-note transcript, the skill extracts commitments,
deadlines, owners, decisions and promised follow-ups, each anchored to verbatim
source evidence. The agent proposes; it never acts without confirmation.

The skill is LLM-optional: when an OpenAI-compatible API key is available it uses
the model; otherwise a deterministic rule-based extractor runs so the demo works
offline.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from .models import Commitment, Source


@dataclass
class ExtractedCommitment:
    """A commitment proposed by the Founder Signal skill (not yet confirmed)."""

    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None  # ISO date string
    decision: Optional[str] = None
    follow_up: Optional[str] = None
    evidence: str = ""  # verbatim quote from source
    confidence: float = 0.5


@dataclass
class ExtractionResult:
    """Structured output of the Founder Signal skill."""

    source: Optional[Source] = None
    commitments: list[ExtractedCommitment] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    follow_ups: list[str] = field(default_factory=list)
    summary: str = ""
    raw: str = ""  # raw model output for audit


# System prompt given to the LLM (or used as the skill's explicit instructions
# when running rule-based). Hermes would render this as the skill's system
# message.
SKILL_SYSTEM_PROMPT = """You are the Founder Signal skill, a specialist agent for founders who receive more information, requests and opportunities than they have time to process.

Your job: read source material (email text, voice-note transcripts, meeting transcripts) and extract ONLY the following, each anchored to verbatim source evidence:
- Commitments: promises to do something, with an owner and due date if stated.
- Decisions: conclusions reached.
- Follow-ups: promised next actions or check-ins.
- Deadlines: dates mentioned in connection with a commitment.

Output structured JSON only, with this exact schema:
{
  "commitments": [
    {"description": "short description", "owner": "person name or null", "due_date": "YYYY-MM-DD or null", "evidence": "verbatim quote from source", "confidence": 0.0-1.0}
  ],
  "decisions": ["string"],
  "follow_ups": ["string"],
  "summary": "one-sentence summary"
}

Rules:
- commitments must be objects with description, owner, due_date, evidence, confidence fields (not bare strings).
- Never invent a due date; use null when not stated.
- Never invent an owner; use null when not stated.
- evidence must be a verbatim quote from the source text.
- Do not send messages, accept commitments, or mark anything complete. You only propose.
- Be conservative: extract only what is explicitly stated."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _make_source(source_id: str, kind: str, title: str, body: str,
                 received_at: Optional[datetime] = None) -> Source:
    return Source(
        id=source_id,
        kind=kind,
        title=title,
        body=body,
        received_at=received_at,
    )


def _parse_llm_json(raw: str) -> ExtractionResult | None:
    """Best-effort parse of LLM JSON output.

    Handles both object-style commitments (with description/owner/due_date/etc.)
    and string-style commitments (bare strings), normalizing the latter.
    """
    try:
        start = raw.index("{")
        end = raw.rindex("}") + 1
        data = json.loads(raw[start:end])
    except (ValueError, json.JSONDecodeError):
        return None
    commitments = []
    for c in data.get("commitments", []):
        if isinstance(c, str):
            commitments.append(ExtractedCommitment(
                description=c,
                evidence=c,
                confidence=0.7,
            ))
        elif isinstance(c, dict):
            commitments.append(ExtractedCommitment(
                description=c.get("description", ""),
                owner=c.get("owner"),
                due_date=c.get("due_date"),
                decision=c.get("decision"),
                follow_up=c.get("follow_up"),
                evidence=c.get("evidence", c.get("description", "")),
                confidence=float(c.get("confidence", 0.5)),
            ))
    return ExtractionResult(
        commitments=commitments,
        decisions=data.get("decisions", []),
        follow_ups=data.get("follow_ups", []),
        summary=data.get("summary", ""),
        raw=raw,
    )


def _rule_based_extract(source: Source) -> ExtractionResult:
    """Deterministic fallback extractor (no LLM required)."""
    body = source.body
    commitments: list[ExtractedCommitment] = []
    decisions: list[str] = []
    follow_ups: list[str] = []

    # Date patterns
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b",
        r"\b(next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
        r"\b(tomorrow|next week|by end of day|eod|by friday)\b",
    ]

    # Commitment cues
    commitment_cues = [
        r"\bi will\s+(.+)",
        r"\bi'll\s+(.+)",
        r"\bwe will\s+(.+)",
        r"\bwe'll\s+(.+)",
        r"\bi promise\s+to\s+(.+)",
        r"\bi commit\s+to\s+(.+)",
        r"\bplease\s+(.+)",
        r"\bcan you\s+(.+)",
        r"\bcould you\s+(.+)",
    ]

    for line in body.splitlines():
        line = line.strip()
        if not line:
            continue
        low = line.lower()
        is_commitment = any(re.search(c, low) for c in commitment_cues)
        is_decision = any(k in low for k in ["decided", "decision", "we agreed", "agreed to", "going with"])
        is_followup = any(k in low for k in ["follow up", "follow-up", "check in", "check-in", "circle back", "touch base"])

        due_date = None
        for pat in date_patterns:
            m = re.search(pat, low)
            if m:
                due_date = m.group(0)
                break

        if is_commitment:
            commitments.append(ExtractedCommitment(
                description=line,
                evidence=line,
                due_date=due_date,
                confidence=0.6,
            ))
        if is_decision:
            decisions.append(line)
        if is_followup:
            follow_ups.append(line)

    summary = f"Extracted {len(commitments)} commitment(s), {len(decisions)} decision(s), {len(follow_ups)} follow-up(s) from {source.kind} '{source.title}'."
    return ExtractionResult(
        source=source,
        commitments=commitments,
        decisions=decisions,
        follow_ups=follow_ups,
        summary=summary,
        raw="rule-based fallback",
    )


def _ollama_extract(source: Source, host: str, model: str) -> ExtractionResult | None:
    """Run extraction via a local Ollama chat endpoint.

    Returns an ExtractionResult on success, or None on failure so the caller
    can fall back to rule-based extraction.
    """
    import urllib.request

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SKILL_SYSTEM_PROMPT},
            {"role": "user", "content": f"Source kind: {source.kind}\nTitle: {source.title}\nBody:\n{source.body}"},
        ],
        "stream": False,
        "format": "json",
        "options": {"temperature": 0.2},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{host.rstrip('/')}/api/chat",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = resp.read().decode("utf-8")
    except Exception:
        return None

    try:
        obj = json.loads(body)
        raw = obj.get("message", {}).get("content", "")
    except (json.JSONDecodeError, KeyError):
        return None

    if not raw:
        return None

    parsed = _parse_llm_json(raw)
    if parsed is not None:
        parsed.source = source
        parsed.raw = raw
        return parsed
    return None


def extract(source: Source, use_llm: bool = False, config: Optional[Config] = None) -> ExtractionResult:
    """Run the Founder Signal extraction skill on a source.

    Args:
        source: The source material (email or transcript).
        use_llm: If True and an LLM provider is available, use the LLM;
            otherwise use the deterministic rule-based extractor.
        config: Optional Config for Ollama host/model settings.

    Returns:
        ExtractionResult with proposed commitments, decisions, follow-ups.
    """
    result = _rule_based_extract(source)
    result.source = source

    if not use_llm:
        return result

    # Try OpenAI first if an API key is present.
    if os.environ.get("OPENAI_API_KEY"):
        try:
            from openai import OpenAI
            client = OpenAI()
            completion = client.chat.completions.create(
                model=os.environ.get("FOUNDER_SIGNAL_MODEL", "gpt-4o-mini"),
                messages=[
                    {"role": "system", "content": SKILL_SYSTEM_PROMPT},
                    {"role": "user", "content": f"Source kind: {source.kind}\nTitle: {source.title}\nBody:\n{source.body}"},
                ],
                temperature=0.2,
                response_format={"type": "json_object"},
            )
            raw = completion.choices[0].message.content or ""
            parsed = _parse_llm_json(raw)
            if parsed is not None:
                parsed.source = source
                parsed.raw = raw
                return parsed
        except Exception:
            # Fall through to Ollama or rule-based.
            pass

    # Try local Ollama (privacy-first, no API key needed).
    cfg = config or Config.from_env()
    try:
        ollama_result = _ollama_extract(source, cfg.ollama_host, cfg.ollama_model)
        if ollama_result is not None:
            return ollama_result
    except Exception:
        pass

    return result


def to_commitments(result: ExtractionResult, source_id: str) -> list[Commitment]:
    """Convert an ExtractionResult into proposed Commitment records (status=open)."""
    commitments: list[Commitment] = []
    for i, c in enumerate(result.commitments):
        commitments.append(Commitment(
            id=f"{source_id}::c{i}",
            source_id=source_id,
            description=c.description,
            owner=c.owner,
            due_date=c.due_date,
            decision=c.decision,
            follow_up=c.follow_up,
            status="open",
            evidence=c.evidence,
        ))
    return commitments
