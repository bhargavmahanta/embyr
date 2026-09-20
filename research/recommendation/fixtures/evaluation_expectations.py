"""#49-level evaluation expectations for the M3 fixture corpus (m3-simulation/v5).

Issue #49 freezes the executable ``SimulationResult`` population, ``top_k``
selection, descriptive metrics, and invariant evaluation. This module exposes the
#49-level oracles the fixture harness must satisfy, derived from the existing
#46/#47/#48 expectation manifests so the earlier-stage claims are never
duplicated.

It contains metadata only. It never enters ``SimulationInput`` and is never part
of a fingerprint.
"""

from __future__ import annotations

from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.fixtures.ids import SCENARIO_IDS
from research.recommendation.fixtures.scenarios import SCENARIOS

CONTRACT_VERSION = "m3-simulation/v5"

#: Frozen descriptive metric vocabulary (§20). Every SimulationResult carries all
#: thirteen keys, even when a metric is empty or zero.
METRIC_KEYS = (
    "candidate_count",
    "eligible_candidate_count",
    "exclusion_count_by_reason",
    "source_coverage",
    "top_k_source_mix",
    "topic_domain_diversity",
    "difficulty_distribution",
    "explicit_interest_coverage",
    "semantic_candidate_coverage",
    "revisit_share",
    "continuation_share",
    "rank_change_due_to_diversity",
    "trace_completeness",
)

#: Frozen hard-invariant vocabulary and canonical order (§19). All ten are emitted
#: for every SimulationResult; no NOT_APPLICABLE status exists.
INVARIANT_CODES = tuple(f"IN-{index}" for index in range(1, 11))

#: Frozen ExclusionCode vocabulary and canonical order (§16).
EXCLUSION_KEYS = (
    "PREREQUISITE_UNMET",
    "EXPLICITLY_PAUSED",
    "NOT_INTERESTED",
    "INVALID_TARGET",
    "INSUFFICIENT_STATE",
)

#: Frozen CandidateSource vocabulary and canonical order (§8).
SOURCE_KEYS = (
    "GRAPH",
    "SEMANTIC",
    "EXPLICIT_INTEREST",
    "HISTORY_CONTINUATION",
    "REVISIT",
)

#: Frozen #49 selection semantics (§17.1).
TOP_K_SELECTION = "PREFIX_MIN_CLIP"
NON_SELECTED_RETENTION = "DROPPED"
METRICS_GATING = "DESCRIPTIVE_ONLY"
INVARIANT_FAILURE_BEHAVIOR = "RETURN_FAIL"

#: Frozen harness shapes (§20.3).
SCENARIO_EVALUATION_FIELDS = (
    "scenario_id",
    "status",
    "simulation_result",
    "expectation_failures",
)
EXPECTATION_FAILURE_FIELDS = ("check", "expected", "actual")
EVALUATION_REPORT_FIELDS = (
    "contract_version",
    "status",
    "scenario_count",
    "passed_count",
    "failed_count",
    "scenario_evaluations",
)

#: Generic engine functions and fixture-harness functions owned by #49 (§20.3).
ENGINE_API = ("run_simulation",)
HARNESS_API = ("evaluate_scenario", "run_fixture_suite", "render_evaluation_summary")


def _target_key(descriptor: dict) -> tuple[str, int, str]:
    return (
        descriptor["entity_id"],
        descriptor["entity_version"],
        descriptor["entity_type"],
    )


def _scenario_expectation(scenario_id: str) -> dict:
    manifest = EXPECTATIONS[scenario_id]
    selected: list[tuple[str, int, str]] = []
    excluded: list[tuple[tuple[str, int, str], tuple[str, ...]]] = []
    empty_result_is_valid = False
    for expectation in manifest["hard_expectations"]:
        target = expectation.get("target")
        if target is None:
            if expectation.get("empty_result_is_valid"):
                empty_result_is_valid = True
            continue
        key = _target_key(target)
        state = expectation.get("eligibility_state")
        if state == "ELIGIBLE":
            selected.append(key)
        elif state == "INELIGIBLE":
            excluded.append((key, tuple(expectation.get("exclusion_reasons", ()))))
    return {
        "scenario_id": scenario_id,
        "expected_selected_targets": selected,
        "expected_excluded_targets": excluded,
        "empty_result_is_valid": empty_result_is_valid,
        "invariants_evaluated": list(INVARIANT_CODES),
        "invariants_exercised": list(manifest["invariants_exercised"]),
        "descriptive_metrics": list(manifest["descriptive_observations"]),
        "top_k": SCENARIOS[scenario_id]["simulation_config"]["top_k"],
    }


#: ``scenario_id -> #49 evaluation expectation`` in canonical fixture order.
EVALUATION_EXPECTATIONS: dict[str, dict] = {
    scenario_id: _scenario_expectation(scenario_id) for scenario_id in SCENARIO_IDS
}
