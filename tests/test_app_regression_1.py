# Regression: ISSUE-001 — N+1 query loop on index() fetching unused sources
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=dashboard loads without N+1 source queries; fails_when=sources loop is present or calls get_source; why_new=no web route tests existed; seam=none; no_claim=none beyond protects

import os
import tempfile
from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source


class SpyLedger(SQLiteLedger):
    def __init__(self, path):
        super().__init__(path)
        self.get_source_calls = 0

    def get_source(self, source_id: str):
        self.get_source_calls += 1
        return super().get_source(source_id)


def test_index_does_not_perform_n_plus_one_source_queries(monkeypatch):
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    ledger = SpyLedger(db_path)
    try:
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        ledger.add_commitment(Commitment(id="c1", source_id="s1", description="Task 1", owner="me", due_date="2026-10-24", status="open"))
        ledger.add_commitment(Commitment(id="c2", source_id="s1", description="Task 2", owner="me", due_date="2026-10-25", status="open"))
        ledger.close()

        active_spy = [None]
        def _mock_open_ledger(cfg):
            spy = SpyLedger(db_path)
            active_spy[0] = spy
            return spy

        monkeypatch.setattr("founder_signal.app.open_ledger", _mock_open_ledger)

        config = Config(ledger_backend="sqlite", ledger_sqlite_path=db_path)
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        response = client.get("/")
        assert response.status_code == 200
        # If the N+1 loop exists in index(), get_source_calls will be > 0.
        # It must be 0 because sources are not rendered on the index page.
        assert active_spy[0] is not None
        assert active_spy[0].get_source_calls == 0, f"Expected 0 get_source calls, got {active_spy[0].get_source_calls}"
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
