# Regression: ISSUE-008 — Heartbeat re-fetches processed emails because check only inspects inbox_path
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=heartbeat ignores already processed emails and does not re-fetch them; fails_when=heartbeat re-fetches emails present in processed_path or with .done marker; why_new=no heartbeat deduplication test existed; seam=none; no_claim=none beyond protects

import json
from founder_signal.config import Config
from founder_signal.inbox import InboxWatcher


def test_heartbeat_skips_already_processed_emails(monkeypatch, tmp_path):
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
        # Mock himalaya envelope search output
        envelope_data = [{"id": "msg_123", "subject": "Test update"}]
        class Res:
            returncode = 0
            stdout = json.dumps(envelope_data)
            stderr = ""

        fetch_count = [0]
        def _mock_fetch_body(self, account, msg_id):
            fetch_count[0] += 1
            return "From: sender@example.com\nTo: anthony@example.com\nSubject: Test\n\nI will send the review by tomorrow."

        monkeypatch.setattr("founder_signal.inbox.subprocess.run", lambda *args, **kwargs: Res())
        monkeypatch.setattr("founder_signal.inbox.InboxWatcher._fetch_message_body", _mock_fetch_body)

        # First heartbeat: fetches 1 email
        fetched1 = watcher.heartbeat_email(["primary"])
        assert fetched1 == 1
        assert fetch_count[0] == 1

        # File is now in processed_path and .done marker is in inbox_path
        processed_file = watcher.processed_path / "email-primary-msg_123.txt"
        done_marker = watcher.inbox_path / "email-primary-msg_123.txt.done"
        assert processed_file.exists() or done_marker.exists()

        # Second heartbeat: should recognize email as already processed and NOT fetch body again
        fetched2 = watcher.heartbeat_email(["primary"])
        assert fetched2 == 0, f"Expected 0 fetched on second heartbeat, got {fetched2}"
        assert fetch_count[0] == 1, f"Expected fetch_count to remain 1, got {fetch_count[0]}"
    finally:
        watcher.close()
