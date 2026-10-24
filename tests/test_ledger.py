"""Tests for the SQLite commitment ledger."""

import os
import tempfile

from founder_signal.ledger import SQLiteLedger, open_ledger
from founder_signal.models import Commitment, Source


def _tmp_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path


def test_add_and_get_source():
    path = _tmp_path()
    try:
        ledger = SQLiteLedger(path)
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        got = ledger.get_source("s1")
        assert got is not None
        assert got.title == "T"
        assert got.kind == "email"
        ledger.close()
    finally:
        os.unlink(path)


def test_add_and_list_commitments():
    path = _tmp_path()
    try:
        ledger = SQLiteLedger(path)
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        c = Commitment(id="c1", source_id="s1", description="Do X", owner="me", due_date="2026-11-01")
        ledger.add_commitment(c)
        got = ledger.get_commitment("c1")
        assert got is not None
        assert got.description == "Do X"
        all_c = ledger.list_commitments()
        assert len(all_c) == 1
        open_c = ledger.list_commitments(status="open")
        assert len(open_c) == 1
        ledger.close()
    finally:
        os.unlink(path)


def test_update_commitment():
    path = _tmp_path()
    try:
        ledger = SQLiteLedger(path)
        source = Source(id="s1", kind="email", title="T", body="B")
        ledger.add_source(source)
        c = Commitment(id="c1", source_id="s1", description="Do X", status="open")
        ledger.add_commitment(c)
        c.status = "done"
        ledger.update_commitment(c)
        got = ledger.get_commitment("c1")
        assert got.status == "done"
        ledger.close()
    finally:
        os.unlink(path)


def test_open_ledger_sqlite_default():
    from founder_signal.config import Config
    cfg = Config(ledger_backend="sqlite", ledger_sqlite_path=_tmp_path())
    try:
        ledger = open_ledger(cfg)
        assert ledger is not None
        ledger.close()
    finally:
        os.unlink(cfg.ledger_sqlite_path)
