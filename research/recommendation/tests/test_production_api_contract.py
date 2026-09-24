"""Assert the M4 request and response examples remain valid contract shapes."""
from __future__ import annotations

import json
import re
from pathlib import Path

API_PATH = Path(__file__).resolve().parents[3] / "docs/api/api-contracts-v0.1.md"
MODES = {"CONTINUE", "EXPLORE", "CREATE", "SURPRISE", "REVISIT"}
BANDS = {"COMFORT", "ADJACENT", "FRONTIER", "WILD"}


def _json_blocks(section: str) -> list[dict]:
    document = API_PATH.read_text(encoding="utf-8")
    after_heading = document.split(section, 1)[1]
    body = after_heading.split("\n### ", 1)[0]
    return [json.loads(raw) for raw in re.findall(r"```json\n(.*?)\n```", body, re.S)]


def test_next_command_and_empty_result_match_frozen_shapes():
    request, empty = _json_blocks("### `POST /api/v1/recommendations/next`")
    assert set(request) == {"mode", "available_minutes", "practical_context"}
    assert request["mode"] in MODES
    assert request["available_minutes"] > 0
    assert empty == {"recommendation": None}


def test_single_recommendation_and_decision_shapes():
    [recommendation] = _json_blocks("### Recommendation")
    assert set(recommendation) == {
        "id", "target_type", "entity", "practical_challenge", "mode",
        "distance_band", "hook", "reason", "presented_at",
    }
    assert recommendation["target_type"] == "LEARNING_ENTITY"
    assert recommendation["mode"] in MODES
    assert recommendation["distance_band"] in BANDS
    accept, skip = _json_blocks(
        "### `POST /api/v1/recommendations/{recommendation_id}/decision`"
    )
    assert accept == {"decision": "ACCEPT"}
    assert skip["decision"] == "SKIP"
    assert set(skip) == {"decision", "reason"}
