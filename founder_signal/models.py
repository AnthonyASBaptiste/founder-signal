"""Data models for the Founder Signal commitment ledger."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Source:
    """A piece of source material fed into Founder Signal."""

    id: str
    kind: str  # "email" | "transcript" | "voice-note"
    title: str
    body: str
    received_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "kind": self.kind,
            "title": self.title,
            "body": self.body,
            "received_at": self.received_at.isoformat() if self.received_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Commitment:
    """A single extracted commitment with source evidence."""

    id: str
    source_id: str
    description: str
    owner: Optional[str] = None
    due_date: Optional[str] = None  # ISO date string
    suggested_due_date: Optional[str] = None  # inferred absolute date when none stated
    direction: Optional[str] = None  # "user_committing" | "user_requested" | "third_party"
    decision: Optional[str] = None
    follow_up: Optional[str] = None
    status: str = "open"  # open | done | waiting | deferred | ignore
    evidence: str = ""  # verbatim quote from source
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "description": self.description,
            "owner": self.owner,
            "due_date": self.due_date,
            "suggested_due_date": self.suggested_due_date,
            "direction": self.direction,
            "decision": self.decision,
            "follow_up": self.follow_up,
            "status": self.status,
            "evidence": self.evidence,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Commitment":
        return cls(
            id=d["id"],
            source_id=d["source_id"],
            description=d["description"],
            owner=d.get("owner"),
            due_date=d.get("due_date"),
            suggested_due_date=d.get("suggested_due_date"),
            direction=d.get("direction"),
            decision=d.get("decision"),
            follow_up=d.get("follow_up"),
            status=d.get("status", "open"),
            evidence=d.get("evidence", ""),
            created_at=datetime.fromisoformat(d["created_at"]),
            updated_at=datetime.fromisoformat(d["updated_at"]),
        )
