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
