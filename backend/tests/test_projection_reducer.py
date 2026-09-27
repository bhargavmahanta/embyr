"""Receipt-only semantic contracts: no database, clock or scheduling inputs."""

import json
from copy import deepcopy
from pathlib import Path
from uuid import UUID

import pytest

U = "11111111-1111-4111-8111-111111111111"
E = "22222222-2222-4222-8222-222222222222"
X = "33333333-3333-4333-8333-333333333333"
O = "44444444-4444-4444-8444-444444444444"
T = "2026-01-01T00:00:00Z"


def receipt(
    n, *, event="EXPLORATION_STARTED", version=1, exploration=X, time=T, group=None
):
    facts = dict.fromkeys(
        [
            "event_id",
            "event_type",
            "source_schema_version",
            "entity_id",
            "entity_version",
            "exploration_id",
            "assessment_session_id",
            "response_id",
            "evaluation_run_id",
            "reflection_id",
            "recommendation_id",
            "command_id",
            "event_ordinal",
            "preference",
            "preference_version",
        ]
    )
    facts.update(
        event_id=str(UUID(int=n)),
        event_type=event,
        source_schema_version=1,
        entity_id=E,
        entity_version=version,
        exploration_id=exploration,
    )
    if event == "ONBOARDING_COMPLETED":
        facts.update(
            entity_id=None,
            entity_version=None,
            exploration_id=None,
            preference_version=1,
        )
    if event in {"REFLECTION_SUBMITTED", "REFLECTION_UPDATED"}:
        facts["reflection_id"] = str(UUID(int=100 + n))
    if event == "RECOMMENDATION_ACCEPTED":
        facts["recommendation_id"] = str(UUID(int=200 + n))
    return {
        "contract_version": "projection-input/v1",
        "schema_version": 1,
        "user_id": U,
        "source_sequence": n,
        "source_kind": "LEDGER",
        "source_key": facts["event_id"],
        "source_group": group or str(n),
        "source_time": time,
        "facts": facts,
    }


def evidence(
    n,
    *,
    response=10,
    evid=20,
    run=30,
    objective=O,
    status="ACTIVE",
    result="SUPPORTED",
    confidence=0.8,
    support=None,
    version=1,
    group=None,
    time=T,
):
    f = {
        "evidence_id": str(UUID(int=evid)),
        "resulting_status": status,
        "source_type": "ASSESSMENT_RESPONSE",
        "source_id": str(UUID(int=response)),
        "evidence_type": "RECOGNITION",
        "evidence_strength": "WEAK",
        "objective_id": objective,
        "entity_id": E,
        "entity_version": version,
        "response_id": str(UUID(int=response)),
        "evaluation_run_id": str(UUID(int=run)),
        "evaluation_status": "SUCCEEDED",
        "evaluation_result": result,
        "evaluator_version": "deterministic-evaluation/v1",
        "rubric_version": "1",
        "support_level": support,
        "classification_confidence": confidence,
        "transition_at": None,
    }
    return {
        "contract_version": "projection-input/v1",
        "schema_version": 1,
        "user_id": U,
        "source_sequence": n,
        "source_kind": "EVIDENCE",
        "source_key": f"{f['evidence_id']}:{status}",
        "source_group": group or str(n),
        "source_time": time,
        "facts": f,
    }


def reduce(rows):
    from app.learning.projection_reducer import reduce_prefix

    return reduce_prefix(U, rows)


def test_empty_prefix_has_no_invented_world_or_objective():
    out = reduce([])
    assert out.objectives == [] and out.nodes == [] and not out.root


def test_supported_weak_recognition_uses_exact_min_any_max_and_provenance():
    out = reduce(
        [
            receipt(1),
            evidence(2),
            evidence(
                3,
                response=11,
                evid=21,
                run=31,
                confidence=0.6,
                support="EXPLANATION",
                time="2026-01-02T00:00:00Z",
            ),
        ]
    )
    assert out.objectives == [
        {
            "objective_id": O,
            "categorical_state": "DEVELOPING",
            "understanding_estimate": None,
            "evidence_count": 2,
            "evaluation_confidence": 0.6,
            "support_required": True,
            "last_evidence_at": "2026-01-02T00:00:00Z",
            "model_version": "learner-projection/v1",
        }
    ]
    assert out.provenance == [(O, str(UUID(int=20))), (O, str(UUID(int=21)))]
    assert out.nodes[0]["growth_state"] == "YOUNG"


@pytest.mark.parametrize("result", ["INSUFFICIENT_EVIDENCE", "UNCERTAIN", "FAILED"])
def test_ineligible_result_cannot_promote(result):
    row = evidence(2, result=result)
    if result == "FAILED":
        row["facts"].update(
            evaluation_status="FAILED",
            evaluation_result=None,
            classification_confidence=None,
        )
    assert reduce([receipt(1), row]).objectives == []
    assert reduce([receipt(1), row]).nodes[0]["growth_state"] == "SEED"


@pytest.mark.parametrize("status", ["SUPERSEDED", "REVOKED"])
def test_retired_evidence_removes_objective_and_can_regress_only_growth(status):
    rows = [receipt(1), evidence(2), evidence(3, status=status)]
    out = reduce(rows)
    assert out.objectives == [] and out.provenance == []
    assert out.nodes[0]["growth_state"] == "SEED"


def test_sequence_wins_crossed_time_and_equal_time_without_uuid_tie_break():
    a = receipt(1, time="2026-02-01T00:00:00Z")
    b = receipt(2, exploration=str(UUID(int=1)), version=2, time=T)
    assert reduce([a, b]).nodes[0]["entity_version"] == 1
    b["source_time"] = a["source_time"]
    assert reduce([a, b]).nodes[0]["entity_version"] == 1


def test_accept_start_is_one_encounter_and_duplicate_start_is_integrity_failure():
    assert (
        len(reduce([receipt(1, event="RECOMMENDATION_ACCEPTED"), receipt(2)]).nodes)
        == 1
    )
    from app.learning.projection_reducer import ProjectionError

    with pytest.raises(ProjectionError, match="DUPLICATE_START"):
        reduce([receipt(1), receipt(2)])


def test_other_version_evidence_does_not_grow_pin():
    out = reduce(
        [
            receipt(1),
            receipt(2, version=2, exploration=str(UUID(int=2))),
            evidence(3, version=2),
        ]
    )
    assert out.objectives[0]["categorical_state"] == "DEVELOPING"
    assert (
        out.nodes[0]["entity_version"] == 1 and out.nodes[0]["growth_state"] == "SEED"
    )


@pytest.mark.parametrize(
    "event,want",
    [
        ("REFLECTION_SUBMITTED", "SPROUT"),
        ("EXPLORATION_COMPLETED", "SPROUT"),
        ("USER_RETURNED", "SEED"),
        ("EXPLORATION_PAUSED", "SEED"),
        ("EXPLORATION_RESUMED", "SEED"),
        ("EXPLORATION_WORK_PREPARED", "SEED"),
        ("REFLECTION_UPDATED", "SEED"),
    ],
)
def test_growth_has_only_frozen_factual_authority(event, want):
    assert (
        reduce([receipt(1), receipt(2, event=event)]).nodes[0]["growth_state"] == want
    )


def test_equivalent_same_group_replacement_retains_semantics():
    first = reduce([receipt(1), evidence(2)])
    after = reduce(
        [
            receipt(1),
            evidence(2),
            evidence(3, status="SUPERSEDED", group="3"),
            evidence(4, evid=21, run=31, group="3"),
        ]
    )
    assert first.nodes == after.nodes
    assert after.provenance == [(O, str(UUID(int=21)))]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda r: r.update(source_sequence=3),
        lambda r: r.update(user_id=str(UUID(int=2))),
        lambda r: r["facts"].update(private="secret"),
        lambda r: r["facts"].update(event_type="UNKNOWN"),
        lambda r: r.update(source_key=str(UUID(int=999))),
    ],
)
def test_malformed_prefix_fails_closed(mutation):
    row = receipt(1)
    mutation(row)
    from app.learning.projection_reducer import ProjectionError

    with pytest.raises(ProjectionError):
        reduce([row])


def test_duplicate_eligible_response_is_integrity_failure():
    from app.learning.projection_reducer import ProjectionError

    with pytest.raises(ProjectionError, match="DUPLICATE_RESPONSE"):
        reduce([receipt(1), evidence(2), evidence(3, evid=21, run=31)])


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -0.1, 1.1])
def test_invalid_confidence_never_reaches_fingerprints(value):
    from app.learning.projection_reducer import ProjectionError

    with pytest.raises(ProjectionError):
        reduce([receipt(1), evidence(2, confidence=value)])


def test_dictionary_order_cannot_change_fingerprints_or_mutate_input():
    rows = [receipt(1), evidence(2)]
    saved = deepcopy(rows)
    a = reduce(rows)
    for r in rows:
        r["facts"] = dict(reversed(list(r["facts"].items())))
    b = reduce(rows)
    assert (
        a.input_fingerprint == b.input_fingerprint
        and a.output_fingerprint == b.output_fingerprint
    )
    assert rows == saved


def test_world_identity_and_coordinates_match_frozen_fixture():
    from app.learning.world_projection import (
        node_object,
        region_object,
        world_id,
        world_seed,
    )

    f = json.loads(
        (Path(__file__).parents[2] / "docs/api/fixtures/m6-v1.json").read_text()
    )
    snapshot = f["public_examples"]["world_populated"]
    user = f["identity_example"]["user_id"]
    node = snapshot["nodes"][0]
    assert str(world_id(user)) == f["identity_example"]["world_id"]
    assert world_seed(f["identity_example"]["world_id"]) == snapshot["generation_seed"]
    assert region_object(user) == snapshot["regions"][0]
    assert (
        node_object(
            user,
            node["entity_id"],
            node["entity_version"],
            node["growth_state"],
            node["revision"],
        )
        == node
    )
