"""Tests for dashboard status management, assignee dropdowns, fast update API,
and CC/BCC email extraction with third-party deliverables.
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone

from founder_signal.app import create_app
from founder_signal.auth import _reset_cache_for_testing
from founder_signal.briefing import generate_briefing
from founder_signal.config import Config
from founder_signal.extraction import extract
from founder_signal.ledger import SQLiteLedger
from founder_signal.models import Commitment, Source
from founder_signal.reconciliation import reconcile


def _setup_app_and_client():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.environ["FS_ADMIN_USER"] = "testadmin"
    os.environ["FS_ADMIN_PASSWORD"] = "testsecret"
    _reset_cache_for_testing()

    cfg = Config(
        ledger_backend="sqlite",
        ledger_sqlite_path=db_path,
        founder_name="Anthony Baptiste",
        founder_emails=(
            "anthony.baptiste@outlook.com",
            "anthony@research-navigator.ai",
            "anthony.as.baptiste@gmail.com",
        ),
    )
    app = create_app(cfg)
    app.config["TESTING"] = True
    client = app.test_client()

    # Login
    client.post("/login", data={"username": "testadmin", "password": "testsecret"})
    return app, client, db_path, cfg


def test_in_progress_status_api_and_dashboard():
    app, client, db_path, cfg = _setup_app_and_client()
    try:
        ledger = SQLiteLedger(db_path)
        source = Source(id="src_1", kind="email", title="Update", body="Work needed")
        ledger.add_source(source)
        c = Commitment(
            id="c_prog_1",
            source_id="src_1",
            description="Build new prototype",
            owner="Anthony Baptiste",
            due_date=(datetime.now(timezone.utc).date() + timedelta(days=2)).isoformat(),
            status="open",
        )
        ledger.add_commitment(c)
        ledger.close()

        # Update status to in_progress via JSON API
        res = client.post(
            "/api/commitments/c_prog_1/status",
            json={"status": "in_progress"},
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["status"] == "in_progress"

        # Verify in ledger
        ledger = SQLiteLedger(db_path)
        updated = ledger.get_commitment("c_prog_1")
        assert updated.status == "in_progress"

        # Verify dashboard renders in_progress commitment
        dash = client.get("/dashboard")
        assert dash.status_code == 200
        html = dash.get_data(as_text=True)
        assert "c_prog_1" in html
        assert "status-select-in_progress" in html
        assert "Build new prototype" in html

        # Verify briefing includes in_progress commitments
        briefing = generate_briefing(ledger, coming_up_days=7, config=cfg)
        assert any(c.id == "c_prog_1" for c in briefing.coming_up)

        # Verify reconciliation tracks in_progress commitments
        new_c = Commitment(
            id="c_new_1",
            source_id="src_1",
            description="Build new prototype",
            owner="Anthony Baptiste",
            due_date=(datetime.now(timezone.utc).date() + timedelta(days=5)).isoformat(),
            status="open",
        )
        rec = reconcile(ledger, [new_c])
        # Should detect date change from existing in_progress item
        assert len(rec.issues) >= 1 or len(rec.commitments) == 0

        ledger.close()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_quick_assign_api_and_edit_dropdown():
    app, client, db_path, cfg = _setup_app_and_client()
    try:
        ledger = SQLiteLedger(db_path)
        source = Source(id="src_2", kind="email", title="Task Email", body="Details")
        ledger.add_source(source)
        c = Commitment(
            id="c_assign_1",
            source_id="src_2",
            description="Prepare pitch deck",
            owner=None,
            due_date="2026-11-20",
            status="open",
        )
        ledger.add_commitment(c)
        ledger.close()

        # 1. Quick assign via /api/commitments/<id>/owner
        res = client.post(
            "/api/commitments/c_assign_1/owner",
            json={"owner": "Tishana Simon"},
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["owner"] == "Tishana Simon"

        ledger = SQLiteLedger(db_path)
        assert ledger.get_commitment("c_assign_1").owner == "Tishana Simon"
        ledger.close()

        # 2. Assign to Anthony Baptiste
        res = client.post(
            "/api/commitments/c_assign_1/owner",
            json={"owner": "Anthony Baptiste"},
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.get_json()["owner"] == "Anthony Baptiste"

        # 3. Unassign
        res = client.post(
            "/api/commitments/c_assign_1/owner",
            json={"owner": ""},
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        assert res.get_json()["owner"] is None

        # 4. Edit page POST with custom owner
        res_edit = client.post(
            "/commitments/c_assign_1",
            data={
                "action": "update",
                "description": "Prepare pitch deck updated",
                "owner_select": "__custom__",
                "owner_custom": "Keneisha Browne",
                "due_date": "2026-11-25",
                "status": "in_progress",
                "evidence": "Quoted evidence",
            },
            follow_redirects=True,
        )
        assert res_edit.status_code == 200

        ledger = SQLiteLedger(db_path)
        updated = ledger.get_commitment("c_assign_1")
        assert updated.owner == "Keneisha Browne"
        assert updated.status == "in_progress"
        assert updated.description == "Prepare pitch deck updated"
        ledger.close()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_fast_async_update_api():
    app, client, db_path, cfg = _setup_app_and_client()
    try:
        ledger = SQLiteLedger(db_path)
        source = Source(id="src_3", kind="email", title="Sprint Sync", body="Content")
        ledger.add_source(source)
        c = Commitment(
            id="c_fast_1",
            source_id="src_3",
            description="Initial description",
            owner="Anthony Baptiste",
            due_date="2026-11-15",
            status="open",
        )
        ledger.add_commitment(c)
        ledger.close()

        res = client.post(
            "/api/commitments/c_fast_1/update",
            json={
                "description": "Snappy updated description",
                "owner_select": "Tishana Simon",
                "due_date": "2026-11-18",
                "status": "in_progress",
                "evidence": "Verbatim quote from email",
            },
            headers={"Content-Type": "application/json"},
        )
        assert res.status_code == 200
        data = res.get_json()
        assert data["success"] is True
        assert data["commitment"]["description"] == "Snappy updated description"
        assert data["commitment"]["owner"] == "Tishana Simon"
        assert data["commitment"]["status"] == "in_progress"
        assert data["commitment"]["due_date"] == "2026-11-18"

        ledger = SQLiteLedger(db_path)
        c_db = ledger.get_commitment("c_fast_1")
        assert c_db.description == "Snappy updated description"
        assert c_db.owner == "Tishana Simon"
        assert c_db.status == "in_progress"
        ledger.close()
    finally:
        if os.path.exists(db_path):
            os.unlink(db_path)


def test_cc_and_bcc_extraction_does_not_attribute_to_founder():
    cfg = Config(
        founder_name="Anthony Baptiste",
        founder_emails=(
            "anthony.baptiste@outlook.com",
            "anthony@research-navigator.ai",
            "anthony.as.baptiste@gmail.com",
        ),
    )

    # Email where Tishana writes to Keneisha, Anthony is CC'd
    email_body_cc = """From: Tishana Simon <tishana@research-navigator.ai>
To: Keneisha Browne <keneisha_browne@hotmail.com>
Cc: Anthony Baptiste <anthony.baptiste@outlook.com>
Subject: Market Analysis & Financial Review

Hi Keneisha,
I will complete the market research summary by Friday, October 30.
Please review the financial model by Monday, November 02.
"""
    source_cc = Source(
        id="email_cc_1",
        kind="email",
        title="Market Analysis",
        body=email_body_cc,
        received_at=datetime.now(timezone.utc),
    )

    result = extract(source_cc, use_llm=False, config=cfg)
    assert len(result.commitments) == 2

    # 1. Tishana's commitment
    c1 = next(c for c in result.commitments if "market research" in c.description.lower())
    assert c1.owner == "Tishana Simon"
    assert c1.direction == "third_party"
    assert c1.owner != "Anthony Baptiste"

    # 2. Request to Keneisha (Anthony is only CC'd)
    c2 = next(c for c in result.commitments if "financial model" in c.description.lower())
    assert c2.owner == "Keneisha Browne"
    assert c2.direction == "third_party"
    assert c2.owner != "Anthony Baptiste"


def test_bcc_extraction_tracks_deliverables_of_others():
    cfg = Config(
        founder_name="Anthony Baptiste",
        founder_emails=(
            "anthony.baptiste@outlook.com",
            "anthony@research-navigator.ai",
            "anthony.as.baptiste@gmail.com",
        ),
    )

    # Email where Anthony is BCC'd with research-navigator.ai email
    email_body_bcc = """From: John Mentor <john@accelerator.com>
To: Sarah Miller <sarah@startup.com>
Bcc: Anthony <anthony@research-navigator.ai>
Subject: Term Sheet Draft

Sarah,
I will send the revised term sheet by November 15.
Please verify the option pool calculations by November 18.
"""
    source_bcc = Source(
        id="email_bcc_1",
        kind="email",
        title="Term Sheet Draft",
        body=email_body_bcc,
        received_at=datetime.now(timezone.utc),
    )

    result = extract(source_bcc, use_llm=False, config=cfg)
    assert len(result.commitments) >= 1

    # Neither commitment should be attributed to Anthony
    for c in result.commitments:
        assert c.owner != "Anthony Baptiste"
        assert c.direction == "third_party"


def test_explicit_name_mention_when_cc_attributes_to_founder():
    cfg = Config(
        founder_name="Anthony Baptiste",
        founder_emails=(
            "anthony.baptiste@outlook.com",
            "anthony@research-navigator.ai",
            "anthony.as.baptiste@gmail.com",
        ),
    )

    # Email where Anthony is CC'd, but specifically addressed in one line
    email_body = """From: Tishana Simon <tishana@research-navigator.ai>
To: Keneisha Browne <keneisha_browne@hotmail.com>
Cc: Anthony Baptiste <anthony.as.baptiste@gmail.com>
Subject: Signatures needed

Keneisha,
I will upload the incorporation documents by Wednesday.

Anthony, please sign the director consent by Thursday.
"""
    source = Source(
        id="email_explicit_1",
        kind="email",
        title="Signatures needed",
        body=email_body,
        received_at=datetime.now(timezone.utc),
    )

    result = extract(source, use_llm=False, config=cfg)
    assert len(result.commitments) == 2

    # Tishana's commitment
    c_tishana = next(c for c in result.commitments if "incorporation" in c.description.lower())
    assert c_tishana.owner == "Tishana Simon"
    assert c_tishana.direction == "third_party"

    # Explicit request to Anthony
    c_anthony = next(c for c in result.commitments if "director consent" in c.description.lower())
    assert c_anthony.owner == "Anthony Baptiste"
    assert c_anthony.direction == "user_requested"


def test_third_party_commitments_land_in_briefing_waiting_on():
    fd, db_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    cfg = Config(
        ledger_backend="sqlite",
        ledger_sqlite_path=db_path,
        founder_name="Anthony Baptiste",
        founder_emails=(
            "anthony.baptiste@outlook.com",
            "anthony@research-navigator.ai",
            "anthony.as.baptiste@gmail.com",
        ),
    )
    ledger = SQLiteLedger(db_path)
    try:
        source = Source(id="s_cc", kind="email", title="Project", body="Content")
        ledger.add_source(source)

        # Deliverable from Tishana Simon to follow up on
        c1 = Commitment(
            id="c_tishana_1",
            source_id="s_cc",
            description="Market analysis delivery",
            owner="Tishana Simon",
            due_date="2026-11-20",
            status="open",
        )
        ledger.add_commitment(c1)

        # Deliverable from Keneisha Browne to follow up on
        c2 = Commitment(
            id="c_keneisha_1",
            source_id="s_cc",
            description="Financial model review",
            owner="Keneisha Browne",
            due_date="2026-11-21",
            status="in_progress",
        )
        ledger.add_commitment(c2)

        # Founder task
        c3 = Commitment(
            id="c_me_1",
            source_id="s_cc",
            description="Sign board consent",
            owner="Anthony Baptiste",
            due_date="2026-11-22",
            status="open",
        )
        ledger.add_commitment(c3)

        briefing = generate_briefing(ledger, coming_up_days=14, config=cfg)

        waiting_ids = [c.id for c in briefing.waiting_on]
        # Both third-party deliverables should be in waiting_on so Anthony can follow up!
        assert "c_tishana_1" in waiting_ids
        assert "c_keneisha_1" in waiting_ids

        # Founder's task must NOT be in waiting_on
        assert "c_me_1" not in waiting_ids
    finally:
        ledger.close()
        if os.path.exists(db_path):
            os.unlink(db_path)
