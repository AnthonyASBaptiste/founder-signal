"""Tests for commitment reconciliation."""

import os

from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source
from founder_signal.reconciliation import reconcile


def _tmp_ledger():
    import os, tempfile
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SQLiteLedger(path), path


def test_duplicate_detection():
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        existing = Commitment(id="c1", source_id="s1", description="Send deck to Sarah", owner="me", due_date="2026-11-01")
        ledger.add_commitment(existing)
        # New commitment that's a near-duplicate.
        new = Commitment(id="c2", source_id="s2", description="send deck to Sarah", owner="me", due_date="2026-11-01")
        result = reconcile(ledger, [new])
        assert len(result.new_commitments) == 0
        assert any(i.kind == "duplicate" for i in result.issues)
    finally:
        ledger.close()
        os.unlink(path)


def test_missing_detail():
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        new = Commitment(id="c1", source_id="s1", description="Do something", owner=None, due_date=None)
        result = reconcile(ledger, [new])
        assert any(i.kind == "missing_detail" for i in result.issues)
    finally:
        ledger.close()
        os.unlink(path)


def test_new_commitment_added():
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        new = Commitment(id="c1", source_id="s1", description="Call investor", owner="me", due_date="2026-12-01")
        result = reconcile(ledger, [new])
        assert len(result.new_commitments) == 1
        assert len(result.issues) == 0
    finally:
        ledger.close()
        os.unlink(path)


def test_change_detection_due_date():
    """A similar existing commitment with a different due date flags a change,
    retaining both source quotes as evidence."""
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        existing = Commitment(
            id="c1", source_id="s1",
            description="send the deck to Sarah next Friday",
            owner="unknown", due_date="2026-10-30",
            evidence="Please send the deck to Sarah next Friday.",
        )
        ledger.add_commitment(existing)
        # Follow-up moves the deadline to Monday.
        new = Commitment(
            id="c2", source_id="s2",
            description="send the deck to Sarah next Monday",
            owner="unknown", due_date="2026-11-02",
            evidence="Please send the deck to Sarah next Monday.",
        )
        result = reconcile(ledger, [new])
        assert len(result.new_commitments) == 0
        change_issues = [i for i in result.issues if i.kind == "change"]
        assert len(change_issues) == 1
        issue = change_issues[0]
        assert "2026-10-30" in issue.description and "2026-11-02" in issue.description
        assert issue.proposed is not None
        assert issue.proposed.due_date == "2026-11-02"
        # Both source quotes retained in proposed evidence.
        assert "Please send the deck to Sarah next Friday." in issue.proposed.evidence
        assert "Please send the deck to Sarah next Monday." in issue.proposed.evidence
        assert "-- Updated from source" in issue.proposed.evidence
    finally:
        ledger.close()
        os.unlink(path)


def test_change_detection_owner():
    """A similar existing commitment with a different owner flags a change."""
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        existing = Commitment(
            id="c1", source_id="s1",
            description="send the deck to Sarah next Friday",
            owner="Alice", due_date="2026-10-30",
            evidence="Please send the deck to Sarah next Friday.",
        )
        ledger.add_commitment(existing)
        new = Commitment(
            id="c2", source_id="s2",
            description="send the deck to Sarah next Monday",
            owner="Bob", due_date="2026-10-30",
            evidence="Please send the deck to Sarah next Monday.",
        )
        result = reconcile(ledger, [new])
        change_issues = [i for i in result.issues if i.kind == "change"]
        assert len(change_issues) == 1
        issue = change_issues[0]
        assert "owner: Alice → Bob" in issue.description
        assert issue.proposed is not None
        assert issue.proposed.owner == "Bob"
    finally:
        ledger.close()
        os.unlink(path)
