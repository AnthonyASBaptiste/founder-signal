"""Commitment reconciliation: detect changes, duplicates, missing details,
approaching deadlines; retain source evidence.

The agent proposes changes; it never applies them without confirmation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from .ledger import Ledger
from .models import Commitment, Source


@dataclass
class ReconciliationIssue:
    """A proposed reconciliation action requiring user confirmation."""

    kind: str  # "duplicate" | "change" | "missing_detail" | "approaching_deadline" | "new"
    commitment_id: str
    description: str
    proposed: Optional[Commitment] = None  # proposed new/updated state
    evidence: str = ""
    requires_confirmation: bool = True


@dataclass
class ReconciliationResult:
    new_commitments: list[Commitment] = field(default_factory=list)
    issues: list[ReconciliationIssue] = field(default_factory=list)
    summary: str = ""


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _is_duplicate(a: Commitment, b: Commitment, threshold: float = 0.8) -> bool:
    """Exact/near duplicate: same description, same owner, same due date."""
    return (
        _description_similar(a, b, threshold=threshold)
        and _owner_match(a, b)
        and _due_date_match(a, b)
    )


def _description_similar(a: Commitment, b: Commitment, threshold: float = 0.75) -> bool:
    """Jaccard similarity on the description words alone."""
    desc_a = _normalize(a.description)
    desc_b = _normalize(b.description)
    if not desc_a or not desc_b:
        return False
    wa = set(desc_a.split())
    wb = set(desc_b.split())
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= threshold


def _owner_match(a: Commitment, b: Commitment) -> bool:
    return (a.owner or "").strip().lower() == (b.owner or "").strip().lower()


def _due_date_match(a: Commitment, b: Commitment) -> bool:
    return (a.due_date or "") == (b.due_date or "")


def _due_soon(commitment: Commitment, within_days: int = 7) -> bool:
    if not commitment.due_date:
        return False
    try:
        due = date.fromisoformat(commitment.due_date)
    except ValueError:
        return False
    today = date.today()
    return today <= due <= today + timedelta(days=within_days)


def _missing_detail(commitment: Commitment) -> Optional[str]:
    if not commitment.owner:
        return "owner"
    if not commitment.due_date:
        return "due_date"
    return None


def reconcile(ledger: Ledger, new_commitments: list[Commitment],
              within_days: int = 7) -> ReconciliationResult:
    """Reconcile newly extracted commitments against the existing ledger.

    For each new commitment:
    - If identical to an existing open commitment -> duplicate issue (not added).
    - Otherwise -> added to new_commitments, with any issues flagged:
        * missing_detail: owner or due_date not stated
        * approaching_deadline: due within `within_days`

    Returns proposed changes; does not mutate the ledger.
    """
    existing = ledger.list_commitments(status="open")
    result = ReconciliationResult()

    for new in new_commitments:
        # Existing commitments with a similar description (candidates for
        # duplicate or change detection).
        similar = [ex for ex in existing if _description_similar(new, ex)]

        # Exact/near duplicate: same description, same owner, same due date.
        dup_match: Optional[Commitment] = next(
            (ex for ex in similar if _owner_match(new, ex) and _due_date_match(new, ex)),
            None,
        )

        if dup_match:
            result.issues.append(ReconciliationIssue(
                kind="duplicate",
                commitment_id=new.id,
                description=f"Possible duplicate of existing commitment '{dup_match.description}' (source {dup_match.source_id}).",
                proposed=dup_match,
                evidence=new.evidence,
            ))
            continue

        # Change: similar description, but the owner or due date differs.
        # The existing promise appears to have moved (e.g. "Friday" → "Monday");
        # propose updating it and retain both source quotes as evidence.
        change_match: Optional[Commitment] = next(
            (ex for ex in similar if not _owner_match(new, ex) or not _due_date_match(new, ex)),
            None,
        )

        if change_match is not None:
            ex = change_match
            source = ledger.get_source(new.source_id)
            new_source_title = source.title if source else new.source_id
            proposed = Commitment(
                id=ex.id,
                source_id=ex.source_id,
                description=ex.description,
                owner=new.owner if new.owner else ex.owner,
                due_date=new.due_date if new.due_date else ex.due_date,
                suggested_due_date=ex.suggested_due_date,
                direction=ex.direction,
                decision=ex.decision,
                follow_up=ex.follow_up,
                status=ex.status,
                evidence=(
                    f"{ex.evidence}\n\n-- Updated from source '{new_source_title}' --\n{new.evidence}"
                ),
                created_at=ex.created_at,
                updated_at=ex.updated_at,
            )
            changed_bits = []
            if ex.owner != proposed.owner:
                changed_bits.append(f"owner: {ex.owner or '—'} → {proposed.owner or '—'}")
            if ex.due_date != proposed.due_date:
                changed_bits.append(f"due date: {ex.due_date or '—'} → {proposed.due_date or '—'}")
            result.issues.append(ReconciliationIssue(
                kind="change",
                commitment_id=ex.id,
                description=(
                    f"Commitment '{ex.description}' appears to have changed: "
                    f"{'; '.join(changed_bits)}."
                ),
                proposed=proposed,
                evidence=new.evidence,
            ))
            continue

        # Not a duplicate or change: add to new commitments, then flag any issues.
        result.new_commitments.append(new)

        # Check for missing details.
        missing = _missing_detail(new)
        if missing:
            result.issues.append(ReconciliationIssue(
                kind="missing_detail",
                commitment_id=new.id,
                description=f"Commitment '{new.description}' is missing {missing}.",
                proposed=new,
                evidence=new.evidence,
            ))

        # Check approaching deadline.
        if _due_soon(new, within_days):
            result.issues.append(ReconciliationIssue(
                kind="approaching_deadline",
                commitment_id=new.id,
                description=f"Commitment '{new.description}' is due {new.due_date} (within {within_days} days).",
                proposed=new,
                evidence=new.evidence,
            ))

    result.summary = (
        f"{len(result.new_commitments)} new commitment(s), "
        f"{len(result.issues)} issue(s) needing review."
    )
    return result
