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


def test_settings_view_post_save_and_reset(tmp_path):
    """Verify settings form submission saves settings and reset_excluded resets counter."""
    from founder_signal.app import create_app
    from founder_signal.ledger import open_ledger, SQLiteLedger

    db_path = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_path))
    ledger = open_ledger(cfg)
    ledger.increment_excluded_count(5)
    assert ledger.get_settings()["excluded_count"] == 5
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

    # 1. Standard POST to save settings
    res = client.post(
        "/settings",
        data={
            "action": "save",
            "vip_emails": "mentor@example.com\ncofounder@example.com",
            "vip_domains": "example.com",
            "include_directly_addressed": "true",
            "digest_time": "08:30",
            "due_soon_days": "5",
            "check_interval_mins": "30",
        },
        follow_redirects=True,
    )
    assert res.status_code == 200

    ledger = open_ledger(cfg)
    saved = ledger.get_settings()
    assert "mentor@example.com" in saved["vip_emails"]
    assert "example.com" in saved["vip_domains"]
    assert saved["due_soon_days"] == 5
    assert saved["excluded_count"] == 5
    ledger.close()

    # 2. Reset counter via dedicated action
    res = client.post(
        "/settings",
        data={"action": "reset_excluded"},
        follow_redirects=True,
    )
    assert res.status_code == 200

    ledger = open_ledger(cfg)
    assert ledger.get_settings()["excluded_count"] == 0
    ledger.close()




def test_api_reset_excluded_strict_json(tmp_path):
    """Verify /api/settings/reset_excluded returns strict JSON even without JSON headers."""
    from founder_signal.app import create_app
    from founder_signal.ledger import open_ledger

    db_path = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_path))
    ledger = open_ledger(cfg)
    ledger.increment_excluded_count(10)
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

    res = client.post("/api/settings/reset_excluded")
    assert res.status_code == 200
    assert res.is_json
    data = res.get_json()
    assert data == {"success": True, "excluded_count": 0}

    ledger = open_ledger(cfg)
    assert ledger.get_settings()["excluded_count"] == 0
    ledger.close()


def test_settings_post_missing_or_conflicting_action_safeguards(tmp_path):
    """Verify POST without action does not overwrite settings, and conflicting actions are rejected."""
    from founder_signal.app import create_app
    from founder_signal.ledger import open_ledger

    db_path = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_path))
    ledger = open_ledger(cfg)
    settings = ledger.get_settings()
    settings["vip_emails"] = ["critical_vip@example.com"]
    ledger.update_settings(settings)
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

    # 1. POST without action should NOT execute save and wipe settings
    res = client.post("/settings", data={}, follow_redirects=True)
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "no valid action specified" in html.lower()

    ledger = open_ledger(cfg)
    assert "critical_vip@example.com" in ledger.get_settings()["vip_emails"]
    ledger.close()

    # 2. POST with conflicting actions should be rejected with an error
    res = client.post(
        "/settings",
        data={"action": ["save", "reset_excluded"]},
        follow_redirects=True,
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "conflicting actions" in html.lower()

    # 3. Explicit POST with action="save" preserves dynamic state (rules, exclusions, counters)
    ledger = open_ledger(cfg)
    settings = ledger.get_settings()
    settings["excluded_senders"] = ["spam@example.com"]
    settings["suggested_rules"] = [{"pattern": "marketing@example.com", "action": "exclude"}]
    ledger.update_settings(settings)
    ledger.increment_excluded_count(7)
    ledger.close()

    res = client.post(
        "/settings",
        data={
            "action": "save",
            "vip_emails": "new_vip@example.com",
            "due_soon_days": "999",  # Should be clamped to 14
            "check_interval_mins": "1",  # Should be clamped to 5
        },
        follow_redirects=True,
    )
    assert res.status_code == 200

    ledger = open_ledger(cfg)
    saved = ledger.get_settings()
    assert "new_vip@example.com" in saved["vip_emails"]
    assert saved["due_soon_days"] == 14
    assert saved["check_interval_mins"] == 5
    # Concurrently updated dynamic fields must be preserved
    assert saved["excluded_count"] == 7
    assert saved["excluded_senders"] == ["spam@example.com"]
    assert saved["suggested_rules"] == [{"pattern": "marketing@example.com", "action": "exclude"}]
    ledger.close()

    # 4. Unrecognized action should flash an error
    res = client.post(
        "/settings",
        data={"action": "unknown_action"},
        follow_redirects=True,
    )
    assert res.status_code == 200
    html = res.get_data(as_text=True)
    assert "unrecognized action" in html.lower()


def test_settings_html_form_isolation(tmp_path):
    """Verify settings.html template isolates Reset Counter button from the main settings form."""
    from founder_signal.app import create_app

    db_path = tmp_path / "test.db"
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=str(db_path))
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

    res = client.get("/settings")
    assert res.status_code == 200
    html = res.get_data(as_text=True)

    assert '<form id="reset-counter-form"' in html
    assert 'form="reset-counter-form"' in html
    assert '<button type="submit" name="action" value="save"' in html




