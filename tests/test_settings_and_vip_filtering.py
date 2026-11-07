"""Tests for Settings, VIP filtering, and Optimistic UI API endpoint."""

import json
from pathlib import Path
from founder_signal.config import Config
from founder_signal.ledger import SQLiteLedger, open_ledger
from founder_signal.models import Commitment, Source
from founder_signal.inbox import InboxWatcher
from founder_signal.app import create_app


def test_ledger_settings_crud(tmp_path):
    db_file = tmp_path / "test.db"
    ledger = SQLiteLedger(path=str(db_file))
    try:
        settings = ledger.get_settings()
        assert "vip_emails" in settings
        assert "tishana@research-navigator.ai" in settings["vip_emails"]

        # Update settings
        settings["vip_emails"].append("founder@newpartner.com")
        settings["discord_alerts_target"] = "discord:custom-channel"
        ledger.update_settings(settings)

        updated = ledger.get_settings()
        assert "founder@newpartner.com" in updated["vip_emails"]
        assert updated["discord_alerts_target"] == "discord:custom-channel"
    finally:
        ledger.close()


def test_heartbeat_filters_non_vip(monkeypatch, tmp_path):
    inbox_dir = tmp_path / "inbox"
    db_file = tmp_path / "test.db"
    cfg = Config(
        ledger_backend="sqlite",
        ledger_sqlite_path=str(db_file),
        inbox_folder=str(inbox_dir),
    )

    monkeypatch.setattr("founder_signal.inbox.resolve_himalaya_bin", lambda *args, **kwargs: "/mock/himalaya")
    watcher = InboxWatcher(cfg)
    watcher.himalaya_bin = "/mock/himalaya"
    try:
        # 1 VIP email from Tishana, 1 non-VIP marketing email from Oracle
        envelope_data = [
            {
                "id": "vip_1",
                "subject": "Review draft contract",
                "from": [{"name": "Tishana", "email": "tishana@research-navigator.ai"}],
                "to": [{"name": "Anthony", "email": "anthony@example.com"}],
            },
            {
                "id": "promo_2",
                "subject": "Oracle Cloud Webinar invitation",
                "from": [{"name": "Oracle Events", "email": "events@oracle-marketing.com"}],
                "to": [{"name": "Anthony", "email": "anthony@example.com"}],
            },
        ]

        class Res:
            returncode = 0
            stdout = json.dumps(envelope_data)
            stderr = ""

        fetch_ids = []

        def _mock_fetch(self, account, msg_id):
            fetch_ids.append(msg_id)
            return "From: tishana@research-navigator.ai\nSubject: Review draft\n\nPlease review the contract by Friday."

        monkeypatch.setattr("founder_signal.inbox.subprocess.run", lambda *args, **kwargs: Res())
        monkeypatch.setattr("founder_signal.inbox.InboxWatcher._fetch_message_body", _mock_fetch)

        fetched = watcher.heartbeat_email(["primary"])
        # Only the VIP email should have been fetched and processed
        assert fetched == 1
        assert fetch_ids == ["vip_1"]
        assert "promo_2" not in fetch_ids
    finally:
        watcher.close()


def test_api_commitment_status_endpoint(tmp_path):
    db_file = tmp_path / "test.db"
    cfg = Config(
        ledger_backend="sqlite",
        ledger_sqlite_path=str(db_file),
    )
    ledger = open_ledger(cfg)
    c = Commitment(
        id="c-test-1",
        source_id="src-1",
        description="Test async status update",
        status="open",
    )
    ledger.add_source(Source(id="src-1", kind="email", title="Test", body="body"))
    ledger.add_commitment(c)
    ledger.close()

    app = create_app(cfg)
    client = app.test_client()

    # If auth environment variables are active in test runner, sign in first
    import os
    if os.environ.get("FS_ADMIN_USER") and os.environ.get("FS_ADMIN_PASSWORD"):
        client.post(
            "/login",
            data={
                "username": os.environ["FS_ADMIN_USER"],
                "password": os.environ["FS_ADMIN_PASSWORD"],
            },
        )

    # Call async JSON endpoint
    res = client.post(
        "/api/commitments/c-test-1/status",
        json={"status": "done"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["status"] == "done"

    # Verify status in database
    ledger2 = open_ledger(cfg)
    try:
        updated = ledger2.get_commitment("c-test-1")
        assert updated.status == "done"
    finally:
        ledger2.close()


def test_excluded_counter_increments_and_resets(tmp_path):
    """Item 1: Predictable filter exclusion count increments and resets."""
    db_file = tmp_path / "test.db"
    ledger = SQLiteLedger(path=str(db_file))
    try:
        assert ledger.get_settings().get("excluded_count", 0) == 0
        val = ledger.increment_excluded_count(3)
        assert val == 3
        assert ledger.get_settings()["excluded_count"] == 3

        ledger.reset_excluded_count()
        assert ledger.get_settings()["excluded_count"] == 0
    finally:
        ledger.close()


def test_learning_from_decisions_rule_generation_and_acceptance(tmp_path):
    """Item 6: Repeated dismissals generate rule suggestions, approved rules exclude senders."""
    db_file = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_file))
    ledger = open_ledger(cfg)
    try:
        # First dismissal: counts 1, no rule yet
        rule1 = ledger.record_dismissal("spammer@cold-sales.com")
        assert rule1 is None
        settings = ledger.get_settings()
        assert settings["dismissal_counts"]["spammer@cold-sales.com"] == 1
        assert len(settings.get("suggested_rules", [])) == 0

        # Second dismissal: threshold reached, rule suggested
        rule2 = ledger.record_dismissal("spammer@cold-sales.com")
        assert rule2 is not None
        assert rule2["type"] == "exclude_sender"
        assert rule2["pattern"] == "spammer@cold-sales.com"
        assert rule2["status"] == "pending"

        # Accept rule
        ok = ledger.accept_suggested_rule(rule2["id"])
        assert ok is True
        updated_settings = ledger.get_settings()
        assert "spammer@cold-sales.com" in updated_settings["excluded_senders"]

        rule_status = next(r for r in updated_settings["suggested_rules"] if r["id"] == rule2["id"])
        assert rule_status["status"] == "accepted"
    finally:
        ledger.close()


def test_api_accept_and_reject_proposal(tmp_path):
    """Item 3: Accept and reject proposed evolution in place."""
    db_file = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_file))
    ledger = open_ledger(cfg)
    c = Commitment(
        id="c-evolve-1",
        source_id="src-1",
        description="Demo day presentation",
        owner="Anthony",
        due_date="2026-11-06",
        status="open",
        pending_change={
            "due_date": "2026-11-09",
            "owner": "Tishana",
            "evidence": "Tishana will deliver on Monday",
            "description": "Deadline moved Friday -> Monday",
        },
    )
    ledger.add_source(Source(id="src-1", kind="email", title="Thread", body="body"))
    ledger.add_commitment(c)
    ledger.close()

    app = create_app(cfg)
    client = app.test_client()

    import os
    if os.environ.get("FS_ADMIN_USER") and os.environ.get("FS_ADMIN_PASSWORD"):
        client.post(
            "/login",
            data={
                "username": os.environ["FS_ADMIN_USER"],
                "password": os.environ["FS_ADMIN_PASSWORD"],
            },
        )

    # Accept proposal
    res = client.post("/api/commitments/c-evolve-1/accept_proposal")
    assert res.status_code == 200
    data = res.get_json()
    assert data["success"] is True
    assert data["due_date"] == "2026-11-09"
    assert data["owner"] == "Tishana"

    ledger2 = open_ledger(cfg)
    updated = ledger2.get_commitment("c-evolve-1")
    assert updated.pending_change is None
    assert updated.due_date == "2026-11-09"
    assert updated.owner == "Tishana"
    ledger2.close()


def test_digest_threshold_only_behavior():
    """Item 5: Digest suppresses alerts when threshold is not crossed."""
    from founder_signal.notifications import notify_morning_briefing
    from founder_signal.briefing import Briefing

    empty_briefing = Briefing(
        do_now=[],
        coming_up=[],
        waiting_on=[],
        needs_clarification=[],
        summary="All clear",
    )

    # Threshold only with 0 items: does not send spam, returns True
    sent = notify_morning_briefing(
        empty_briefing,
        threshold_only=True,
        pending_proposals_count=0,
    )
    assert sent is True
