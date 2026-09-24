"""The first production ranking profile is a versioned M4 contract artifact."""
from __future__ import annotations

import json
import math
from pathlib import Path

from research.recommendation.simulator.validation import SCORING_FEATURE_SET

PROFILE_PATH = (
    Path(__file__).resolve().parents[3]
    / "backend"
    / "app"
    / "recommendation"
    / "profiles"
    / "recommendation-profile-v1.json"
)


def test_initial_profile_matches_owner_reviewed_m3_feature_contract():
    profile = json.loads(PROFILE_PATH.read_text(encoding="utf-8"))

    assert profile["profile_version"] == "recommendation-profile/v1"
    assert profile["semantic_contract"] == "m3-simulation/v5"
    assert profile["top_k"] == 1
    assert set(profile["feature_weights"]) == SCORING_FEATURE_SET
    assert profile["feature_weights"] == {
        "readiness": 0.14,
        "difficulty_fit": 0.18,
        "explicit_interest": 0.22,
        "inferred_interest": 0.08,
        "graph_proximity": 0.12,
        "semantic_similarity": 0.14,
        "continuation_value": 0.07,
        "revisit_value": 0.05,
    }
    assert all(
        math.isfinite(value) and value >= 0
        for value in profile["feature_weights"].values()
    )
    assert profile["rerank"] == {
        "strategy": "DOMAIN_COVERAGE",
        "diversity_weight": 0.08,
    }
