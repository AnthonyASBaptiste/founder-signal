import io
import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.inbox import InboxWatcher
from founder_signal.ledger import open_ledger


def test_upload_dedup_and_processed_marker():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox_dir = Path(tmpdir) / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(Path(tmpdir) / "test.db")

        config = Config(
            inbox_folder=str(inbox_dir),
            ledger_sqlite_path=db_path,
            ledger_backend="sqlite",
        )

        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Upload a transcript file
        file_content = b"I will send the term sheet by tomorrow afternoon."
        data = {
            "kind": "transcript",
            "title": "Investor Call",
            "file": (io.BytesIO(file_content), "term_sheet_call.txt"),
        }

        response = client.post(
            "/ingest",
            data=data,
            content_type="multipart/form-data",
            follow_redirects=True,
        )
        assert response.status_code == 200

        # Check ledger has 1 commitment
        ledger = open_ledger(config)
        try:
            commitments = ledger.list_commitments()
            assert len(commitments) == 1
        finally:
            ledger.close()

        # Check inbox state:
        # 1. File must NOT remain in root inbox_dir
        assert not (inbox_dir / "term_sheet_call.txt").exists()
        # 2. File must be moved to inbox/processed/
        assert (inbox_dir / "processed" / "term_sheet_call.txt").exists()
        # 3. .done marker must exist in inbox_dir
        assert (inbox_dir / "term_sheet_call.txt.done").exists()

        # 4. Now run InboxWatcher.scan() - it must process 0 files!
        watcher = InboxWatcher(config)
        try:
            processed_count = watcher.scan()
            assert processed_count == 0
        finally:
            watcher.close()

        # Ledger must STILL have only 1 commitment (no duplicate ingestion)
        ledger = open_ledger(config)
        try:
            commitments = ledger.list_commitments()
            assert len(commitments) == 1
        finally:
            ledger.close()
