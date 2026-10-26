import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.ledger import open_ledger


def test_proposal_accept_and_reject_workflow():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        config = Config(
            inbox_folder=tmpdir,
            ledger_sqlite_path=db_path,
            ledger_backend="sqlite",
            briefing_coming_up_days=14,
        )

        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # 1. Ingest initial commitment: "Please send the deck to Sarah next Friday."
        resp = client.post(
            "/ingest",
            data={
                "kind": "email",
                "title": "Initial email",
                "body": "Please send the deck to Sarah next Friday.",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        ledger = open_ledger(config)
        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        initial_c = commitments[0]
        assert initial_c.due_date == "2026-10-30"
        assert initial_c.pending_change is None
        ledger.close()

        # 2. Ingest schedule change email: "Please send the deck to Sarah next Monday."
        resp = client.post(
            "/ingest",
            data={
                "kind": "email",
                "title": "Update email",
                "body": "Please send the deck to Sarah next Monday.",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200

        # Ledger should still have 1 commitment, but now with pending_change
        ledger = open_ledger(config)
        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        updated_c = commitments[0]
        assert updated_c.id == initial_c.id
        assert updated_c.due_date == "2026-10-30"  # Original due date preserved until reviewed
        assert updated_c.pending_change is not None
        assert updated_c.pending_change["due_date"] == "2026-11-02"
        ledger.close()

        # 3. View commitment detail page via GET
        resp = client.get(f"/commitments/{initial_c.id}")
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        assert "Proposed Change Awaiting Review" in html
        assert "2026-11-02" in html
        assert "Accept Proposal" in html
        assert "Reject Proposal" in html

        # 4. Also verify index page displays "Proposed Change" badge and "Review Change" button
        index_resp = client.get("/")
        assert index_resp.status_code == 200
        index_html = index_resp.get_data(as_text=True)
        assert "Proposed Change" in index_html
        assert "Review Change" in index_html

        # 5. Test Reject Proposal first
        reject_resp = client.post(
            f"/commitments/{initial_c.id}",
            data={"action": "reject_proposal"},
            follow_redirects=True,
        )
        assert reject_resp.status_code == 200

        ledger = open_ledger(config)
        rejected_c = ledger.get_commitment(initial_c.id)
        assert rejected_c.pending_change is None
        assert rejected_c.due_date == "2026-10-30"  # Untouched
        ledger.close()

        # 6. Re-stage proposal and test Accept Proposal
        client.post(
            "/ingest",
            data={
                "kind": "email",
                "title": "Update email 2",
                "body": "Please send the deck to Sarah next Monday.",
            },
            follow_redirects=True,
        )

        ledger = open_ledger(config)
        staged_again_c = ledger.get_commitment(initial_c.id)
        assert staged_again_c.pending_change is not None
        ledger.close()

        accept_resp = client.post(
            f"/commitments/{initial_c.id}",
            data={"action": "accept_proposal"},
            follow_redirects=True,
        )
        assert accept_resp.status_code == 200

        ledger = open_ledger(config)
        accepted_c = ledger.get_commitment(initial_c.id)
        assert accepted_c.pending_change is None
        assert accepted_c.due_date == "2026-11-02"  # Successfully applied!
        ledger.close()
