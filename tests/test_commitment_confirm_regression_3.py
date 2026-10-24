# Regression: ISSUE-003 — Confirm action in commitment detail does not persist to ledger
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=confirm action updates commitment in ledger; fails_when=confirm action ignores ledger; why_new=confirm action had no test coverage; seam=none; no_claim=none beyond protects

import os
import tempfile
from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source


def test_commitment_confirm_persists_to_ledger():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    ledger = SQLiteLedger(db_path)
    try:
        source = Source(id="s_test", kind="email", title="T", body="B")
        ledger.add_source(source)
        commitment = Commitment(
            id="c_test_confirm",
            source_id="s_test",
            description="Confirm test task",
            owner="me",
            due_date="2026-10-30",
            status="open"
        )
        ledger.add_commitment(commitment)
        original_updated_at = ledger.get_commitment("c_test_confirm").updated_at
        ledger.close()

        config = Config(ledger_backend="sqlite", ledger_sqlite_path=db_path)
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Submit confirm action
        resp = client.post("/commitments/c_test_confirm", data={"action": "confirm"})
        assert resp.status_code == 302

        # Verify updated_at changed in database
        verify_ledger = SQLiteLedger(db_path)
        updated_c = verify_ledger.get_commitment("c_test_confirm")
        verify_ledger.close()

        assert updated_c.updated_at >= original_updated_at
        # Check that update_commitment was actually called by checking updated_at timestamp delta
        assert updated_c.updated_at != original_updated_at, "Expected updated_at to be refreshed on confirm"
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
