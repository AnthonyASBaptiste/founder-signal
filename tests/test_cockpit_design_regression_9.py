# Regression: ISSUE-009 — Warm editorial founder's cockpit UI system contracts
# Value: protects=cockpit attention hero, distinct briefing signature lanes, warm palette variables, and quiet list actions render properly across routes

import os
import tempfile
from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source


def test_cockpit_editorial_design_routes():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    try:
        ledger = SQLiteLedger(db_path)
        source = Source(id="s1", kind="email", title="Urgent Email", body="Need urgent fix.")
        ledger.add_source(source)
        # Commitment overdue/due now
        c_urgent = Commitment(
            id="c1",
            source_id="s1",
            description="Fix production deploy",
            owner="me",
            due_date="2026-10-24",
            status="open",
            evidence="Please fix the production deploy today"
        )
        # Commitment needing clarification
        c_unassigned = Commitment(
            id="c2",
            source_id="s1",
            description="Reach out to lead investor",
            owner=None,
            due_date=None,
            status="open",
            evidence="Someone needs to reach out"
        )
        ledger.add_commitment(c_urgent)
        ledger.add_commitment(c_unassigned)
        ledger.close()

        config = Config(ledger_backend="sqlite", ledger_sqlite_path=db_path)
        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # 1. Dashboard (Cockpit)
        r_index = client.get("/")
        assert r_index.status_code == 200
        html_idx = r_index.text
        # Warm palette & typography
        assert "--color-bg: #fbf9f5;" in html_idx
        assert "Newsreader" in html_idx
        assert "--color-brand: #164e4b;" in html_idx
        assert "--color-urgent: #c2410c;" in html_idx
        # Cockpit Attention Hero leads with what needs attention
        assert "cockpit-hero" in html_idx
        assert "has-urgent" in html_idx
        assert "Attention Required" in html_idx
        assert "cockpit-metrics" in html_idx
        # Quieted row controls
        assert "btn-action-done" in html_idx
        assert "btn-action-ghost" in html_idx
        assert "due-pill-urgent" in html_idx

        # 2. Morning Briefing Signature
        r_briefing = client.get("/briefing")
        assert r_briefing.status_code == 200
        html_briefing = r_briefing.text
        assert "lane-card-do-now" in html_briefing
        assert "lane-card-coming-up" in html_briefing
        assert "lane-card-waiting" in html_briefing
        assert "lane-card-clarification" in html_briefing

        # 3. Detail View
        r_detail = client.get("/commitments/c1")
        assert r_detail.status_code == 200
        html_detail = r_detail.text
        assert "source-preview-card" in html_detail
        assert "action" in html_detail

        # 4. Ingest View
        r_ingest = client.get("/ingest")
        assert r_ingest.status_code == 200
        html_ingest = r_ingest.text
        assert "field-file-transcript" in html_ingest
        assert "field-file-audio" in html_ingest
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)
