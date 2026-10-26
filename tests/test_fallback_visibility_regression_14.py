import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.config import Config
from founder_signal.ledger import open_ledger


def test_fallback_visibility_and_extractor_tracking():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = str(Path(tmpdir) / "test.db")
        config = Config(
            inbox_folder=tmpdir,
            ledger_sqlite_path=db_path,
            ledger_backend="sqlite",
            use_llm=True,
            ollama_host="http://127.0.0.1:9999",  # unreachable port to force fallback
        )

        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Ingest with use_llm="on"
        resp = client.post(
            "/ingest",
            data={
                "kind": "email",
                "title": "Fallback Test Email",
                "body": "I will deliver the quarterly review by Friday.",
                "use_llm": "on",
            },
            follow_redirects=True,
        )
        assert resp.status_code == 200
        html = resp.get_data(as_text=True)

        # Check flash warning appears
        assert "Notice: LLM extraction via ollama unavailable" in html
        assert "fell back to rule-based extraction" in html

        # Verify source extractor in ledger
        ledger = open_ledger(config)
        commitments = ledger.list_commitments()
        assert len(commitments) == 1
        c = commitments[0]
        source = ledger.get_source(c.source_id)
        assert source is not None
        assert source.extractor == "rules"
        ledger.close()

        # Verify commitment detail page shows extractor badge
        detail_resp = client.get(f"/commitments/{c.id}")
        assert detail_resp.status_code == 200
        detail_html = detail_resp.get_data(as_text=True)
        assert "rules" in detail_html
