"""m3-simulation/v3 migration integrity: generation context and objective_id.

Covers the retained Issue #46 candidate contract (explicit
``CandidateGenerationContext`` anchors and the explicit ``objective_id`` required
for ``REQUIRES`` relationships) under the v3 contract version. These are
fixture/input integrity checks, not a candidate engine.
"""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS, SCENARIO_TARGETS
from research.recommendation.fixtures.canonical import input_fingerprint
from research.recommendation.fixtures.expectations import EXPECTATIONS
from research.recommendation.fixtures.ids import SCENARIO_IDS
from research.recommendation.fixtures.semantic import VECTOR_DIMENSION

CATEGORY_T = "scn-T-no-eligible-001"
SCENARIO_E = "scn-E-preference-conflict-001"
REQUIRES_SCENARIOS = (
    "scn-F-prereq-unmet-001",
    "scn-G-prereq-satisfied-001",
    "scn-H-prereq-unknown-001",
    "scn-X1-more-unmet-prereq-001",
    "scn-X7-multi-exclusion-empty-001",
    "scn-T-no-eligible-001",
)


def _entities(snapshot: dict) -> dict[tuple[str, int], dict]:
    return {
        (entity["entity_id"], entity["entity_version"]): entity
        for entity in snapshot["ontology_snapshot"]["entities"]
    }


def _anchors(snapshot: dict) -> list[dict]:
    return snapshot["generation_context"]["anchor_entities"]


def _relationships(snapshot: dict):
    for entity in snapshot["ontology_snapshot"]["entities"]:
        for relationship in entity["relationships"]:
            yield entity, relationship


def _objective_state(
    snapshot: dict, objective_id: str, entity_id: str, entity_version: int
) -> dict | None:
    for state in snapshot["learner_state_snapshot"]["objective_states"]:
        if (
            state["objective_id"] == objective_id
            and state["entity_id"] == entity_id
            and state["entity_version"] == entity_version
        ):
            return state
    return None


def test_all_fixtures_are_v3():
    for scenario_id in SCENARIO_IDS:
        assert SCENARIOS[scenario_id]["contract_version"] == "m3-simulation/v3", scenario_id


def test_anchors_are_unique_and_canonically_sorted():
    for scenario_id, snapshot in SCENARIOS.items():
        anchors = _anchors(snapshot)
        keys = [(anchor["entity_id"], anchor["entity_version"]) for anchor in anchors]
        assert len(keys) == len(set(keys)), scenario_id
        assert keys == sorted(keys), scenario_id
        for anchor in anchors:
            assert isinstance(anchor["entity_version"], int), scenario_id


def test_anchors_resolve_in_ontology():
    for scenario_id, snapshot in SCENARIOS.items():
        entities = _entities(snapshot)
        for anchor in _anchors(snapshot):
            key = (anchor["entity_id"], anchor["entity_version"])
            assert key in entities, (scenario_id, key)


def test_anchor_mapping_is_deliberate():
    # Scenario E candidates are reachable through non-NEUTRAL explicit
    # preferences and deliberately has no generation anchor. Every other
    # scenario declares its scenario-local seed as query context.
    for scenario_id, snapshot in SCENARIOS.items():
        seed = SCENARIO_TARGETS[scenario_id]["seed"]
        anchor = {"entity_id": seed["entity_id"], "entity_version": seed["entity_version"]}
        expected = [] if scenario_id == SCENARIO_E else [anchor]
        assert _anchors(snapshot) == expected, scenario_id


def test_semantic_anchor_vectors_are_valid():
    for scenario_id, snapshot in SCENARIOS.items():
        vectors = {
            (vector["entity_id"], vector["entity_version"]): vector["vector"]
            for vector in snapshot["semantic_space"]["vectors"]
        }
        for anchor in _anchors(snapshot):
            key = (anchor["entity_id"], anchor["entity_version"])
            assert key in vectors, (scenario_id, key)
            assert len(vectors[key]) == VECTOR_DIMENSION, scenario_id


def test_anchor_is_not_an_expected_target():
    for scenario_id, manifest in EXPECTATIONS.items():
        anchor_keys = {
            (anchor["entity_id"], anchor["entity_version"])
            for anchor in _anchors(SCENARIOS[scenario_id])
        }
        descriptors = [entry.get("target") for entry in manifest["hard_expectations"]]
        for expectation in manifest["relative_expectations"]:
            descriptors.append(expectation["higher_ranked_target"])
            descriptors.append(expectation["lower_ranked_target"])
        for descriptor in descriptors:
            if descriptor is None:
                continue
            assert (descriptor["entity_id"], descriptor["entity_version"]) not in anchor_keys, (
                scenario_id,
                descriptor,
            )


def test_requires_relationships_declare_requirement_and_objective():
    for scenario_id, snapshot in SCENARIOS.items():
        for entity, relationship in _relationships(snapshot):
            if relationship["relationship_type"] == "REQUIRES":
                assert relationship["requirement"] in ("HARD", "SOFT"), scenario_id
                assert relationship["objective_id"], scenario_id
            else:
                assert relationship["requirement"] is None, scenario_id
                assert relationship["objective_id"] is None, scenario_id


def test_requires_objective_resolves_to_prerequisite_objective():
    for scenario_id, snapshot in SCENARIOS.items():
        entities = _entities(snapshot)
        for entity, relationship in _relationships(snapshot):
            if relationship["relationship_type"] != "REQUIRES":
                continue
            prerequisite = entities[
                (relationship["target_entity_id"], relationship["target_entity_version"])
            ]
            assert relationship["objective_id"] in prerequisite["objective_ids"], scenario_id


def test_prerequisite_evidence_cases():
    cases = {
        "scn-F-prereq-unmet-001": "ENCOUNTERED",
        "scn-G-prereq-satisfied-001": "UNDERSTOOD",
        "scn-H-prereq-unknown-001": None,
    }
    assert set(cases) <= set(REQUIRES_SCENARIOS)
    for scenario_id, expected_state in cases.items():
        snapshot = SCENARIOS[scenario_id]
        target = SCENARIO_TARGETS[scenario_id]["target"]
        entities = _entities(snapshot)
        entity = entities[(target["entity_id"], target["entity_version"])]
        requires = [
            relationship
            for relationship in entity["relationships"]
            if relationship["relationship_type"] == "REQUIRES"
        ]
        assert len(requires) == 1, scenario_id
        relationship = requires[0]
        state = _objective_state(
            snapshot,
            relationship["objective_id"],
            relationship["target_entity_id"],
            relationship["target_entity_version"],
        )
        if expected_state is None:
            assert state is None
        else:
            assert state is not None and state["state"] == expected_state


def test_category_t_emits_no_eligible_candidate_structurally():
    snapshot = SCENARIOS[CATEGORY_T]
    anchor_keys = {
        (anchor["entity_id"], anchor["entity_version"]) for anchor in _anchors(snapshot)
    }
    reachable = {
        (vector["entity_id"], vector["entity_version"])
        for vector in snapshot["semantic_space"]["vectors"]
    } - anchor_keys
    entities = _entities(snapshot)
    hard_excluded = {
        (preference["entity_id"], 1)
        for preference in snapshot["preference_snapshot"]["explicit_preferences"]
        if preference["preference"] in ("PAUSED", "NOT_INTERESTED")
    }
    requires = {
        key
        for key, entity in entities.items()
        if any(
            relationship["relationship_type"] == "REQUIRES"
            for relationship in entity["relationships"]
        )
    }
    assert reachable
    for key in reachable:
        assert key in hard_excluded or key in requires, key
    for expectation in EXPECTATIONS[CATEGORY_T]["hard_expectations"]:
        assert expectation.get("eligibility_state") != "ELIGIBLE"


def test_prerequisite_objective_oracles_resolve():
    oracle_scenarios = (
        "scn-F-prereq-unmet-001",
        "scn-G-prereq-satisfied-001",
        "scn-H-prereq-unknown-001",
        "scn-X1-more-unmet-prereq-001",
        "scn-X7-multi-exclusion-empty-001",
    )
    for scenario_id in oracle_scenarios:
        expectations = EXPECTATIONS[scenario_id]["hard_expectations"]
        oracles = [e["prerequisite_objective_id"] for e in expectations if "prerequisite_objective_id" in e]
        assert oracles, scenario_id
        snapshot = SCENARIOS[scenario_id]
        objective_ids = {
            objective_id
            for entity in snapshot["ontology_snapshot"]["entities"]
            for objective_id in entity["objective_ids"]
        }
        for expectation in expectations:
            oracle = expectation.get("prerequisite_objective_id")
            if oracle is None:
                continue
            assert oracle in objective_ids, (scenario_id, oracle)
            target = expectation["target"]
            declared = _declared_requires_objective(
                snapshot, target["entity_id"], target["entity_version"]
            )
            assert oracle == declared, (scenario_id, target)


def _declared_requires_objective(snapshot: dict, entity_id: str, entity_version: int):
    for entity in snapshot["ontology_snapshot"]["entities"]:
        if (entity["entity_id"], entity["entity_version"]) != (entity_id, entity_version):
            continue
        for relationship in entity["relationships"]:
            if relationship["relationship_type"] == "REQUIRES":
                return relationship["objective_id"]
    return None


def test_generation_context_is_part_of_the_fingerprint():
    snapshot = copy.deepcopy(SCENARIOS["scn-L-semantic-neighbor-001"])
    without_anchor = copy.deepcopy(snapshot)
    without_anchor["generation_context"]["anchor_entities"] = []
    assert input_fingerprint(snapshot) != input_fingerprint(without_anchor)


# ---------------------------------------------------------------------------
# Structural reachability: every expected #46 candidate must have >=1 frozen
# nomination source. Derived from inputs only; this is a fixture-integrity
# check, not the candidate engine.
# ---------------------------------------------------------------------------

NOMINATING_PREFERENCES = frozenset({"MORE", "LESS", "PAUSED", "NOT_INTERESTED"})


def _entity_key(entity: dict) -> tuple[str, int]:
    return (entity["entity_id"], entity["entity_version"])


def _related_to_adjacency(snapshot: dict) -> dict[tuple[str, int], set]:
    adjacency: dict[tuple[str, int], set] = {
        _entity_key(entity): set() for entity in snapshot["ontology_snapshot"]["entities"]
    }
    for entity in snapshot["ontology_snapshot"]["entities"]:
        source = _entity_key(entity)
        for relationship in entity["relationships"]:
            if relationship["relationship_type"] != "RELATED_TO":
                continue
            target = (relationship["target_entity_id"], relationship["target_entity_version"])
            adjacency.setdefault(source, set()).add(target)
            adjacency.setdefault(target, set()).add(source)
    return adjacency


def _reachable(start: tuple[str, int], adjacency: dict) -> set:
    seen: set = set()
    stack = [start]
    while stack:
        node = stack.pop()
        for neighbour in adjacency.get(node, ()):
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return seen


def _nomination_sources(snapshot: dict) -> dict[tuple[str, int], set[str]]:
    adjacency = _related_to_adjacency(snapshot)
    anchors = {_entity_key(anchor) for anchor in _anchors(snapshot)}
    vectors = {_entity_key(vector) for vector in snapshot["semantic_space"]["vectors"]}
    anchored_vectors = anchors & vectors
    explicit = {
        preference["entity_id"]: preference["preference"]
        for preference in snapshot["preference_snapshot"]["explicit_preferences"]
    }
    active_targets = [
        (exploration["entity_id"], exploration["entity_version"])
        for exploration in snapshot["exploration_history"]["explorations"]
        if exploration["status"] == "ACTIVE"
    ]
    completed = {
        (exploration["entity_id"], exploration["entity_version"])
        for exploration in snapshot["exploration_history"]["explorations"]
        if exploration["status"] == "COMPLETED"
    }
    sources: dict[tuple[str, int], set[str]] = {}
    for entity in snapshot["ontology_snapshot"]["entities"]:
        key = _entity_key(entity)
        found: set[str] = set()
        if explicit.get(key[0]) in NOMINATING_PREFERENCES:
            found.add("EXPLICIT_INTEREST")
        if key not in anchors and key in vectors and anchored_vectors:
            found.add("SEMANTIC")
        if key not in anchors:
            if any(key in _reachable(anchor, adjacency) for anchor in anchors):
                found.add("GRAPH")
            if any(
                key != target and key in _reachable(target, adjacency)
                for target in active_targets
            ):
                found.add("HISTORY_CONTINUATION")
        if key in completed:
            found.add("REVISIT")
        sources[key] = found
    return sources


def _expected_candidate_targets(scenario_id: str) -> list[dict]:
    manifest = EXPECTATIONS[scenario_id]
    targets = [
        expectation["target"]
        for expectation in manifest["hard_expectations"]
        if "target" in expectation and "eligibility_state" in expectation
    ]
    for expectation in manifest["relative_expectations"]:
        targets.append(expectation["higher_ranked_target"])
        targets.append(expectation["lower_ranked_target"])
    return targets


def test_every_expected_candidate_has_a_frozen_nomination_source():
    for scenario_id, snapshot in SCENARIOS.items():
        sources = _nomination_sources(snapshot)
        for target in _expected_candidate_targets(scenario_id):
            key = (target["entity_id"], target["entity_version"])
            assert sources[key], (scenario_id, target)


def test_scenario_e_conflict_targets_are_reachable_without_anchor():
    snapshot = SCENARIOS[SCENARIO_E]
    assert _anchors(snapshot) == []
    sources = _nomination_sources(snapshot)
    for name in ("more_target", "less_target"):
        target = SCENARIO_TARGETS[SCENARIO_E][name]
        key = (target["entity_id"], target["entity_version"])
        assert "EXPLICIT_INTEREST" in sources[key], name
    assert "control" not in SCENARIO_TARGETS[SCENARIO_E]


def test_objective_states_are_versioned_and_unique():
    for scenario_id, snapshot in SCENARIOS.items():
        keys = [
            (state["objective_id"], state["entity_id"], state["entity_version"])
            for state in snapshot["learner_state_snapshot"]["objective_states"]
        ]
        for state in snapshot["learner_state_snapshot"]["objective_states"]:
            assert isinstance(state["entity_version"], int), scenario_id
        assert len(keys) == len(set(keys)), scenario_id


def test_explicit_preferences_are_versioned_and_unique():
    for scenario_id, snapshot in SCENARIOS.items():
        keys = [
            (preference["entity_id"], preference["entity_version"])
            for preference in snapshot["preference_snapshot"]["explicit_preferences"]
        ]
        for preference in snapshot["preference_snapshot"]["explicit_preferences"]:
            assert isinstance(preference["entity_version"], int), scenario_id
        assert len(keys) == len(set(keys)), scenario_id


def test_requires_prerequisite_evidence_is_version_matched():
    for scenario_id, snapshot in SCENARIOS.items():
        entities = _entities(snapshot)
        for entity, relationship in _relationships(snapshot):
            if relationship["relationship_type"] != "REQUIRES":
                continue
            prerequisite_key = (
                relationship["target_entity_id"],
                relationship["target_entity_version"],
            )
            assert prerequisite_key in entities, (scenario_id, prerequisite_key)
            for state in snapshot["learner_state_snapshot"]["objective_states"]:
                if state["objective_id"] != relationship["objective_id"]:
                    continue
                if state["entity_id"] != relationship["target_entity_id"]:
                    continue
                assert state["entity_version"] == relationship["target_entity_version"], (
                    scenario_id,
                    state,
                )
