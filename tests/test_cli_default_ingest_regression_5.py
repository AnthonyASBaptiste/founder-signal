# Regression: ISSUE-005 — CLI fails with invalid choice when ingest subcommand is omitted
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=cli auto-defaults to ingest for files and ingest flags; fails_when=cli errors on --kind email or raw file path; why_new=no CLI argument parsing tests existed; seam=none; no_claim=none beyond protects

import pytest
from founder_signal.cli import main


def test_cli_defaults_to_ingest_for_flags(monkeypatch, tmp_path):
    email_file = tmp_path / "email.txt"
    email_file.write_text("I will send the report by tomorrow.", encoding="utf-8")

    # Mock _ingest to verify it gets invoked
    ingest_called = []
    monkeypatch.setattr("founder_signal.cli._ingest", lambda args, cfg: ingest_called.append(args) or 0)

    # 1. Calling with a file directly as first argument (README example: python -m founder_signal.cli transcript.txt)
    rc1 = main([str(email_file), "--kind", "transcript", "--title", "Weekly sync"])
    assert rc1 == 0
    assert len(ingest_called) == 1
    assert ingest_called[0].file == str(email_file)
    assert ingest_called[0].kind == "transcript"

    # 2. Calling with flags directly (README example: cat email.txt | python -m founder_signal.cli --kind email)
    rc2 = main(["--kind", "email", "--title", "Accelerator update"])
    assert rc2 == 0
    assert len(ingest_called) == 2
    assert ingest_called[1].kind == "email"
    assert ingest_called[1].title == "Accelerator update"
