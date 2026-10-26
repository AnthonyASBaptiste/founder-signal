# Regression: ISSUE-001 — Hermes HTTP skill does not stage pending_change on existing commitments
# Found by /qa on 2026-10-26
# Report: .gstack/qa-reports/run-20261026T063027Z/qa-report-founder-signal-2026-10-26.md
# Value: protects=hermes invoke stages pending_change; fails_when=reconciliation issue.kind=='change' is ignored; why_new=no existing test covers hermes schedule update staging; seam=none; no_claim=none beyond protects

import tempfile
from pathlib import Path

from founder_signal.config import Config
from founder_signal.hermes_skill import create_skill_app
from founder_signal.ledger import open_ledger


def test_hermes_skill_stages_pending_change_on_reconciliation():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        cfg = Config(inbox_folder=tmpdir, ledger_sqlite_path=db_path)
        app = create_skill_app(cfg)
        client = app.test_client()

        # Step 1: Initial commitment via Hermes agent skill
        resp1 = client.post(
            "/skills/founder-signal/invoke",
            json={
                "input": "Please send the deck to Sarah next Friday.",
                "source_title": "Initial accelerator email",
            },
        )
        assert resp1.status_code == 200

        ledger = open_ledger(cfg)
        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        initial_c = commitments[0]
        assert initial_c.pending_change is None
        c_id = initial_c.id
        ledger.close()

        # Step 2: Schedule change via Hermes agent skill (Friday -> Monday)
        resp2 = client.post(
            "/skills/founder-signal/invoke",
            json={
                "input": "Quick change of plan - please send the deck to Sarah next Monday.",
                "source_title": "Schedule change email",
            },
        )
        assert resp2.status_code == 200
        data2 = resp2.get_json()
        assert data2["ok"] is True

        # Verify that existing commitment in ledger has staged pending_change
        ledger = open_ledger(cfg)
        updated_c = ledger.get_commitment(c_id)
        assert updated_c is not None
        assert updated_c.pending_change is not None, (
            "Hermes skill should stage pending_change on existing commitment when reconciliation detects a change"
        )
        assert "2026-11-02" in str(updated_c.pending_change.get("due_date"))
        assert "Monday" in str(updated_c.pending_change.get("evidence"))
        ledger.close()
