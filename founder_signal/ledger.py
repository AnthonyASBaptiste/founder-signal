"""Persistent commitment ledger with SQLite and MongoDB Atlas backends."""

from __future__ import annotations

import json
import sqlite3
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional, Any

from .models import Commitment, ProcessingLog, Source

DEFAULT_SETTINGS = {
    # 1. VIP People & Ingestion Criteria
    "vip_people": [
        {"name": "Tishana Simon", "role": "co-founder", "email": "tishana@research-navigator.ai"},
        {"name": "Tishana Simon (Alt)", "role": "co-founder", "email": "dm.businesstt@gmail.com"},
        {"name": "Keneisha Browne", "role": "mentor", "email": "keneisha_browne@hotmail.com"},
        {"name": "Point Lisas Nitrogen (PLNL)", "role": "key partner", "domain": "plnl.co.tt"},
    ],
    "vip_emails": [
        "tishana@research-navigator.ai",
        "dm.businesstt@gmail.com",
        "keneisha_browne@hotmail.com",
    ],
    "vip_domains": [
        "plnl.co.tt",
    ],
    "vip_keywords": [
        "Future Caribbean",
        "Caribbean Dragons",
        "Omni Caribbean",
        "futurecaribbean",
        "caribbeandragons",
        "omnicaribbean",
    ],
    "only_scan_vip": True,
    "include_directly_addressed": False,
    "founder_email": "",
    "auto_ignore_bulk": True,
    "excluded_count": 0,

    # 5. Digest & Schedule Tuning
    "digest_enabled": True,
    "digest_time": "08:00",
    "digest_threshold_only": True,
    "due_soon_days": 3,
    "check_interval_mins": 15,
    "discord_alerts_target": "discord:alerts-and-logs",
    "app_url": "https://founder-signal.builtbyanthony.tech",

    # 6. Learned Rules & Exclusions
    "suggested_rules": [],
    "dismissal_counts": {},
    "excluded_senders": [],
    "excluded_domains": [],
}

_SHARED_MONGO_CLIENT = None


def get_shared_mongo_client(uri: str):
    """Reuse a single MongoClient to preserve connection pools and eliminate SSL/TLS reconnect latency."""
    global _SHARED_MONGO_CLIENT
    if _SHARED_MONGO_CLIENT is None:
        from pymongo import MongoClient

        _SHARED_MONGO_CLIENT = MongoClient(uri, serverSelectionTimeoutMS=5000, maxPoolSize=50)
    return _SHARED_MONGO_CLIENT



class Ledger(ABC):
    """Abstract commitment ledger."""

    @abstractmethod
    def add_source(self, source: Source) -> None:
        ...

    @abstractmethod
    def get_source(self, source_id: str) -> Optional[Source]:
        ...

    @abstractmethod
    def list_sources(self) -> list[Source]:
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
    def add_processing_log(self, log: ProcessingLog) -> None:
        ...

    @abstractmethod
    def list_processing_logs(self) -> list[ProcessingLog]:
        ...

    @abstractmethod
    def get_settings(self) -> dict:
        ...

    @abstractmethod
    def update_settings(self, settings: dict) -> None:
        ...

    @abstractmethod
    def has_processed_file(self, filename: str) -> bool:
        ...

    @abstractmethod
    def clear_ledger(self) -> None:
        ...

    @abstractmethod
    def close(self) -> None:
        ...

    def increment_excluded_count(self, n: int = 1) -> int:
        """Increment count of messages filtered out for predictable reporting."""
        settings = self.get_settings()
        new_count = settings.get("excluded_count", 0) + n
        settings["excluded_count"] = new_count
        self.update_settings(settings)
        return new_count

    def reset_excluded_count(self) -> None:
        """Reset excluded message count."""
        settings = self.get_settings()
        settings["excluded_count"] = 0
        self.update_settings(settings)

    def record_dismissal(self, pattern: str, title: Optional[str] = None) -> Optional[dict]:
        """Record user dismissal (e.g. marking ignore) for a sender/domain and suggest rules when repeated."""
        if not pattern or not pattern.strip():
            return None
        clean_p = pattern.lower().strip()
        settings = self.get_settings()
        counts = settings.setdefault("dismissal_counts", {})
        counts[clean_p] = counts.get(clean_p, 0) + 1

        new_rule = None
        # Threshold: 2 dismissals suggests a filter rule for user approval
        if counts[clean_p] >= 2:
            excluded = set(settings.get("excluded_senders", []) + settings.get("excluded_domains", []))
            rules = settings.setdefault("suggested_rules", [])
            already_suggested = any(r.get("pattern") == clean_p and r.get("status") in ("pending", "accepted") for r in rules)
            if clean_p not in excluded and not already_suggested:
                rule_type = "exclude_sender" if "@" in clean_p else "exclude_domain"
                new_rule = {
                    "id": f"rule_{uuid.uuid4().hex[:8]}",
                    "pattern": clean_p,
                    "type": rule_type,
                    "reason": f"You ignored {counts[clean_p]} commitments associated with {clean_p}.",
                    "status": "pending",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                }
                rules.append(new_rule)
        self.update_settings(settings)
        return new_rule

    def accept_suggested_rule(self, rule_id: str) -> bool:
        """Accept a suggested exclusion rule."""
        settings = self.get_settings()
        rules = settings.get("suggested_rules", [])
        for r in rules:
            if r.get("id") == rule_id and r.get("status") == "pending":
                r["status"] = "accepted"
                pattern = r.get("pattern", "")
                if "@" in pattern:
                    ex = settings.setdefault("excluded_senders", [])
                    if pattern not in ex:
                        ex.append(pattern)
                else:
                    ex = settings.setdefault("excluded_domains", [])
                    if pattern not in ex:
                        ex.append(pattern)
                self.update_settings(settings)
                return True
        return False

    def dismiss_suggested_rule(self, rule_id: str) -> bool:
        """Dismiss a suggested rule without applying it."""
        settings = self.get_settings()
        rules = settings.get("suggested_rules", [])
        for r in rules:
            if r.get("id") == rule_id and r.get("status") == "pending":
                r["status"] = "dismissed"
                self.update_settings(settings)
                return True
        return False


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
                created_at TEXT NOT NULL,
                extractor TEXT
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
                pending_change TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES sources(id)
            );
            CREATE INDEX IF NOT EXISTS idx_commitments_source ON commitments(source_id);
            CREATE INDEX IF NOT EXISTS idx_commitments_status ON commitments(status);
            CREATE INDEX IF NOT EXISTS idx_commitments_due ON commitments(due_date);
            CREATE TABLE IF NOT EXISTS processing_log (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                kind TEXT NOT NULL,
                source_id TEXT,
                received_at TEXT,
                processed_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ok',
                commitment_count INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_processing_log_processed_at ON processing_log(processed_at);
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        # Migration: add new columns to existing databases
        cur.execute("PRAGMA table_info(commitments)")
        existing_cols = {row["name"] for row in cur.fetchall()}
        if "suggested_due_date" not in existing_cols:
            cur.execute("ALTER TABLE commitments ADD COLUMN suggested_due_date TEXT")
        if "direction" not in existing_cols:
            cur.execute("ALTER TABLE commitments ADD COLUMN direction TEXT")
        if "pending_change" not in existing_cols:
            cur.execute("ALTER TABLE commitments ADD COLUMN pending_change TEXT")

        cur.execute("PRAGMA table_info(sources)")
        existing_source_cols = {row["name"] for row in cur.fetchall()}
        if "extractor" not in existing_source_cols:
            cur.execute("ALTER TABLE sources ADD COLUMN extractor TEXT")

        self.conn.commit()

    def add_source(self, source: Source) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO sources (id, kind, title, body, received_at, created_at, extractor) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                source.id,
                source.kind,
                source.title,
                source.body,
                source.received_at.isoformat() if source.received_at else None,
                source.created_at.isoformat(),
                source.extractor,
            ),
        )
        self.conn.commit()

    def get_source(self, source_id: str) -> Optional[Source]:
        row = self.conn.execute(
            "SELECT * FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if not row:
            return None
        raw_row = dict(row)
        return Source(
            id=raw_row["id"],
            kind=raw_row["kind"],
            title=raw_row["title"],
            body=raw_row["body"],
            received_at=datetime.fromisoformat(raw_row["received_at"]) if raw_row.get("received_at") else None,
            created_at=datetime.fromisoformat(raw_row["created_at"]),
            extractor=raw_row.get("extractor"),
        )

    def list_sources(self) -> list[Source]:
        rows = self.conn.execute(
            "SELECT * FROM sources ORDER BY received_at IS NULL, received_at DESC, created_at DESC"
        ).fetchall()
        return [self._row_to_source(r) for r in rows]

    @staticmethod
    def _row_to_source(row: sqlite3.Row) -> Source:
        raw_row = dict(row)
        return Source(
            id=raw_row["id"],
            kind=raw_row["kind"],
            title=raw_row["title"],
            body=raw_row["body"],
            received_at=datetime.fromisoformat(raw_row["received_at"]) if raw_row.get("received_at") else None,
            created_at=datetime.fromisoformat(raw_row["created_at"]),
            extractor=raw_row.get("extractor"),
        )

    def add_commitment(self, commitment: Commitment) -> None:
        pending_json = json.dumps(commitment.pending_change) if commitment.pending_change else None
        self.conn.execute(
            "INSERT OR REPLACE INTO commitments "
            "(id, source_id, description, owner, due_date, suggested_due_date, direction, decision, follow_up, status, evidence, pending_change, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                pending_json,
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
        pending_json = json.dumps(commitment.pending_change) if commitment.pending_change else None
        self.conn.execute(
            "UPDATE commitments SET description=?, owner=?, due_date=?, suggested_due_date=?, direction=?, decision=?, "
            "follow_up=?, status=?, evidence=?, pending_change=?, updated_at=? WHERE id=?",
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
                pending_json,
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

    def add_processing_log(self, log: ProcessingLog) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO processing_log "
            "(id, filename, kind, source_id, received_at, processed_at, status, commitment_count, error_message) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                log.id,
                log.filename,
                log.kind,
                log.source_id,
                log.received_at.isoformat() if log.received_at else None,
                log.processed_at.isoformat(),
                log.status,
                log.commitment_count,
                log.error_message,
            ),
        )
        self.conn.commit()

    def list_processing_logs(self) -> list[ProcessingLog]:
        rows = self.conn.execute(
            "SELECT * FROM processing_log ORDER BY processed_at DESC"
        ).fetchall()
        return [self._row_to_processing_log(r) for r in rows]

    def get_settings(self) -> dict:
        row = self.conn.execute("SELECT value FROM settings WHERE key = 'app_settings'").fetchone()
        if not row:
            settings = dict(DEFAULT_SETTINGS)
            self.update_settings(settings)
            return settings
        try:
            stored = json.loads(row["value"])
            res = dict(DEFAULT_SETTINGS)
            res.update(stored)
            return res
        except Exception:
            return dict(DEFAULT_SETTINGS)

    def update_settings(self, settings: dict) -> None:
        val = json.dumps(settings)
        self.conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('app_settings', ?)", (val,))
        self.conn.commit()

    def has_processed_file(self, filename: str) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM processing_log WHERE filename = ? AND status = 'ok' LIMIT 1",
            (filename,),
        ).fetchone()
        return row is not None

    def clear_ledger(self) -> None:
        self.conn.execute("DELETE FROM commitments")
        self.conn.execute("DELETE FROM sources")
        self.conn.execute("DELETE FROM processing_log")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _row_to_processing_log(row: sqlite3.Row) -> ProcessingLog:
        raw_row = dict(row)
        return ProcessingLog(
            id=raw_row["id"],
            filename=raw_row["filename"],
            kind=raw_row["kind"],
            source_id=raw_row.get("source_id"),
            received_at=datetime.fromisoformat(raw_row["received_at"]) if raw_row.get("received_at") else None,
            processed_at=datetime.fromisoformat(raw_row["processed_at"]),
            status=raw_row.get("status", "ok"),
            commitment_count=raw_row.get("commitment_count", 0),
            error_message=raw_row.get("error_message"),
        )

    @staticmethod
    def _row_to_commitment(row: sqlite3.Row) -> Commitment:
        raw_row = dict(row)
        pending_val = raw_row.get("pending_change")
        pending_change = json.loads(pending_val) if pending_val else None
        return Commitment(
            id=raw_row["id"],
            source_id=raw_row["source_id"],
            description=raw_row["description"],
            owner=raw_row.get("owner"),
            due_date=raw_row.get("due_date"),
            suggested_due_date=raw_row.get("suggested_due_date"),
            direction=raw_row.get("direction"),
            decision=raw_row.get("decision"),
            follow_up=raw_row.get("follow_up"),
            status=raw_row.get("status", "open"),
            evidence=raw_row.get("evidence") or "",
            pending_change=pending_change,
            created_at=datetime.fromisoformat(raw_row["created_at"]),
            updated_at=datetime.fromisoformat(raw_row["updated_at"]),
        )


class MongoLedger(Ledger):
    """MongoDB Atlas-backed ledger."""

    def __init__(self, uri: str, database: str = "founder_signal", client: Optional[Any] = None):
        if client is not None:
            self.client = client
            self._shared = False
        else:
            self.client = get_shared_mongo_client(uri)
            self._shared = True
        self.db = self.client[database]
        self.sources = self.db["sources"]
        self.commitments = self.db["commitments"]
        self.processing_logs = self.db["processing_logs"]
        self.settings = self.db["settings"]
        # Create indexes best-effort; don't block app startup if MongoDB is
        # temporarily unreachable. Indexes are idempotent and will be created
        # on the next successful connection.
        try:
            self.commitments.create_index("source_id")
            self.commitments.create_index("status")
            self.commitments.create_index("due_date")
            self.processing_logs.create_index("processed_at")
            self.processing_logs.create_index("filename")
        except Exception:
            pass

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
            extractor=doc.get("extractor"),
        )

    def list_sources(self) -> list[Source]:
        cursor = self.sources.find().sort([("received_at", -1), ("created_at", -1)])
        return [Source(
            id=d["id"],
            kind=d["kind"],
            title=d["title"],
            body=d["body"],
            received_at=datetime.fromisoformat(d["received_at"]) if d.get("received_at") else None,
            created_at=datetime.fromisoformat(d["created_at"]),
            extractor=d.get("extractor"),
        ) for d in cursor]

    def add_commitment(self, commitment: Commitment) -> None:
        self.commitments.replace_one({"id": commitment.id}, commitment.to_dict(), upsert=True)

    def get_commitment(self, commitment_id: str) -> Optional[Commitment]:
        doc = self.commitments.find_one({"id": commitment_id})
        if not doc:
            return None
        return Commitment.from_dict(doc)

    def list_commitments(self, status: Optional[str] = None) -> list[Commitment]:
        query = {} if status is None else {"status": status}
        # Compound sort: due_date ascending (nulls sort first in MongoDB),
        # then created_at as a stable tiebreaker. Matches SQLite's
        # ORDER BY due_date, created_at intent for deterministic ordering.
        cursor = self.commitments.find(query).sort([("due_date", 1), ("created_at", 1)])
        return [Commitment.from_dict(d) for d in cursor]

    def update_commitment(self, commitment: Commitment) -> None:
        commitment.updated_at = datetime.now(timezone.utc)
        self.commitments.replace_one({"id": commitment.id}, commitment.to_dict(), upsert=True)

    def find_by_source(self, source_id: str) -> list[Commitment]:
        cursor = self.commitments.find({"source_id": source_id}).sort("created_at", 1)
        return [Commitment.from_dict(d) for d in cursor]

    def add_processing_log(self, log: ProcessingLog) -> None:
        self.processing_logs.replace_one({"id": log.id}, log.to_dict(), upsert=True)

    def list_processing_logs(self) -> list[ProcessingLog]:
        cursor = self.processing_logs.find().sort("processed_at", -1)
        return [ProcessingLog.from_dict(d) for d in cursor]

    def get_settings(self) -> dict:
        doc = self.settings.find_one({"_id": "app_settings"})
        if not doc:
            settings = dict(DEFAULT_SETTINGS)
            self.update_settings(settings)
            return settings
        res = dict(DEFAULT_SETTINGS)
        for k, v in doc.items():
            if k != "_id":
                res[k] = v
        return res

    def update_settings(self, settings: dict) -> None:
        to_save = dict(settings)
        to_save["_id"] = "app_settings"
        self.settings.replace_one({"_id": "app_settings"}, to_save, upsert=True)

    def has_processed_file(self, filename: str) -> bool:
        return self.processing_logs.find_one({"filename": filename, "status": "ok"}) is not None

    def clear_ledger(self) -> None:
        self.commitments.delete_many({})
        self.sources.delete_many({})
        self.processing_logs.delete_many({})

    def close(self) -> None:
        if not getattr(self, "_shared", False):
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
