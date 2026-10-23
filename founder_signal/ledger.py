"""Persistent commitment ledger with SQLite and MongoDB Atlas backends."""

from __future__ import annotations

import sqlite3
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from .models import Commitment, Source


class Ledger(ABC):
    """Abstract commitment ledger."""

    @abstractmethod
    def add_source(self, source: Source) -> None:
        ...

    @abstractmethod
    def get_source(self, source_id: str) -> Optional[Source]:
        ...

    @abstractmethod
    def add_commitment(self, commitment: Commitment) -> None:
        ...

    @abstractmethod
    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        ...

    @abstractmethod
    def list_commitments(self, status: Optional[str] = None) -> list[Commitment]:
        ...

    @abstractmethod
    def update_commitment(self, commitment: Commitment) -> None:
        ...

    @abstractmethod
    def find_by_source(self, source_id: str) -> list[Commitment]:
        ...

    @abstractmethod
    def close(self) -> None:
        ...


class SQLiteLedger(Ledger):
    """SQLite-backed ledger (default for local demos)."""

    def __init__(self, path: str = "data/founder_signal.db"):
        self.path = path
        import os

        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS sources (
                id TEXT PRIMARY KEY,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                received_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS commitments (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                description TEXT NOT NULL,
                owner TEXT,
                due_date TEXT,
                suggested_due_date TEXT,
                direction TEXT,
                decision TEXT,
                follow_up TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                evidence TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id)
            );
            CREATE INDEX IF NOT EXISTS idx_commitments_source ON commitments(source_id);
            CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
            CREATE INDEX IF NOT EXISTS idx_commitments_due ON commitments(due_date);
            """
        )
        # Migration: add new columns to existing databases
        cur.execute("PRAGMA table_info(commitments)")
        existing_cols = {row["name"] for row in cur.fetchall()}
        if "suggested_due_date" not in existing_cols:
            cur.execute("ALTER TABLE commitments ADD COLUMN suggested_due_date TEXT")
        if "direction" not in existing_cols:
            cur.execute("ALTER TABLE commitments ADD COLUMN direction TEXT")
        self.conn.commit()

    def add_source(self, source: Source) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sources (id, kind, title, body, received_at, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.kind,
                source.title,
                source.body,
                source.received_at.isoformat() if source.received_at else None,
                source.created_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_source(self, source_id: str) -> Optional[Source]:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not row:
            return None
        return Source(
            id=row["id"],
            kind=row["kind"],
            title=row["title"],
            body=row["body"],
            received_at=datetime.fromisoformat(row["received_at"]) if row["received_at"] else None,
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def add_commitment(self, commitment: Commitment) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO commitments "
            "(id, source_id, description, owner, due_date, suggested_due_date, direction, decision, follow_up, status, evidence, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                commitment.id,
                commitment.source_id,
                commitment.description,
                commitment.owner,
                commitment.due_date,
                commitment.suggested_due_date,
                commitment.direction,
                commitment.decision,
                commitment.follow_up,
                commitment.status,
                commitment.evidence,
                commitment.created_at.isoformat(),
                commitment.updated_at.isoformat(),
            ),
        )
        self.conn.commit()

    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        row = self.conn.execute(
            "SELECT * FROM commitments WHERE id = ?", (commitment_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_commitment(row)

    def list_commitments(self, status: Optional[str] = None) -> list[Commitment]:
        if status is None:
            rows = self.conn.execute(
                "SELECT * FROM commitments ORDER BY due_date IS NULL, due_date, created_at"
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM commitments WHERE status = ? "
                "ORDER BY due_date IS NULL, due_date, created_at",
                (status,),
            ).fetchall()
        return [self._row_to_commitment(r) for r in rows]

    def update_commitment(self, commitment: Commitment) -> None:
        commitment.updated_at = datetime.now(timezone.utc)
        self.conn.execute(
            "UPDATE commitments SET description=?, owner=?, due_date=?, suggested_due_date=?, direction=?, decision=?, "
            "follow_up=?, status=?, evidence=?, updated_at=? WHERE id=?",
            (
                commitment.description,
                commitment.owner,
                commitment.due_date,
                commitment.suggested_due_date,
                commitment.direction,
                commitment.decision,
                commitment.follow_up,
                commitment.status,
                commitment.evidence,
                commitment.updated_at.isoformat(),
                commitment.id,
            ),
        )
        self.conn.commit()

    def find_by_source(self, source_id: str) -> list[Commitment]:
        rows = self.conn.execute(
            "SELECT * FROM commitments WHERE source_id = ? ORDER BY created_at",
            (source_id,),
        ).fetchall()
        return [self._row_to_commitment(r) for r in rows]

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _row_to_commitment(row: sqlite3.Row) -> Commitment:
        return Commitment(
            id=row["id"],
            source_id=row["source_id"],
            description=row["description"],
            owner=row["owner"],
            due_date=row["due_date"],
            suggested_due_date=row["suggested_due_date"],
            direction=row["direction"],
            decision=row["decision"],
            follow_up=row["follow_up"],
            status=row["status"],
            evidence=row["evidence"] or "",
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
        )


class MongoLedger(Ledger):
    """MongoDB Atlas-backed ledger."""

    def __init__(self, uri: str, database: str = "founder_signal"):
        from pymongo import MongoClient

        self.client = MongoClient(uri)
        self.db = self.client[database]
        self.sources = self.db["sources"]
        self.commitments = self.db["commitments"]
        self.commitments.create_index("source_id")
        self.commitments.create_index("status")
        self.commitments.create_index("due_date")

    def add_source(self, source: Source) -> None:
        self.sources.replace_one({"id": source.id}, source.to_dict(), upsert=True)

    def get_source(self, source_id: str) -> Optional[Source]:
        doc = self.sources.find_one({"id": source_id})
        if not doc:
            return None
        return Source(
            id=doc["id"],
            kind=doc["kind"],
            title=doc["title"],
            body=doc["body"],
            received_at=datetime.fromisoformat(doc["received_at"]) if doc.get("received_at") else None,
            created_at=datetime.fromisoformat(doc["created_at"]),
        )

    def add_commitment(self, commitment: Commitment) -> None:
        self.commitments.replace_one({"id": commitment.id}, commitment.to_dict(), upsert=True)

    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        doc = self.commitments.find_one({"id": commitment_id})
        if not doc:
            return None
        return Commitment.from_dict(doc)

    def list_commitments(self, status: Optional[str] = None) -> list[Commitment]:
        query = {} if status is None else {"status": status}
        cursor = self.commitments.find(query).sort("due_date", 1)
        return [Commitment.from_dict(d) for d in cursor]

    def update_commitment(self, commitment: Commitment) -> None:
        commitment.updated_at = datetime.now(timezone.utc)
        self.commitments.replace_one({"id": commitment.id}, commitment.to_dict(), upsert=True)

    def find_by_source(self, source_id: str) -> list[Commitment]:
        cursor = self.commitments.find({"source_id": source_id}).sort("created_at", 1)
        return [Commitment.from_dict(d) for d in cursor]

    def close(self) -> None:
        self.client.close()


def open_ledger(config) -> Ledger:
    """Open a ledger based on configuration."""
    backend = getattr(config, "ledger_backend", "sqlite")
    if backend == "mongodb":
        uri = getattr(config, "mongodb_uri", None)
        if not uri:
            raise ValueError("MONGODB_URI is required when LEDGER_BACKEND=mongodb")
        return MongoLedger(uri, getattr(config, "mongodb_database", "founder_signal"))
    return SQLiteLedger(getattr(config, "ledger_sqlite_path", "data/founder_signal.db"))
