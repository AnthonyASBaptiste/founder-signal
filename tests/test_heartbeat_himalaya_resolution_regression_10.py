# Regression: ISSUE-010 — Heartbeat fails when HIMALAYA_BIN is not an absolute path and lookback window is too narrow
# Found by /qa on 2026-10-25
# Value: protects=heartbeat resolves himalaya via PATH and supports configurable lookback days; fails_when=himalaya not found despite being in PATH or lookback days not applied; why_new=prevent heartbeat failures on standard CLI installs
import json
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from founder_signal.config import Config
from founder_signal.inbox import InboxWatcher, resolve_himalaya_bin


def test_resolve_himalaya_bin_via_path(monkeypatch):
    monkeypatch.setattr("shutil.which", lambda name: "/usr/custom/bin/himalaya" if name == "himalaya" else None)
    resolved = resolve_himalaya_bin("himalaya")
    assert resolved == "/usr/custom/bin/himalaya"


def test_heartbeat_configurable_lookback_days(monkeypatch, tmp_path):
    inbox_dir = tmp_path / "inbox"
    db_file = tmp_path / "test.db"
    cfg = Config(
        ledger_backend="sqlite",
        ledger_sqlite_path=str(db_file),
        inbox_folder=str(inbox_dir),
        heartbeat_days=5,
    )

    captured_cmds = []

    class MockResult:
        returncode = 0
        stdout = "[]"
        stderr = ""

    def mock_run(cmd, *args, **kwargs):
        captured_cmds.append(cmd)
        return MockResult()

    monkeypatch.setattr("subprocess.run", mock_run)
    monkeypatch.setattr("founder_signal.inbox.resolve_himalaya_bin", lambda *args, **kwargs: "/usr/bin/himalaya")

    watcher = InboxWatcher(cfg)
    watcher.himalaya_bin = "/usr/bin/himalaya"
    try:
        # Default should use cfg.heartbeat_days (5)
        watcher.heartbeat_email(["zoho"])
        expected_since_5 = (datetime.now(timezone.utc) - timedelta(days=5)).strftime("%Y-%m-%d")
        assert any(f"after {expected_since_5}" in arg for cmd in captured_cmds for arg in cmd)

        # Overriding with days=10
        captured_cmds.clear()
        watcher.heartbeat_email(["zoho"], days=10)
        expected_since_10 = (datetime.now(timezone.utc) - timedelta(days=10)).strftime("%Y-%m-%d")
        assert any(f"after {expected_since_10}" in arg for cmd in captured_cmds for arg in cmd)
    finally:
        watcher.close()
