import os
import subprocess
import tempfile
from pathlib import Path


def test_demo_script_protects_caller_database():
    """Verify that demo.sh does not delete or overwrite a caller-specified database."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a pre-existing database with valuable user content
        precious_db = Path(tmpdir) / "precious_user_data.db"
        precious_db.write_text("PRAGMA user_version = 42;", encoding="utf-8")

        env = os.environ.copy()
        env["LEDGER_SQLITE_PATH"] = str(precious_db)
        env["FOUNDER_NAME"] = "TestFounder"

        # Run demo/demo.sh
        repo_root = Path(__file__).resolve().parent.parent
        demo_script = repo_root / "demo" / "demo.sh"

        result = subprocess.run(
            ["bash", str(demo_script)],
            cwd=str(repo_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert result.returncode == 0, f"demo.sh failed: {result.stderr}"

        # The caller's precious database MUST NOT have been deleted
        assert precious_db.exists(), "demo.sh deleted the caller's database at LEDGER_SQLITE_PATH!"
        assert (
            precious_db.read_text(encoding="utf-8") == "PRAGMA user_version = 42;"
        ), "demo.sh overwrote the caller's database at LEDGER_SQLITE_PATH!"
