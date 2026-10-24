"""Tests for the Founder Signal extraction skill."""

from datetime import datetime, timezone

from founder_signal.extraction import extract, to_commitments, SKILL_SYSTEM_PROMPT
from founder_signal.models import Source


def _make_source(body: str) -> Source:
    return Source(
        id="test:src:1",
        kind="email",
        title="Test email",
        body=body,
        received_at=datetime.now(timezone.utc),
    )


def test_extracts_commitment_with_owner_and_due():
    source = _make_source("I will send the deck to Sarah by Friday, October 30.")
    result = extract(source)
    assert len(result.commitments) >= 1
    c = result.commitments[0]
    assert "deck" in c.description.lower()
    assert c.evidence


def test_extracts_decision_and_followup():
    source = _make_source("We decided to go with option B. Let's follow up next week.")
    result = extract(source)
    assert len(result.decisions) >= 1 or len(result.follow_ups) >= 1


def test_to_commitments_creates_open_records():
    source = _make_source("I will call the investor tomorrow.")
    result = extract(source)
    commitments = to_commitments(result, source.id)
    assert all(c.status == "open" for c in commitments)
    assert all(c.source_id == source.id for c in commitments)


def test_skill_system_prompt_present():
    assert "Founder Signal" in SKILL_SYSTEM_PROMPT
    assert "verbatim" in SKILL_SYSTEM_PROMPT.lower()
