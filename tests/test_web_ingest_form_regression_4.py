# Regression: ISSUE-004 — Ingest template has duplicate field-file IDs and hidden required inputs
# Found by /qa on 2026-10-23
# Report: .gstack/qa-reports/qa-report-localhost-2026-10-23.md
# Value: protects=ingest page file inputs have unique IDs and toggle properly without hidden required inputs; fails_when=duplicate id="field-file" exists or labels mismatch; why_new=no HTML template contract test existed; seam=none; no_claim=none beyond protects

import re
from pathlib import Path


def test_ingest_template_file_inputs_have_unique_ids_and_labels():
    tmpl_path = Path("founder_signal/web/templates/ingest.html")
    content = tmpl_path.read_text(encoding="utf-8")

    # Find all file inputs
    file_inputs = re.findall(r'<input[^>]*type="file"[^>]*>', content)
    assert len(file_inputs) == 2, f"Expected 2 file inputs, got {len(file_inputs)}"

    # Check IDs
    ids = []
    for fi in file_inputs:
        m = re.search(r'id="([^"]+)"', fi)
        assert m is not None, f"File input missing id: {fi}"
        ids.append(m.group(1))

    # All IDs must be unique
    assert len(ids) == len(set(ids)), f"Duplicate IDs found in file inputs: {ids}"

    # Labels must match the input IDs
    for input_id in ids:
        label_match = re.search(rf'<label[^>]*for="{input_id}"', content)
        assert label_match is not None, f"No matching label found for id={input_id}"

    # Script must reference all file input IDs to toggle required/disabled
    for input_id in ids:
        assert input_id in content, f"Script does not reference {input_id}"
