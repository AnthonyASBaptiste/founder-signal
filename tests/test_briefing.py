"""Tests for the morning briefing."""

import os, tempfile

from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source
from founder_signal.briefing import generate_briefing


def _tmp_ledger():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return SQLiteLedger(path), path


def test_briefing_sections():
    ledger, path = _tmp_ledger()
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        # Overdue/due today -> do now
        ledger.add_commitment(Commitment(id="c1", source_id="s1", description="Due today", owner="me", due_date="2026-10-23", status="open"))
        # Coming up within 7 days
        ledger.add_commitment(Commitment(id="c2", source_id="s1", description="Coming up", owner="me", due_date="2026-10-28", status="open"))
        # Waiting on someone (delegated)
        ledger.add_commitment(Commitment(id="c3", source_id="s1", description="Delegated", owner="co-founder", due_date="2026-10-29", status="open"))
        # Missing detail
        ledger.add_commitment(Commitment(id="c4", source_id="s1", description="Vague", owner=None, due_date=None, status="open"))

        briefing = generate_briefing(ledger, coming_up_days=7)
        assert len(briefing.do_now) >= 1
        assert len(briefing.coming_up) >= 1
        assert len(briefing.waiting_on) >= 1
        assert len(briefing.needs_clarification) >= 1
    finally:
        ledger.close()
        os.unlink(path)
