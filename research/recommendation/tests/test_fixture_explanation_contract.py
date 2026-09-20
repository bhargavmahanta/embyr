"""Contract + fixture integrity for the m3-simulation/v4 explanation freeze (#48).

Phase A is contract/fixture-only: this module validates the frozen explanation
vocabulary, canonical ordering, cardinality, emission-rule wording, the #48
public API, and the migrated exact fixture explanation oracles. It does **not**
exercise a runtime explanation emitter (that is #48 implementation work).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from research.recommendation.fixtures import SCENARIO_TARGETS, SCENARIOS
from research.recommendation.fixtures.builders import EXPLANATION_CODES
from research.recommendation.fixtures.expectations import EXPECTATIONS

CONTRACT_PATH = Path(__file__).resolve().parents[1] / "simulation-contract-v0.1.md"

CANONICAL_INDEX = {code: index for index, code in enumerate(EXPLANATION_CODES)}

EXPECTED_VOCABULARY = (
    "EXPLICIT_INTEREST_MATCH",
    "RELATED_TO_RECENT_EXPLORATION",
    "PREREQUISITES_SATISFIED",
    "GOOD_DIFFICULTY_FIT",
    "SEMANTICALLY_RELATED",
    "REVISIT_OPPORTUNITY",
    "DIVERSITY_ADJUSTMENT",
    "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
)


def _contract_text() -> str:
    return CONTRACT_PATH.read_text(encoding="utf-8")


def _flat_text() -> str:
    return re.sub(r"\s+", " ", _contract_text())


def _json_examples() -> list[str]:
    return re.findall(r"```json\n(.*?)\n```", _contract_text(), flags=re.DOTALL)


def _explanation_entries() -> list[tuple[str, str | None, list[str]]]:
    entries: list[tuple[str, str | None, list[str]]] = []
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["hard_expectations"]:
            if "explanation_codes" not in expectation:
                continue
            target = expectation.get("target")
            target_name = None
            if target is not None:
                for name, descriptor in SCENARIO_TARGETS[scenario_id].items():
                    if descriptor == target:
                        target_name = name
                        break
            entries.append((scenario_id, target_name, expectation["explanation_codes"]))
    return entries


def test_vocabulary_is_exactly_the_eight_frozen_codes_in_order():
    assert EXPLANATION_CODES == EXPECTED_VOCABULARY
    assert len(EXPLANATION_CODES) == 8


def test_contract_freezes_explanation_model_as_contextual():
    text = _contract_text()
    assert "contextual, not strictly rank-causal" in text
    assert "configured_weights" in text
    assert "component_scores" in text


def test_contract_freezes_cardinality_zero_to_eight():
    text = _contract_text()
    assert "Cardinality is `0..8`" in text
    assert "empty `explanation_codes` list is valid" in text
    assert "MUST NOT fabricate a generic code" in text
    assert "Every final recommendation must carry at least one explanation code" not in text


def test_contract_forbids_fallback_codes():
    text = _contract_text()
    assert "No other explanation code is permitted" in text
    for forbidden in ("GENERIC_RECOMMENDATION", "INFERRED_INTEREST_MATCH", "GRAPH_RELATED"):
        assert forbidden not in text, forbidden


def test_contract_freezes_canonical_order_and_dedupe():
    text = _contract_text()
    assert "Emit all applicable codes" in text
    assert "deduplicate" in text
    assert "no top-N cap" in text
    assert "MUST NOT be alphabetically sorted" in text


def test_contract_freezes_all_eight_emission_rules():
    text = _contract_text()
    for phrase in (
        "iff fv.explicit_interest > 0.0",
        "score_trace.reason_codes contains EXPLICIT_INFERRED_CONFLICT_SUPPRESSED",
        "readiness_summary.hard_prerequisites_total > 0",
        "iff fv.difficulty_fit >= 0.8",
        "iff fv.semantic_similarity > 0.0",
        "iff candidate_sources contains HISTORY_CONTINUATION",
        "iff candidate_sources contains REVISIT",
        "rerank_trace.reason_codes contains DOMAIN_COVERAGE_ADJUSTMENT",
    ):
        assert phrase in text, phrase


def test_contract_states_recent_label_has_no_time_threshold():
    text = _flat_text()
    assert "no wall-clock threshold" in text
    assert "elapsed-time condition" in text


def test_contract_freezes_public_api_and_decision_trace_ownership():
    text = _flat_text()
    assert "build_recommendation_results(ranked_candidates: list[dict]) -> list[dict]" in text
    assert "No new `DecisionTrace` schema is introduced" in text
    assert "duplicated into `RecommendationResult`" in text


def test_contract_places_human_readable_explanation_out_of_48():
    text = _contract_text()
    assert "not part of #48" in text
    assert "template rendering" in text


def test_contract_recommendation_result_block_lists_exact_ranked_fields():
    text = _contract_text()
    block = re.search(
        r"RecommendationResult\n(.*?)\n```", text, flags=re.DOTALL
    )
    assert block, "RecommendationResult block missing"
    fields = re.findall(r"^- (\w+)", block.group(1), flags=re.MULTILINE)
    assert fields == [
        "candidate_id",
        "target_entity_id",
        "target_entity_version",
        "target_entity_type",
        "candidate_sources",
        "readiness_summary",
        "score_trace",
        "rerank_trace",
        "ordering_score",
        "deterministic_tiebreak_key",
        "final_rank",
        "explanation_codes",
    ]


def test_contract_json_examples_still_parse_and_count_is_seven():
    examples = _json_examples()
    assert len(examples) == 7
    for raw in examples:
        json.loads(raw)


def test_contract_multi_code_and_empty_code_examples_exist():
    examples = [json.loads(raw) for raw in _json_examples()]
    code_lists: list[list[str]] = []

    def _collect(value):
        if isinstance(value, dict):
            codes = value.get("explanation_codes")
            if isinstance(codes, list):
                code_lists.append(codes)
            for child in value.values():
                _collect(child)
        elif isinstance(value, list):
            for child in value:
                _collect(child)

    for example in examples:
        _collect(example)
    assert any(len(codes) > 1 for codes in code_lists)
    assert any(codes == [] for codes in code_lists)


RECOMMENDATION_RESULT_FIELDS = {
    "candidate_id",
    "target_entity_id",
    "target_entity_version",
    "target_entity_type",
    "candidate_sources",
    "readiness_summary",
    "score_trace",
    "rerank_trace",
    "ordering_score",
    "deterministic_tiebreak_key",
    "final_rank",
    "explanation_codes",
}


def _recommendation_results(value):
    if isinstance(value, dict):
        if {"explanation_codes", "score_trace", "rerank_trace", "final_rank"} <= set(value):
            yield value
        for child in value.values():
            yield from _recommendation_results(child)
    elif isinstance(value, list):
        for child in value:
            yield from _recommendation_results(child)


def test_contract_recommendation_result_examples_are_schema_consistent():
    examples = [json.loads(raw) for raw in _json_examples()]
    results = [entry for example in examples for entry in _recommendation_results(example)]
    assert results, "expected RecommendationResult examples"
    for result in results:
        assert set(result) == RECOMMENDATION_RESULT_FIELDS
        codes = result["explanation_codes"]
        assert len(codes) == len(set(codes))
        for code in codes:
            assert code in CANONICAL_INDEX, code
        assert codes == sorted(codes, key=CANONICAL_INDEX.__getitem__), codes
        assert result["final_rank"] == result["rerank_trace"]["post_rerank_rank"]
        assert abs(
            result["ordering_score"]
            - (
                result["score_trace"]["pre_rerank_score"]
                + result["rerank_trace"]["diversity_adjustment"]
            )
        ) < 1e-9


def test_manifest_uses_exact_explanation_codes_not_include():
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["hard_expectations"]:
            assert "explanation_codes_include" not in expectation, scenario_id


def test_every_manifest_code_is_frozen_deduped_and_canonically_ordered():
    entries = _explanation_entries()
    assert entries, "expected migrated explanation oracles"
    for scenario_id, target_name, codes in entries:
        assert 0 <= len(codes) <= 8, (scenario_id, target_name, codes)
        assert len(codes) == len(set(codes)), (scenario_id, target_name, codes)
        for code in codes:
            assert code in CANONICAL_INDEX, (scenario_id, target_name, code)
        assert codes == sorted(codes, key=CANONICAL_INDEX.__getitem__), (
            scenario_id,
            target_name,
            codes,
        )


def test_ineligible_targets_never_carry_explanation_codes():
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["hard_expectations"]:
            if expectation.get("eligibility_state") != "INELIGIBLE":
                continue
            assert "explanation_codes" not in expectation, scenario_id


def _codes_for(scenario_id: str, name: str) -> list[str]:
    descriptor = SCENARIO_TARGETS[scenario_id][name]
    for expectation in EXPECTATIONS[scenario_id]["hard_expectations"]:
        if expectation.get("target") == descriptor:
            return expectation.get("explanation_codes", [])
    raise AssertionError(f"no explanation oracle for {scenario_id}:{name}")


def test_explicit_more_emits_match_and_less_does_not():
    assert "EXPLICIT_INTEREST_MATCH" in _codes_for("scn-A-explicit-more-001", "target")
    assert "EXPLICIT_INTEREST_MATCH" not in _codes_for("scn-B-explicit-less-001", "target")
    assert _codes_for("scn-A-explicit-more-001", "control") == [
        "GOOD_DIFFICULTY_FIT",
        "SEMANTICALLY_RELATED",
    ]


def test_conflict_targets_emit_override_code():
    assert _codes_for("scn-E-preference-conflict-001", "more_target") == [
        "EXPLICIT_INTEREST_MATCH",
        "GOOD_DIFFICULTY_FIT",
        "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
    ]
    assert _codes_for("scn-E-preference-conflict-001", "less_target") == [
        "GOOD_DIFFICULTY_FIT",
        "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
    ]


def test_prerequisite_code_requires_nonzero_hard_prerequisites():
    assert _codes_for("scn-G-prereq-satisfied-001", "target") == [
        "PREREQUISITES_SATISFIED",
        "GOOD_DIFFICULTY_FIT",
        "SEMANTICALLY_RELATED",
    ]
    assert "PREREQUISITES_SATISFIED" not in _codes_for("scn-G-prereq-satisfied-001", "control")


def test_difficulty_threshold_boundary():
    for scenario_id in (
        "scn-I-difficulty-too-low-001",
        "scn-J-difficulty-appropriate-001",
        "scn-K-difficulty-too-high-001",
    ):
        assert "GOOD_DIFFICULTY_FIT" in _codes_for(scenario_id, "appropriate")
        assert "GOOD_DIFFICULTY_FIT" not in _codes_for(scenario_id, "too_low")
        assert "GOOD_DIFFICULTY_FIT" not in _codes_for(scenario_id, "too_high")


def test_semantic_threshold_boundary():
    assert "SEMANTICALLY_RELATED" in _codes_for("scn-L-semantic-neighbor-001", "near")
    assert "SEMANTICALLY_RELATED" not in _codes_for("scn-L-semantic-neighbor-001", "far")


def test_history_revisit_and_diversity_codes():
    assert "RELATED_TO_RECENT_EXPLORATION" in _codes_for("scn-N-continuation-001", "target")
    assert "REVISIT_OPPORTUNITY" in _codes_for("scn-O-revisit-001", "target")
    assert _codes_for("scn-P-diversity-pressure-001", "spread") == [
        "SEMANTICALLY_RELATED",
        "DIVERSITY_ADJUSTMENT",
    ]
    assert "DIVERSITY_ADJUSTMENT" not in _codes_for("scn-P-diversity-pressure-001", "cluster_a")


def test_graph_only_context_has_no_dedicated_code():
    for scenario_id, manifest in EXPECTATIONS.items():
        for expectation in manifest["hard_expectations"]:
            for code in expectation.get("explanation_codes", []):
                assert "GRAPH" not in code, (scenario_id, code)
