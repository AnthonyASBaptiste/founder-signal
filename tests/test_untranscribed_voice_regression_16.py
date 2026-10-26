import io
import tempfile
from pathlib import Path
from unittest.mock import patch

from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.inbox import InboxWatcher
from founder_signal.ledger import open_ledger


def test_web_upload_untranscribed_voice_note_state():
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

        # Simulate whisper unavailable or failing to transcribe
        with patch("founder_signal.inbox._transcribe_audio", return_value=None):
            audio_bytes = b"RIFFfake_wave_data_header_fmt_data"
            data = {
                "kind": "voice-note",
                "title": "Co-founder Sync Voice Memo",
                "file": (io.BytesIO(audio_bytes), "sync_memo.wav"),
            }
            resp = client.post("/ingest", data=data, content_type="multipart/form-data", follow_redirects=True)
            assert resp.status_code == 200
            html = resp.get_data(as_text=True)

            # Check that file landed in needs_transcription
            needs_trans_dir = inbox_dir / "needs_transcription"
            assert needs_trans_dir.exists()
            files_in_needs = list(needs_trans_dir.glob("*.wav"))
            assert len(files_in_needs) == 1
            assert files_in_needs[0].name == "sync_memo.wav"

            # Check that file was NOT placed in processed/ and NO .done file exists
            processed_dir = inbox_dir / "processed"
            assert not processed_dir.exists() or len(list(processed_dir.iterdir())) == 0
            done_files = list(inbox_dir.glob("*.done")) + list(needs_trans_dir.glob("*.done"))
            assert len(done_files) == 0

            # Ledger must remain empty: no source, no commitments created
            ledger = open_ledger(config)
            assert len(ledger.list_commitments()) == 0
            cur = ledger.conn.cursor()
            cur.execute("SELECT COUNT(*) FROM sources")
            assert cur.fetchone()[0] == 0
            ledger.close()

            # Dashboard reflects the pending state
            assert "Audio Pending" in html
            assert "needs transcription" in html.lower()


def test_inbox_watcher_untranscribed_voice_note_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        inbox_dir = Path(tmpdir) / "inbox"
        inbox_dir.mkdir(parents=True, exist_ok=True)
        db_path = str(Path(tmpdir) / "test.db")

        config = Config(
            inbox_folder=str(inbox_dir),
            ledger_sqlite_path=db_path,
            ledger_backend="sqlite",
        )

        watcher = InboxWatcher(config)

        # Create an audio file in the inbox
        audio_file = inbox_dir / "voice_promise.mp3"
        audio_file.write_bytes(b"FAKE_MP3_DATA")

        with patch("founder_signal.inbox._transcribe_audio", return_value=None):
            watcher.process_file(audio_file)

        # File moved to needs_transcription
        needs_trans_file = inbox_dir / "needs_transcription" / "voice_promise.mp3"
        assert needs_trans_file.exists()
        assert not audio_file.exists()

        # No .done marker created
        assert not (inbox_dir / ".voice_promise.mp3.done").exists()
        assert not (inbox_dir / "needs_transcription" / ".voice_promise.mp3.done").exists()

        # No source or commitments added to ledger
        assert len(watcher.ledger.list_commitments()) == 0
        cur = watcher.ledger.conn.cursor()
        cur.execute("SELECT COUNT(*) FROM sources")
        assert cur.fetchone()[0] == 0

        watcher.ledger.close()
