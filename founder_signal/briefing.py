"""Morning briefing: Do now · Coming up · Waiting on someone · Needs clarification."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Any

from .ledger import Ledger
from .models import Commitment


@dataclass
class Briefing:
    do_now: list[Commitment] = field(default_factory=list)
    coming_up: list[Commitment] = field(default_factory=list)
    waiting_on: list[Commitment] = field(default_factory=list)
    needs_clarification: list[Commitment] = field(default_factory=list)
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    summary: str = ""


def _is_overdue_or_due_today(commitment: Commitment) -> bool:
    if not commitment.due_date:
        return False
    try:
        due = date.fromisoformat(commitment.due_date)
    except ValueError:
        return False
    return due <= date.today()


def _is_coming_up(commitment: Commitment, within_days: int = 7) -> bool:
    if not commitment.due_date:
        return False
    try:
        due = date.fromisoformat(commitment.due_date)
    except ValueError:
        return False
    today = date.today()
    return today < due <= today + timedelta(days=within_days)


def generate_briefing(
    ledger: Ledger,
    coming_up_days: int = 7,
    config: Optional[Any] = None,
    founder_name: Optional[str] = None,
) -> Briefing:
    """Generate the morning briefing from the ledger.

    Sections:
    - Do now: overdue or due today, open commitments.
    - Coming up: due within `coming_up_days`, open.
    - Waiting on: open commitments with an owner other than "me"/"I"/founder (delegated).
    - Needs clarification: open commitments missing owner or due date.
    """
    if config is None:
        try:
            from .config import Config
            config = Config.from_env()
        except Exception:
            config = None

    fname = (founder_name or (getattr(config, "founder_name", None) or "")).strip().lower()

    all_open = ledger.list_commitments(status="open")
    briefing = Briefing()

    for c in all_open:
        if _is_overdue_or_due_today(c):
            briefing.do_now.append(c)
        elif _is_coming_up(c, coming_up_days):
            briefing.coming_up.append(c)

        owner = (c.owner or "").strip().lower()
        is_founder = owner in ("me", "i", "myself", "founder") or (
            bool(fname) and (owner == fname or fname in owner or owner in fname)
        )
        if owner and not is_founder:
            briefing.waiting_on.append(c)

        if not c.owner or not c.due_date:
            briefing.needs_clarification.append(c)

    briefing.summary = (
        f"{len(briefing.do_now)} do now · "
        f"{len(briefing.coming_up)} coming up · "
        f"{len(briefing.waiting_on)} waiting on someone · "
        f"{len(briefing.needs_clarification)} needs clarification"
    )
    return briefing
