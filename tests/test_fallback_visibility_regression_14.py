import os
import tempfile
from pathlib import Path

from founder_signal.app import create_app
from founder_signal.auth import _reset_cache_for_testing
from founder_signal.config import Config
from founder_signal.ledger import open_ledger
from founder_signal.models import Commitment, Source


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

        # Configure single-user auth for the test client
        os.environ["FS_ADMIN_USER"] = "test"
        os.environ["FS_ADMIN_PASSWORD"] = "test"
        _reset_cache_for_testing()

        app = create_app(config)
        app.config["TESTING"] = True
        client = app.test_client()

        # Sign in before accessing protected routes
        client.post("/login", data={"username": "test", "password": "test"})

        # Add commitment directly to ledger with rules extractor (simulating LLM fallback)
        ledger = open_ledger(config)
        source = Source(id="s1", kind="email", title="Fallback Test Email", body="I will deliver the quarterly review by Friday.", extractor="rules")
        ledger.add_source(source)
        c = Commitment(
            id="c1",
            source_id="s1",
            description="Deliver the quarterly review",
            owner="me",
            due_date="2026-11-06",
            status="open",
            evidence="I will deliver the quarterly review by Friday."
        )
        ledger.add_commitment(c)
        ledger.close()

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
