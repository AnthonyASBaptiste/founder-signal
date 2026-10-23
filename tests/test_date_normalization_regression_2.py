# Regression: ISSUE-002 — Natural language dates in extraction are not normalized to ISO YYYY-MM-DD
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=due_date normalized to ISO YYYY-MM-DD from natural language dates; fails_when=raw text like 'october 30' or 'tomorrow' stored unnormalized; why_new=existing tests only tested YYYY-MM-DD; seam=none; no_claim=none beyond protects

import re
from datetime import date
from founder_signal.models import Source
from founder_signal.extraction import extract, to_commitments
from founder_signal.briefing import _is_coming_up, _is_overdue_or_due_today


def test_natural_language_dates_normalized_to_iso():
    source = Source(
        id="s_test_date",
        kind="email",
        title="Date Test",
        body="I will send the pitch deck by October 30.\nI will review the proposal tomorrow."
    )
    result = extract(source, use_llm=False)
    commitments = to_commitments(result, source.id)

    assert len(commitments) >= 1
    for c in commitments:
        if c.due_date:
            assert re.match(r"^\d{4}-\d{2}-\d{2}$", c.due_date), f"due_date '{c.due_date}' is not ISO YYYY-MM-DD"
            # Must not raise ValueError when parsed with fromisoformat
            parsed = date.fromisoformat(c.due_date)
            assert parsed is not None
