"""Hard-invariant evaluation for simulation results (#49, m3-simulation/v5).

Evaluates IN-1..IN-10 as outcome checks over data already produced by #46/#47/#48
(§19.1). It never reimplements candidate generation, eligibility, scoring,
reranking, or explanation derivation, and it never raises on invariant failure:
failures are returned as ``FAIL`` diagnostics (§19.2). All ten invariants are
always emitted in canonical order.
"""

from __future__ import annotations

import ast
from pathlib import Path

from .eligibility import EXCLUSION_ORDER
from .identity import canonical_json
from .metrics import result_is_trace_complete

PASS = "PASS"
FAIL = "FAIL"

#: Frozen invariant vocabulary and canonical order (§19).
INVARIANT_CODES = tuple(f"IN-{index}" for index in range(1, 11))

_SIMULATOR_DIR = Path(__file__).resolve().parent

#: Frozen offline/determinism policy reused from the recommendation offline tests.
FORBIDDEN_MODULE_ROOTS = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "http",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "supabase",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "asyncpg",
        "storage3",
        "openai",
        "anthropic",
        "boto3",
        "google",
        "testcontainers",
    }
)
FORBIDDEN_ATTRIBUTES = frozenset(
    {
        "now",
        "today",
        "utcnow",
        "time",
        "monotonic",
        "urandom",
        "getrandbits",
        "random",
        "randint",
        "randrange",
        "choice",
        "shuffle",
        "sample",
        "uuid4",
        "uuid1",
        "token_hex",
        "token_bytes",
    }
)


def _result(code: str, passed: bool, diagnostics: dict) -> dict:
    return {
        "invariant_code": code,
        "status": PASS if passed else FAIL,
        "diagnostics": diagnostics,
    }


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def _nondeterministic_attributes(tree: ast.AST) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES
    }


def scan_source(source: str, filename: str = "<source>") -> list[str]:
    """Return deterministic forbidden findings for one Python source string.

    Pure parser helper: performs no network, filesystem, or model access.
    """
    tree = ast.parse(source)
    findings = [
        f"{filename}:import:{root}"
        for root in sorted(_import_roots(tree) & FORBIDDEN_MODULE_ROOTS)
    ]
    findings.extend(
        f"{filename}:attr:{attr}"
        for attr in sorted(_nondeterministic_attributes(tree))
    )
    return sorted(findings)


def _scan_simulator_modules() -> list[str]:
    findings: list[str] = []
    for path in sorted(_SIMULATOR_DIR.glob("*.py")):
        findings.extend(scan_source(path.read_text(encoding="utf-8"), path.name))
    return sorted(findings)


def _candidate_by_id(considered: list[dict]) -> dict[str, dict]:
    return {candidate["candidate_id"]: candidate for candidate in considered}


def _in1(core, second) -> dict:
    keys = (
        "candidates_considered",
        "candidates_excluded",
        "ranked_recommendations",
        "metrics",
    )
    payload = {
        "candidates_considered": core.candidates_considered,
        "candidates_excluded": core.candidates_excluded,
        "ranked_recommendations": core.selected_recommendations,
        "metrics": core.metrics,
    }
    payload_second = {
        "candidates_considered": second.candidates_considered,
        "candidates_excluded": second.candidates_excluded,
        "ranked_recommendations": second.selected_recommendations,
        "metrics": second.metrics,
    }
    equal = canonical_json(payload) == canonical_json(payload_second)
    return _result("IN-1", equal, {"logical_equal": equal})


def _in2(core) -> dict:
    by_id = _candidate_by_id(core.candidates_considered)
    offenders = sorted(
        result["candidate_id"]
        for result in core.selected_recommendations
        if by_id.get(result["candidate_id"], {}).get("eligibility_state") != "ELIGIBLE"
    )
    return _result("IN-2", not offenders, {"ineligible_selected": offenders})


def _in3(core) -> dict:
    by_id = _candidate_by_id(core.candidates_considered)
    offenders: list[str] = []
    for result in core.selected_recommendations:
        candidate = by_id.get(result["candidate_id"])
        if candidate is None:
            continue
        for evaluation in candidate["prerequisite_evaluations"]:
            if evaluation["requirement"] == "HARD" and evaluation["state"] in (
                "UNSATISFIED",
                "UNKNOWN",
            ):
                offenders.append(result["candidate_id"])
                break
    offenders = sorted(set(offenders))
    return _result("IN-3", not offenders, {"hard_prerequisite_violations": offenders})


def _conflict_ids(execution) -> list[str]:
    conflict_reason = "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"
    return sorted(
        result["candidate_id"]
        for result in execution.full_recommendation_results
        if conflict_reason in result["score_trace"]["reason_codes"]
    )


def _in4(core, second) -> dict:
    conflict_reason = "EXPLICIT_INFERRED_CONFLICT_SUPPRESSED"
    override_code = "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED"
    violations: list[str] = []
    for result in core.full_recommendation_results:
        if conflict_reason not in result["score_trace"]["reason_codes"]:
            continue
        suppressed = (
            result["score_trace"]["component_scores"]["inferred_interest"] == 0.0
        )
        mapped = override_code in result["explanation_codes"]
        if not (suppressed and mapped):
            violations.append(result["candidate_id"])
    violations = sorted(set(violations))
    deterministic = _conflict_ids(core) == _conflict_ids(second)
    return _result(
        "IN-4",
        not violations and deterministic,
        {
            "conflict_violations": violations,
            "conflict_state_deterministic": deterministic,
        },
    )


def _in5(core) -> dict:
    if not core.selected_recommendations:
        return _result("IN-5", True, {"traces_incomplete": 0})
    by_id = _candidate_by_id(core.candidates_considered)
    incomplete = sorted(
        result["candidate_id"]
        for result in core.selected_recommendations
        if not result_is_trace_complete(result, by_id)
    )
    return _result(
        "IN-5",
        not incomplete,
        {"traces_incomplete": len(incomplete), "incomplete": incomplete},
    )


def _in6(core) -> dict:
    vocabulary = set(EXCLUSION_ORDER)
    invalid: list[str] = []
    without_reason = 0
    for candidate in core.candidates_considered:
        if candidate["eligibility_state"] != "INELIGIBLE":
            continue
        reasons = candidate["exclusion_reasons"]
        if not reasons:
            without_reason += 1
            invalid.append(candidate["candidate_id"])
            continue
        if any(reason not in vocabulary for reason in reasons):
            invalid.append(candidate["candidate_id"])
    invalid = sorted(set(invalid))
    return _result(
        "IN-6",
        not invalid,
        {
            "exclusions_without_reason": without_reason,
            "invalid_exclusions": invalid,
        },
    )


def _in7(core) -> dict:
    ranks = [entry["final_rank"] for entry in core.full_ranked_candidates]
    expected = list(range(1, len(ranks) + 1))
    selected_ranks = [result["final_rank"] for result in core.selected_recommendations]
    prefix_ok = selected_ranks == list(range(1, len(selected_ranks) + 1))
    return _result("IN-7", ranks == expected and prefix_ok, {"ranks": ranks})


def _in8(core) -> dict:
    keys = [
        (entry["target_entity_id"], entry["target_entity_version"])
        for entry in core.full_ranked_candidates
    ]
    duplicates = len(keys) - len(set(keys))
    return _result("IN-8", duplicates == 0, {"duplicate_targets": duplicates})


def _in9() -> dict:
    findings = _scan_simulator_modules()
    if findings:
        return _result(
            "IN-9",
            False,
            {"external_calls": len(findings), "findings": findings},
        )
    return _result("IN-9", True, {"external_calls": 0})


def _in10(core) -> dict:
    eligible = sum(
        1
        for candidate in core.candidates_considered
        if candidate["eligibility_state"] == "ELIGIBLE"
    )
    empty = core.selected_recommendations == []
    passed = eligible > 0 or empty
    return _result(
        "IN-10",
        passed,
        {"eligible_candidate_count": eligible, "empty_recommendations": empty},
    )


def evaluate_invariants(core, second) -> list[dict]:
    """Return all ten invariant results in canonical order (§19.1, §19.2).

    ``core`` is the first core execution; ``second`` is an independent second
    execution used only by IN-1/IN-4 determinism checks. Invariant failure never
    raises.
    """
    return [
        _in1(core, second),
        _in2(core),
        _in3(core),
        _in4(core, second),
        _in5(core),
        _in6(core),
        _in7(core),
        _in8(core),
        _in9(),
        _in10(core),
    ]
