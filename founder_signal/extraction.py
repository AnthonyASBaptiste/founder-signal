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
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .config import Config
from .models import Commitment, Source


@dataclass
class ExtractedCommitment:
    """A commitment proposed by the Founder Signal skill (not yet confirmed)."""

    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None  # ISO date string (explicitly stated)
    suggested_due_date: Optional[str] = None  # inferred absolute date when none stated
    direction: Optional[str] = None  # "user_committing" | "user_requested" | "third_party"
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
    extractor: str = "rules"  # "ollama/gemma4:e2b-it-qat" | "openai/..." | "rules"
    fallback_from: Optional[str] = None  # name of provider that failed prior to fallback


# System prompt given to the LLM (or used as the skill's explicit instructions
# when running rule-based). Hermes would render this as the skill's system
# message.
SKILL_SYSTEM_PROMPT = """You are the Founder Signal skill, a specialist agent for founders who receive more information, requests and opportunities than they have time to process.

Your job: read source material (email text, voice-note transcripts, meeting transcripts) and extract ONLY commitments that are directed at or made by the founder (the recipient of this message).

First, identify who the founder/recipient is from the email headers (To:, Cc:) or the body context. Then extract ONLY:

- Commitments the founder is making ("I will do X", "I'll send Y")
- Commitments others are making TO the founder ("Please review this", "I will send you the contract")
- Commitments where the founder is clearly the intended owner or beneficiary

Do NOT extract:
- General statements, newsletters, marketing content, or FYI information
- Commitments between third parties that don't involve the founder
- Auto-generated text, signatures, disclaimers, or boilerplate
- Statements that are just information sharing, not action items

For each commitment, determine the direction:
- "user_committing" — the founder promised to do something
- "user_requested" — someone asked the founder to do something
- "third_party" — someone else committed to do something for the founder

Output structured JSON only, with this exact schema:
{
  "commitments": [
    {"description": "short description", "owner": "person name or null", "due_date": "YYYY-MM-DD or null", "direction": "user_committing | user_requested | third_party", "evidence": "verbatim quote from source", "confidence": 0.0-1.0}
  ],
  "decisions": ["string"],
  "follow_ups": ["string"],
  "summary": "one-sentence summary"
}

Rules:
- commitments must be objects with description, owner, due_date, direction, evidence, confidence fields (not bare strings).
- Convert relative dates to absolute YYYY-MM-DD when possible (e.g. "next Friday" → actual date, "end of week" → Friday of this week, "tomorrow" → tomorrow's date). Use null only when no date can be determined.
- Never invent an owner; use null when not stated.
- evidence must be a verbatim quote from the source text.
- Do not send messages, accept commitments, or mark anything complete. You only propose.
- Be conservative: extract only what is explicitly stated and directed at the founder."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_due_date(due_date: Optional[str], description: str) -> Optional[str]:
    """Convert relative or natural language dates to absolute YYYY-MM-DD.

    Returns the absolute date if one can be determined, otherwise None.
    """
    candidate_text = f"{due_date or ''} {description or ''}".lower().strip()
    if not candidate_text:
        return None

    # Check if already ISO format YYYY-MM-DD
    m_iso = re.search(r"\b(\d{4}-\d{2}-\d{2})\b", candidate_text)
    if m_iso:
        return m_iso.group(1)

    today = datetime.now(timezone.utc).date()

    # Month name + day pattern (e.g. "October 30" or "30 October")
    month_map = {
        "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
        "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6,
        "july": 7, "jul": 7, "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9,
        "october": 10, "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
    }
    month_re = "|".join(month_map.keys())

    # "October 30" or "Oct 30"
    m_md = re.search(rf"\b({month_re})\s+(\d{{1,2}})(?:st|nd|rd|th)?\b", candidate_text)
    if m_md:
        m_name = m_md.group(1)
        day = int(m_md.group(2))
        month = month_map[m_name]
        try:
            cand = date(today.year, month, day)
            if cand < today - timedelta(days=90):
                cand = date(today.year + 1, month, day)
            return cand.isoformat()
        except ValueError:
            pass

    # "30 October" or "30th Oct"
    m_dm = re.search(rf"\b(\d{{1,2}})(?:st|nd|rd|th)?\s+({month_re})\b", candidate_text)
    if m_dm:
        day = int(m_dm.group(1))
        m_name = m_dm.group(2)
        month = month_map[m_name]
        try:
            cand = date(today.year, month, day)
            if cand < today - timedelta(days=90):
                cand = date(today.year + 1, month, day)
            return cand.isoformat()
        except ValueError:
            pass

    # Relative weekday patterns
    weekday_map = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }

    # "next Friday" / "next monday"
    m = re.search(r"\bnext\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", candidate_text)
    if m:
        target_wd = weekday_map[m.group(1)]
        days_ahead = (target_wd - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (today + timedelta(days=days_ahead)).isoformat()

    # "this Friday" / "this monday"
    m = re.search(r"\bthis\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", candidate_text)
    if m:
        target_wd = weekday_map[m.group(1)]
        days_ahead = (target_wd - today.weekday()) % 7
        return (today + timedelta(days=days_ahead)).isoformat()

    # "tomorrow"
    if "tomorrow" in candidate_text:
        return (today + timedelta(days=1)).isoformat()

    # "end of week" / "by friday" / "eod friday"
    if any(k in candidate_text for k in ["end of week", "by friday", "eod friday", "end of the week"]):
        days_ahead = (4 - today.weekday()) % 7
        if days_ahead == 0:
            days_ahead = 7
        return (today + timedelta(days=days_ahead)).isoformat()

    # "end of day" / "eod" / "today"
    if any(k in candidate_text for k in ["end of day", "eod", "by today", "today"]):
        return today.isoformat()

    # "next week"
    if "next week" in candidate_text:
        return (today + timedelta(days=7)).isoformat()

    return None


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
                suggested_due_date=c.get("suggested_due_date"),
                direction=c.get("direction"),
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


def _rule_based_extract(source: Source, config: Optional[Config] = None,
                        founder_name: Optional[str] = None,
                        founder_email: Optional[str] = None) -> ExtractionResult:
    """Deterministic fallback extractor (no LLM required).

    Filters out quoted email lines and headers, identifies the founder from
    To:/Cc: headers or speaker labels, and only extracts commitments directed
    at or made by the founder.
    """
    cfg = config or Config.from_env()
    founder_name = founder_name or cfg.founder_name
    founder_email = founder_email or cfg.founder_email

    body = source.body
    commitments: list[ExtractedCommitment] = []
    decisions: list[str] = []
    follow_ups: list[str] = []

    # --- Pre-process: strip email headers and quoted lines ---
    lines = body.splitlines()
    cleaned: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        # Skip quoted email lines (start with >)
        if stripped.startswith(">"):
            continue
        # Skip email header lines (From:, To:, Cc:, Subject:, Date:, etc.)
        # These can appear at the top or in forwarded message chains.
        if re.match(r"^(From|To|Cc|Bcc|Subject|Date|Message-ID|Content-Type|Content-Transfer-Encoding|X-|Received|Reply-To):\s", stripped, re.IGNORECASE):
            continue
        # Skip signature blocks and separators
        if stripped.startswith("-- ") or stripped.startswith("*"):
            continue
        cleaned.append(stripped)

    # --- Identify the founder from headers ---
    has_headers = any(
        re.match(r"^(From|To|Cc|Bcc|Subject|Date):\s", line.strip(), re.IGNORECASE)
        for line in body.splitlines()
    )
    founder_in_to = not has_headers  # Default to primary recipient if no headers
    founder_in_cc = False
    for line in body.splitlines():
        low = line.lower()
        if low.startswith("to:") or low.startswith("cc:"):
            if founder_name.lower() in low:
                if low.startswith("to:"):
                    founder_in_to = True
                else:
                    founder_in_cc = True
            if founder_email and founder_email.lower() in low:
                if low.startswith("to:"):
                    founder_in_to = True
                else:
                    founder_in_cc = True

    founder_is_primary = founder_in_to  # founder is the main recipient
    founder_is_recipient = founder_in_to or founder_in_cc  # founder is To or Cc

    # --- Date patterns ---
    date_patterns = [
        r"\b(\d{4}-\d{2}-\d{2})\b",
        r"\b(january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{1,2}\b",
        r"\b(next\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
        r"\b(tomorrow|next week|by end of day|eod|by friday)\b",
    ]

    # --- Decision and follow-up cues ---
    decision_cues = [
        r"\bwe decided\b", r"\bdecision\b", r"\bwe agreed\b", r"\bagreed to\b",
        r"\bgoing with\b", r"\bwe've decided\b", r"\bwe have decided\b",
    ]
    followup_cues = [
        r"\bfollow up\b", r"\bfollow-up\b", r"\bcheck in\b", r"\bcheck-in\b",
        r"\bcircle back\b", r"\btouch base\b",
    ]
    # Patterns where the speaker is committing themselves (user_committing if speaker is founder)
    self_commit_cues = [
        r"\bi will\s+(.+)",
        r"\bi'll\s+(.+)",
        r"\bi promise\s+to\s+(.+)",
        r"\bi commit\s+to\s+(.+)",
        r"\bwe will\s+(.+)",
        r"\bwe'll\s+(.+)",
    ]
    # Patterns where someone is asking the speaker to do something (user_requested if addressed to founder)
    request_cues = [
        r"\bplease\s+(.+)",
        r"\bcan you\s+(.+)",
        r"\bcould you\s+(.+)",
        r"\bwould you\s+(.+)",
    ]

    # Track current speaker for transcripts (lines like "Name: text")
    current_speaker = None
    speaker_pattern = re.compile(r"^([A-Za-z][A-Za-z\s'’\-]+?):\s(.+)$")

    for line in cleaned:
        low = line.lower()

        # Detect speaker label in transcripts
        m = speaker_pattern.match(line)
        if m:
            current_speaker = m.group(1).strip()
            line = m.group(2)
            low = line.lower()

        is_self_commit = any(re.search(c, low) for c in self_commit_cues)
        is_request = any(re.search(c, low) for c in request_cues)
        is_decision = any(re.search(c, low) for c in decision_cues)
        is_followup = any(re.search(c, low) for c in followup_cues)

        if not is_self_commit and not is_request and not is_decision and not is_followup:
            continue

        if is_decision:
            decisions.append(line)
        if is_followup:
            follow_ups.append(line)

        if not is_self_commit and not is_request:
            continue

        # Determine direction
        # Use word-boundary matching so "Anthony" doesn't false-match "Anthony's"
        # or "Anthonette" in speaker labels.
        is_founder_speaking = bool(
            (not current_speaker and founder_is_primary)
            or (
                current_speaker
                and founder_name
                and re.search(rf"\b{re.escape(founder_name.lower())}\b", current_speaker.lower())
            )
        )

        if is_self_commit:
            if is_founder_speaking:
                direction = "user_committing"
                owner = founder_name
            else:
                # Someone else committing - only relevant if for the founder
                direction = "third_party"
                owner = current_speaker
        elif is_request:
            # Only treat as user_requested if founder is the primary recipient (To:).
            # If founder is only Cc'd, requests are likely for someone else.
            if founder_is_primary:
                direction = "user_requested"
                owner = founder_name
            else:
                # Request directed at someone else, skip
                continue

        # Extract due date from the line
        due_date = None
        for pat in date_patterns:
            m = re.search(pat, low)
            if m:
                due_date = m.group(0)
                # Normalize explicit dates to YYYY-MM-DD
                date_m = re.search(r"(\d{4}-\d{2}-\d{2})", due_date)
                if date_m:
                    due_date = date_m.group(1)
                break

        # Apply due date inference when no explicit date
        suggested_due_date = None
        if not due_date:
            suggested_due_date = _infer_due_date(None, line)

        # Extract description (the commitment part after the cue)
        description = line
        for cue_list in (self_commit_cues, request_cues):
            for cue in cue_list:
                m = re.search(cue, low)
                if m:
                    description = m.group(1).strip()
                    break

        commitments.append(ExtractedCommitment(
            description=description,
            owner=owner,
            due_date=due_date,
            suggested_due_date=suggested_due_date,
            direction=direction,
            evidence=line,
            confidence=0.6,
        ))

    summary = f"Extracted {len(commitments)} commitment(s), {len(decisions)} decision(s), {len(follow_ups)} follow-up(s) from {source.kind} '{source.title}'."
    return ExtractionResult(
        source=source,
        commitments=commitments,
        decisions=decisions,
        follow_ups=follow_ups,
        summary=summary,
        raw="rule-based fallback",
    )


def _ollama_extract(source: Source, host: str, model: str, config: Optional[Config] = None,
                    founder_name: Optional[str] = None, founder_email: Optional[str] = None) -> ExtractionResult | None:
    """Run extraction via a local Ollama chat endpoint.

    Returns an ExtractionResult on success, or None on failure so the caller
    can fall back to rule-based extraction.
    """
    import urllib.request

    cfg = config or Config.from_env()
    founder_name = founder_name or cfg.founder_name
    founder_email = founder_email or cfg.founder_email

    system_prompt = SKILL_SYSTEM_PROMPT + f"\n\nThe founder/recipient is: {founder_name}" + (f" ({founder_email})" if founder_email else "") + "."

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
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
        parsed.extractor = f"ollama/{model}"
        return parsed
    return None


def extract(source: Source, use_llm: bool = False, config: Optional[Config] = None,
            account: Optional[str] = None) -> ExtractionResult:
    """Run the Founder Signal extraction skill on a source.

    Args:
        source: The source material (email or transcript).
        use_llm: If True and an LLM provider is available, use the LLM;
            otherwise use the deterministic rule-based extractor.
        config: Optional Config for Ollama host/model settings.
        account: Optional himalaya account name for per-account founder identity.

    Returns:
        ExtractionResult with proposed commitments, decisions, follow-ups.
    """
    cfg = config or Config.from_env()

    # Resolve founder identity for this account (per-account override or global).
    founder_name, founder_email = cfg.founder_for_account(account)

    attempted_provider: Optional[str] = None

    # LLM is the primary path when requested (privacy-first via Ollama).
    if use_llm:
        attempted_provider = "ollama"
        # Try local Ollama first (no API key needed, runs locally).
        try:
            ollama_result = _ollama_extract(source, cfg.ollama_host, cfg.ollama_model, cfg, founder_name, founder_email)
            if ollama_result is not None:
                ollama_result.extractor = f"ollama/{cfg.ollama_model}"
                return ollama_result
        except Exception:
            pass

        # Try OpenAI only if cloud fallback is explicitly permitted AND an API key is present.
        if getattr(cfg, "allow_cloud_fallback", False) and os.environ.get("OPENAI_API_KEY"):
            attempted_provider = "openai"
            try:
                from openai import OpenAI
                client = OpenAI()
                system_prompt = SKILL_SYSTEM_PROMPT + f"\n\nThe founder/recipient is: {founder_name}" + (f" ({founder_email})" if founder_email else "") + "."
                model_name = os.environ.get("FOUNDER_SIGNAL_MODEL", "gpt-4o-mini")
                completion = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
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
                    parsed.extractor = f"openai/{model_name}"
                    return parsed
            except Exception:
                pass

    # Deterministic rule-based fallback (works offline, no API key).
    result = _rule_based_extract(source, cfg, founder_name, founder_email)
    result.source = source
    result.extractor = "rules"
    if use_llm and attempted_provider:
        result.fallback_from = attempted_provider
    return result


def to_commitments(result: ExtractionResult, source_id: str) -> list[Commitment]:
    """Convert an ExtractionResult into proposed Commitment records (status=open).

    Applies due date inference when no explicit due date is found, and carries
    the direction field through so the UI can filter non-directed commitments.
    """
    commitments: list[Commitment] = []
    for i, c in enumerate(result.commitments):
        due_date = _infer_due_date(c.due_date, c.description)
        suggested_due_date = c.suggested_due_date
        if not due_date and not suggested_due_date:
            suggested_due_date = _infer_due_date(None, c.description)
        commitments.append(Commitment(
            id=f"{source_id}::c{i}",
            source_id=source_id,
            description=c.description,
            owner=c.owner,
            due_date=due_date,
            suggested_due_date=suggested_due_date,
            direction=c.direction,
            decision=c.decision,
            follow_up=c.follow_up,
            status="open",
            evidence=c.evidence,
        ))
    return commitments
