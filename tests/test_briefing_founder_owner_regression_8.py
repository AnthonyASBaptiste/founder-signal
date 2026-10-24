# Regression: ISSUE-007 — Briefing includes founder-owned commitments in waiting_on list
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=briefing waiting_on excludes commitments owned by founder; fails_when=commitments with founder name appear in waiting_on; why_new=existing briefing test only used owner="me"; seam=none; no_claim=none beyond protects

import tempfile, os
from founder_signal.models import Commitment, Source
from founder_signal.ledger import SQLiteLedger
from founder_signal.config import Config
from founder_signal.briefing import generate_briefing


def test_briefing_excludes_founder_name_from_waiting_on():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    ledger = SQLiteLedger(db_path)
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)

        # 1. Commitment owned by founder: "Anthony Baptiste"
        c_founder = Commitment(
            id="c_founder",
            source_id="s1",
            description="Send investor update",
            owner="Anthony Baptiste",
            due_date="2026-10-28",
            status="open"
        )
        ledger.add_commitment(c_founder)

        # 2. Commitment owned by another person: "Sarah Miller"
        c_other = Commitment(
            id="c_other",
            source_id="s1",
            description="Send audited financials",
            owner="Sarah Miller",
            due_date="2026-10-29",
            status="open"
        )
        ledger.add_commitment(c_other)

        cfg = Config(founder_name="Anthony Baptiste")
        briefing = generate_briefing(ledger, coming_up_days=7, config=cfg)

        # c_other should be in waiting_on
        waiting_ids = [c.id for c in briefing.waiting_on]
        assert "c_other" in waiting_ids, "Expected c_other in waiting_on"

        # c_founder MUST NOT be in waiting_on
        assert "c_founder" not in waiting_ids, f"c_founder with owner={c_founder.owner} should not be in waiting_on"
    finally:
        ledger.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
