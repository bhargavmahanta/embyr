"""Static M4 presentation copy covers the frozen M3 explanation vocabulary."""
from __future__ import annotations

import json
from pathlib import Path

from research.recommendation.simulator.explain import EXPLANATION_CODES

COPY_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "app"
    / "recommendation"
    / "profiles"
    / "recommendation-copy-v1.json"
)


def test_initial_copy_has_a_reviewable_template_for_each_m3_explanation_code():
    copy = json.loads(COPY_PATH.read_text(encoding="utf-8"))

    assert copy["copy_version"] == "recommendation-copy/v1"
    assert set(copy["templates"]) == set(EXPLANATION_CODES)
    for code in EXPLANATION_CODES:
        template = copy["templates"][code]
        assert set(template) == {"hook", "reason"}
        assert all(isinstance(value, str) and value.strip() for value in template.values())
