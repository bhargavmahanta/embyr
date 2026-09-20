"""#49 invariant evaluation: PASS/FAIL outcomes, ordering, non-raising behavior."""

from __future__ import annotations

import copy

from research.recommendation.simulator.invariants import (
    INVARIANT_CODES,
    evaluate_invariants,
    scan_source,
)
from research.recommendation.tests._runner_helpers import (
    candidate,
    core,
    explanation,
    hard_prerequisite,
    ranked,
)


def _by_code(results: list[dict]) -> dict[str, dict]:
    return {entry["invariant_code"]: entry for entry in results}


def _valid_core():
    considered = [candidate("c1", "e1")]
    full_ranked = [ranked("c1", "e1", rank=1)]
    explanations = [explanation("c1", "e1", rank=1)]
    return core(
        considered,
        full_ranked=full_ranked,
        explanations=explanations,
        selected=explanations,
    )


def test_all_invariants_pass_on_consistent_core():
    first = _valid_core()
    second = copy.deepcopy(first)
    results = evaluate_invariants(first, second)
    assert [entry["invariant_code"] for entry in results] == list(INVARIANT_CODES)
    assert {entry["status"] for entry in results} == {"PASS"}


def test_invariant_diagnostics_are_deterministic():
    first = _valid_core()
    second = copy.deepcopy(first)
    assert evaluate_invariants(first, second) == evaluate_invariants(first, second)


def test_invariants_never_raise_on_corruption():
    considered = [candidate("c1", "e1", eligibility="INELIGIBLE", exclusion_reasons=())]
    broken = core(considered, explanations=[explanation("c1", "e1")])
    results = evaluate_invariants(broken, copy.deepcopy(broken))
    assert len(results) == 10


def test_in1_fails_when_second_execution_differs():
    first = _valid_core()
    second = copy.deepcopy(first)
    second.metrics = dict(second.metrics)
    second.metrics["candidate_count"] = 99
    result = _by_code(evaluate_invariants(first, second))["IN-1"]
    assert result["status"] == "FAIL"
    assert result["diagnostics"]["logical_equal"] is False


def test_in2_fails_when_selected_is_ineligible():
    considered = [
        candidate("c1", "e1", eligibility="INELIGIBLE", exclusion_reasons=["NOT_INTERESTED"])
    ]
    broken = core(considered, explanations=[explanation("c1", "e1")])
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-2"]["status"] == "FAIL"


def test_in3_fails_on_unsatisfied_and_unknown_hard_prerequisites():
    for state in ("UNSATISFIED", "UNKNOWN"):
        considered = [
            candidate("c1", "e1", prerequisite_evaluations=(hard_prerequisite(state),))
        ]
        broken = core(considered, explanations=[explanation("c1", "e1")])
        assert (
            _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-3"]["status"]
            == "FAIL"
        ), state


def test_in4_fails_when_conflict_not_suppressed_and_mapped():
    considered = [candidate("c1", "e1")]
    conflict = explanation("c1", "e1", conflict=True, explanation_codes=())
    broken = core(considered, explanations=[conflict])
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-4"]["status"] == "FAIL"


def test_in4_passes_when_conflict_suppressed_and_mapped():
    considered = [candidate("c1", "e1")]
    conflict = explanation(
        "c1",
        "e1",
        conflict=True,
        explanation_codes=["EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"],
    )
    ok = core(considered, explanations=[conflict])
    assert _by_code(evaluate_invariants(ok, copy.deepcopy(ok)))["IN-4"]["status"] == "PASS"


def test_in5_fails_when_selected_trace_incomplete():
    considered = [candidate("c1", "e1")]
    incomplete = explanation("c1", "e1")
    del incomplete["ordering_score"]
    broken = core(considered, explanations=[incomplete])
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-5"]["status"] == "FAIL"


def test_in5_passes_for_empty_selected():
    broken = core([], explanations=[])
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-5"]["status"] == "PASS"


def test_in6_fails_when_ineligible_has_no_reason():
    considered = [candidate("c1", "e1", eligibility="INELIGIBLE", exclusion_reasons=())]
    broken = core(considered)
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-6"]["status"] == "FAIL"


def test_in6_fails_on_unknown_reason_vocabulary():
    considered = [
        candidate("c1", "e1", eligibility="INELIGIBLE", exclusion_reasons=["NOT_A_REASON"])
    ]
    broken = core(considered)
    result = _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-6"]
    assert result["status"] == "FAIL"


def test_in7_fails_on_non_contiguous_ranks():
    considered = [candidate("c1", "e1")]
    broken = core(
        considered,
        full_ranked=[ranked("c1", "e1", rank=2)],
        explanations=[explanation("c1", "e1", rank=2)],
    )
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-7"]["status"] == "FAIL"


def test_in8_fails_on_duplicate_final_targets():
    considered = [candidate("c1", "e1"), candidate("c2", "e1")]
    broken = core(
        considered,
        full_ranked=[ranked("c1", "e1", rank=1), ranked("c2", "e1", rank=2)],
    )
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-8"]["status"] == "FAIL"


def test_in10_fails_when_no_eligible_but_selected_non_empty():
    considered = [
        candidate("c1", "e1", eligibility="INELIGIBLE", exclusion_reasons=["NOT_INTERESTED"])
    ]
    broken = core(considered, explanations=[explanation("c1", "e1")], eligible_count=0)
    assert _by_code(evaluate_invariants(broken, copy.deepcopy(broken)))["IN-10"]["status"] == "FAIL"


def test_in9_scan_source_flags_forbidden_import_and_call():
    assert scan_source("import requests\n", "bad.py") == ["bad.py:import:requests"]
    findings = scan_source("import datetime\ndatetime.datetime.now()\n", "bad.py")
    assert "bad.py:attr:now" in findings
    assert scan_source("import json\nvalue = json.dumps({})\n", "ok.py") == []
