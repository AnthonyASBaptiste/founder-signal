# Regression: ISSUE-003 — Web upload exceeding max_upload_mb returns unstyled 413 instead of redirect with flash
# Found by /qa on 2026-10-26
# Report: .gstack/qa-reports/run-20261026T063027Z/qa-report-founder-signal-2026-10-26.md
# Value: protects=web upload size limit handled with redirect and flash; fails_when=413 unhandled raw page is returned; why_new=no existing test covers upload size limit handler; seam=none; no_claim=none beyond protects

import io
import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.config import Config


def test_web_upload_exceeds_size_limit_redirects_with_flash():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Set max_upload_mb = 1 MB
        cfg = Config(
            inbox_folder=tmpdir,
            ledger_sqlite_path=str(Path(tmpdir) / "test.db"),
            max_upload_mb=1,
        )
        app = create_app(cfg)
        app.config["TESTING"] = True
        client = app.test_client()

        # Upload a 2 MB file (exceeds 1 MB limit)
        oversized_data = b"0" * (2 * 1024 * 1024)
        data = {
            "kind": "transcript",
            "title": "Huge Transcript",
            "file": (io.BytesIO(oversized_data), "huge_transcript.txt"),
        }
        resp = client.post("/ingest", data=data, content_type="multipart/form-data", follow_redirects=True)

        assert resp.status_code == 200
        html = resp.get_data(as_text=True)
        # Should flash a clean, actionable error message mentioning the size limit
        assert "File too large" in html or "file too large" in html.lower()
        assert "1 MB" in html or "limit" in html.lower()
