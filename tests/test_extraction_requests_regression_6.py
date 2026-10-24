# Regression: ISSUE-006 — Rule-based extractor drops requests and misattributes self-commits when text lacks email headers or speaker labels
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=extracts direct requests as user_requested when no headers exist, and sets owner=founder on self-commits without speaker labels; fails_when=requests dropped or self-commits have null owner; why_new=existing tests only tested self-commit description substring; seam=none; no_claim=none beyond protects

from founder_signal.extraction import extract
from founder_signal.models import Source
from founder_signal.config import Config


def test_extract_handles_requests_without_headers():
    cfg = Config(founder_name="Anthony Baptiste")
    source = Source(
        id="s_req",
        kind="email",
        title="Direct Request",
        body="Please send the financial model by tomorrow."
    )
    result = extract(source, use_llm=False, config=cfg)
    assert len(result.commitments) == 1
    c = result.commitments[0]
    assert "financial model" in c.description.lower()
    assert c.direction == "user_requested"
    assert c.owner == "Anthony Baptiste"


def test_extract_self_commit_without_speaker_label_attributes_to_founder():
    cfg = Config(founder_name="Anthony Baptiste")
    source = Source(
        id="s_self",
        kind="email",
        title="Self Commit",
        body="I will send the deck to Sarah by Friday, October 30."
    )
    result = extract(source, use_llm=False, config=cfg)
    assert len(result.commitments) == 1
    c = result.commitments[0]
    assert c.direction == "user_committing"
    assert c.owner == "Anthony Baptiste"
