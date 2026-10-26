# Regression: ISSUE-002 — CLI ingest non-existent file produces unhandled FileNotFoundError traceback
# Found by /qa on 2026-10-26
# Report: .gstack/qa-reports/run-20261026T063027Z/qa-report-founder-signal-2026-10-26.md
# Value: protects=cli ingest handles missing file gracefully; fails_when=uncaught FileNotFoundError is raised; why_new=no existing test covers CLI missing file error; seam=none; no_claim=none beyond protects

import subprocess
import sys


def test_cli_ingest_missing_file_graceful_error():
    result = subprocess.run(
        [sys.executable, "-m", "founder_signal.cli", "ingest", "/tmp/definitely_non_existent_file_fs_test.txt"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    # Should not dump an unhandled Python traceback
    assert "Traceback (most recent call last)" not in result.stderr
    assert "Traceback (most recent call last)" not in result.stdout
    # Should print a clear error to stderr
    err = result.stderr.lower()
    assert "error" in err or "not found" in err
