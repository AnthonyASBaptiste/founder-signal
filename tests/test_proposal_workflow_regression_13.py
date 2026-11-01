import os
import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.auth import _reset_cache_for_testing
from founder_signal.config import Config
from founder_signal.ledger import open_ledger
from founder_signal.models import Commitment, Source


def test_proposal_accept_and_reject_workflow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        config = Config(
            inbox_folder=tmpdir,
            ledger_sqlite_path=db_path,
            ledger_backend="sqlite",
            briefing_coming_up_days=14,
        )

        # Configure single-user auth for the test client
        os.environ["FS_ADMIN_USER"] = "test"
        os.environ["FS_ADMIN_PASSWORD"] = "test"
        _reset_cache_for_testing()

        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Sign in before accessing protected routes
        client.post("/login", data={"username": "test", "password": "test"})

        # 1. Add initial commitment directly to ledger
        ledger = open_ledger(config)
        source = Source(id="s1", kind="email", title="Initial email", body="Please send the deck to Sarah next Friday.")
        ledger.add_source(source)
        initial_c = Commitment(
            id="c1",
            source_id="s1",
            description="Send the deck to Sarah",
            owner="me",
            due_date="2026-10-30",
            status="open",
            evidence="Please send the deck to Sarah next Friday."
        )
        ledger.add_commitment(initial_c)

        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        assert commitments[0].due_date == "2026-10-30"
        assert commitments[0].pending_change is None
        ledger.close()

        # 2. Add a schedule change email as a new source/commitment with pending_change
        ledger = open_ledger(config)
        source2 = Source(id="s2", kind="email", title="Update email", body="Please send the deck to Sarah next Monday.")
        ledger.add_source(source2)
        updated_c = Commitment(
            id="c1",
            source_id="s2",
            description="Send the deck to Sarah",
            owner="me",
            due_date="2026-10-30",
            status="open",
            evidence="Please send the deck to Sarah next Monday.",
            pending_change={"due_date": "2026-11-02"}
        )
        ledger.add_commitment(updated_c)

        # Ledger should still have 1 commitment, but now with pending_change
        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        assert commitments[0].id == "c1"
        assert commitments[0].due_date == "2026-10-30"  # Original due date preserved until reviewed
        assert commitments[0].pending_change is not None
        assert commitments[0].pending_change["due_date"] == "2026-11-02"
        ledger.close()

        # 3. View commitment detail page via GET
        resp = client.get(f"/commitments/c1")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Proposed Change Awaiting Review" in html
        assert "2026-11-02" in html
        assert "Accept Proposal" in html
        assert "Reject Proposal" in html

        # 4. Also verify dashboard page displays "Proposed Change" badge and "Review Change" button
        index_resp = client.get("/dashboard")
        assert index_resp.status_code == 200
        index_html = index_resp.get_data(as_text=True)
        assert "Proposed Change" in index_html
        assert "Review Change" in index_html

        # 5. Test Reject Proposal first
        reject_resp = client.post(
            f"/commitments/c1",
            data={"action": "reject_proposal"},
            follow_redirects=True,
        )
        assert reject_resp.status_code == 200

        ledger = open_ledger(config)
        rejected_c = ledger.get_commitment("c1")
        assert rejected_c.pending_change is None
        assert rejected_c.due_date == "2026-10-30"  # Untouched
        ledger.close()

        # 6. Re-stage proposal and test Accept Proposal
        ledger = open_ledger(config)
        source3 = Source(id="s3", kind="email", title="Update email 2", body="Please send the deck to Sarah next Monday.")
        ledger.add_source(source3)
        staged_again_c = Commitment(
            id="c1",
            source_id="s3",
            description="Send the deck to Sarah",
            owner="me",
            due_date="2026-10-30",
            status="open",
            evidence="Please send the deck to Sarah next Monday.",
            pending_change={"due_date": "2026-11-02"}
        )
        ledger.add_commitment(staged_again_c)

        accept_resp = client.post(
            f"/commitments/c1",
            data={"action": "accept_proposal"},
            follow_redirects=True,
        )
        assert accept_resp.status_code == 200

        accepted_c = ledger.get_commitment("c1")
        assert accepted_c.pending_change is None
        assert accepted_c.due_date == "2026-11-02"  # Successfully applied!
        ledger.close()
