"""Founder Signal — commitment extraction and reconciliation for overloaded founders.

Extracts commitments, deadlines, owners, decisions and promised follow-ups from
email text and voice-note transcripts, reconciles them against a persistent
commitment ledger, and emits a tiny action briefing:

    Do now · Coming up · Waiting on someone · Needs clarification

The agent proposes changes; it never sends messages, accepts commitments or
marks tasks complete without your confirmation.
"""

from .config import Config

__all__ = ["Config"]
