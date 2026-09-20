"""The 27-scenario M3 simulation fixture corpus.

20 canonical scenarios (A-T) plus 7 approved compound scenarios (X1-X7). Every
scenario is deterministic, offline, and synthetic. Scenarios build
``SimulationInput`` snapshots only; candidate generation, eligibility, scoring,
ranking, reranking, and results belong to #46-#49.

Relative expectations are grounded in same-scenario controlled comparators: a
target and an otherwise-equivalent control that differ only in the tested
factor. No relative claim compares outputs across independently constructed
scenarios.
"""

from __future__ import annotations

from collections.abc import Callable

import research.recommendation.fixtures.builders as b
from research.recommendation.fixtures.ids import (
    COMPOUND_SCENARIO_IDS,
    CANONICAL_SCENARIO_IDS,
    SCENARIO_IDS,
    SCENARIO_INDEX,
    IdSpace,
)
from research.recommendation.fixtures.semantic import named_vector
from research.recommendation.fixtures.timestamps import sim_time

# Reusable, deterministic inferred-interest profiles (learner_interest_state).
POSITIVE = {
    "recent": 0.9,
    "long_term": 0.85,
    "user_initiated": 0.9,
    "algorithm": 0.2,
    "revisits": 4,
}
MILD_POSITIVE = {
    "recent": 0.3,
    "long_term": 0.3,
    "user_initiated": 0.3,
    "algorithm": 0.1,
    "revisits": 1,
}
NEGATIVE = {
    "recent": -0.6,
    "long_term": -0.5,
    "user_initiated": -0.4,
    "algorithm": 0.3,
    "revisits": 0,
}


class _Builder:
    """Deterministic per-scenario snapshot assembler."""

    def __init__(self, scenario_id: str) -> None:
        self.scenario_id = scenario_id
        self.ids = IdSpace(SCENARIO_INDEX[scenario_id])
        self._entities: dict[str, dict] = {}
        self._vectors: list[dict] = []
        self._objective_states: list[dict] = []
        self._interest_states: list[dict] = []
        self._preferences: list[dict] = []
        self._explorations: list[dict] = []
        self._challenge: dict | None = None
        self._objective_counter = 0
        self._exploration_counter = 0
        self.targets: dict[str, dict] = {}

    # -- entity registration -------------------------------------------------
    def _register(
        self,
        entity_id: str,
        entity_type: str,
        title: str,
        domains: tuple[str, ...],
        difficulty: float,
        effort: int,
    ) -> None:
        self._entities[entity_id] = {
            "entity_type": entity_type,
            "title": title,
            "domains": list(domains),
            "difficulty": difficulty,
            "effort": effort,
            "relationships": [],
            "objective_ids": [],
        }

    def domain(self, local: int, title: str, *, difficulty: float = 0.5) -> str:
        entity_id = self.ids.domain(local)
        self._register(entity_id, "DOMAIN", title, (), difficulty, 10)
        return entity_id

    def topic(
        self,
        name: str,
        local: int,
        title: str,
        *,
        domains: tuple[str, ...] | list[str] = (),
        difficulty: float = 0.5,
        effort: int = 15,
    ) -> str:
        entity_id = self.ids.entity(local)
        self._register(entity_id, "TOPIC", title, tuple(domains), difficulty, effort)
        self.targets[name] = {
            "entity_id": entity_id,
            "entity_version": 1,
            "entity_type": "TOPIC",
        }
        return entity_id

    # -- graph signals -------------------------------------------------------
    def require(
        self, entity_id: str, prerequisite_entity_id: str, requirement: str = "HARD"
    ) -> None:
        self._entities[entity_id]["relationships"].append(
            b.relationship("REQUIRES", prerequisite_entity_id, 1, requirement)
        )

    def relate(self, entity_id: str, other_entity_id: str) -> None:
        self._entities[entity_id]["relationships"].append(
            b.relationship("RELATED_TO", other_entity_id, 1)
        )

    # -- learner-signal domains (kept separate) ------------------------------
    def objective(
        self,
        entity_id: str,
        *,
        state: str | None = None,
        understanding: float | None = None,
    ) -> str:
        self._objective_counter += 1
        objective_id = self.ids.objective(self._objective_counter)
        self._entities[entity_id]["objective_ids"].append(objective_id)
        if state is not None:
            self._objective_states.append(
                b.objective_state(objective_id, entity_id, state, understanding)
            )
        return objective_id

    def interest(
        self,
        entity_id: str,
        *,
        recent: float,
        user_initiated: float,
        algorithm: float,
        long_term: float | None = None,
        revisits: int = 0,
    ) -> None:
        self._interest_states.append(
            b.interest_state(
                entity_id,
                1,
                recent_affinity=recent,
                long_term_affinity=recent if long_term is None else long_term,
                user_initiated_strength=user_initiated,
                algorithm_exposure_strength=algorithm,
                voluntary_revisit_count=revisits,
            )
        )

    def inferred(self, entity_id: str, profile: dict) -> None:
        self.interest(entity_id, **profile)

    def preference(self, entity_id: str, preference_value: str) -> None:
        self._preferences.append(b.explicit_preference(entity_id, preference_value))

    def exploration(
        self,
        entity_id: str,
        status: str,
        intent: str,
        *,
        start: int = 0,
        returned: int | None = None,
        completed: int | None = None,
        paused: int | None = None,
    ) -> str:
        self._exploration_counter += 1
        exploration_id = f"{self.scenario_id}-exp-{self._exploration_counter:03d}"
        self._explorations.append(
            b.exploration(
                exploration_id,
                entity_id,
                1,
                intent,
                status,
                started_at=sim_time(start),
                returned_at=None if returned is None else sim_time(returned),
                completed_at=None if completed is None else sim_time(completed),
                paused_at=None if paused is None else sim_time(paused),
            )
        )
        return exploration_id

    def challenge(self, area_id: str, ability: float) -> None:
        self._challenge = b.challenge_state(area_id, ability)

    def vector(self, entity_id: str, vector: str | list[float]) -> None:
        resolved = named_vector(vector) if isinstance(vector, str) else list(vector)
        self._vectors.append(b.semantic_vector(entity_id, 1, resolved))

    # -- assembly ------------------------------------------------------------
    def build(self, *, top_k: int = 5) -> dict:
        entities = [
            b.entity(
                entity_id,
                1,
                meta["entity_type"],
                meta["title"],
                domain_ids=meta["domains"],
                relationships=meta["relationships"],
                objective_ids=meta["objective_ids"],
                difficulty_prior=meta["difficulty"],
                estimated_effort_minutes=meta["effort"],
            )
            for entity_id, meta in self._entities.items()
        ]
        return b.simulation_input(
            scenario_id=self.scenario_id,
            learner_ref=b.learner(self.ids.learner()),
            ontology_snapshot=b.ontology_snapshot(f"{self.scenario_id}-ontology", entities),
            learner_state_snapshot=b.learner_state_snapshot(
                f"{self.scenario_id}-learner-state",
                objective_states=self._objective_states,
                interest_states=self._interest_states,
                challenge_state=self._challenge,
            ),
            preference_snapshot=b.preference_snapshot(
                f"{self.scenario_id}-preferences", self._preferences
            ),
            exploration_history=b.exploration_history(
                f"{self.scenario_id}-history", self._explorations
            ),
            semantic_space=b.semantic_space(
                f"{self.scenario_id}-semantic", self._vectors
            ),
            simulation_config=b.simulation_config(top_k=top_k),
        )


# ===========================================================================
# Canonical scenarios A-T
# ===========================================================================


def _scenario_a() -> _Builder:
    s = _Builder("scn-A-explicit-more-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Target Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.inferred(entity_id, POSITIVE)
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.vector(target, "near")
    s.vector(control, "near")
    s.preference(target, "MORE")
    s.preference(control, "NEUTRAL")
    s.challenge(domain, 0.5)
    return s


def _scenario_b() -> _Builder:
    s = _Builder("scn-B-explicit-less-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Target Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.inferred(entity_id, POSITIVE)
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.vector(target, "near")
    s.vector(control, "near")
    s.preference(target, "LESS")
    s.preference(control, "NEUTRAL")
    s.challenge(domain, 0.5)
    return s


def _scenario_c() -> _Builder:
    s = _Builder("scn-C-explicit-paused-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Paused Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(target, POSITIVE)
    s.preference(target, "PAUSED")
    s.challenge(domain, 0.5)
    return s


def _scenario_d() -> _Builder:
    s = _Builder("scn-D-not-interested-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Disliked Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(target, POSITIVE)
    s.preference(target, "NOT_INTERESTED")
    s.challenge(domain, 0.5)
    return s


def _scenario_e() -> _Builder:
    s = _Builder("scn-E-preference-conflict-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    more_target = s.topic("more_target", 1, "Explicitly Liked Topic", domains=[domain])
    less_target = s.topic("less_target", 2, "Explicitly Disliked Topic", domains=[domain])
    control = s.topic("control", 3, "Control Topic", domains=[domain])
    for entity_id in (more_target, less_target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(more_target, NEGATIVE)
    s.inferred(less_target, POSITIVE)
    s.preference(more_target, "MORE")
    s.preference(less_target, "LESS")
    s.preference(control, "NEUTRAL")
    s.challenge(domain, 0.5)
    return s


def _prerequisite_scenario(
    scenario_id: str, prerequisite_state: str | None, understanding: float | None
) -> _Builder:
    s = _Builder(scenario_id)
    domain = s.domain(1, "Foundations")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    prerequisite = s.topic("prerequisite", 3, "Prerequisite Topic", domains=[domain])
    target = s.topic("target", 1, "Dependent Topic", domains=[domain])
    control = s.topic("control", 2, "Independent Topic", domains=[domain])
    s.require(target, prerequisite)
    s.objective(prerequisite, state=prerequisite_state, understanding=understanding)
    s.objective(target, state="EXPLORING", understanding=0.5)
    s.objective(control, state="EXPLORING", understanding=0.5)
    s.inferred(control, MILD_POSITIVE)
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.vector(target, "near")
    s.vector(control, "near")
    s.challenge(domain, 0.5)
    return s


def _scenario_f() -> _Builder:
    return _prerequisite_scenario("scn-F-prereq-unmet-001", "ENCOUNTERED", 0.0)


def _scenario_g() -> _Builder:
    return _prerequisite_scenario("scn-G-prereq-satisfied-001", "UNDERSTOOD", 0.9)


def _scenario_h() -> _Builder:
    return _prerequisite_scenario("scn-H-prereq-unknown-001", None, None)


def _difficulty_scenario(scenario_id: str) -> _Builder:
    s = _Builder(scenario_id)
    domain = s.domain(1, "Foundations")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    for name, local, difficulty in (
        ("too_low", 1, 0.1),
        ("appropriate", 2, 0.5),
        ("too_high", 3, 0.9),
    ):
        target = s.topic(name, local, name.replace("_", " ").title(), domains=[domain], difficulty=difficulty)
        s.objective(target, state="EXPLORING", understanding=0.5)
        s.vector(target, "mid")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.challenge(domain, 0.5)
    return s


def _scenario_i() -> _Builder:
    return _difficulty_scenario("scn-I-difficulty-too-low-001")


def _scenario_j() -> _Builder:
    return _difficulty_scenario("scn-J-difficulty-appropriate-001")


def _scenario_k() -> _Builder:
    return _difficulty_scenario("scn-K-difficulty-too-high-001")


def _scenario_l() -> _Builder:
    s = _Builder("scn-L-semantic-neighbor-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 3, "Seed Topic", domains=[domain])
    near = s.topic("near", 1, "Near Neighbor", domains=[domain])
    far = s.topic("far", 2, "Far Neighbor", domains=[domain])
    for entity_id in (near, far):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
    s.vector(seed, "seed")
    s.vector(near, "near")
    s.vector(far, "far")
    s.challenge(domain, 0.5)
    return s


def _scenario_m() -> _Builder:
    s = _Builder("scn-M-graph-neighbor-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 3, "Seed Topic", domains=[domain])
    distance_1 = s.topic("distance_1", 1, "Direct Neighbor", domains=[domain])
    distance_2 = s.topic("distance_2", 2, "Second-hop Neighbor", domains=[domain])
    s.relate(distance_1, seed)
    s.relate(distance_2, distance_1)
    for entity_id in (distance_1, distance_2):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "mid")
    s.vector(seed, "seed")
    s.challenge(domain, 0.5)
    return s


def _scenario_n() -> _Builder:
    s = _Builder("scn-N-continuation-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Continuation Topic", domains=[domain])
    control = s.topic("control", 2, "Unrelated Topic", domains=[domain])
    s.relate(target, seed)
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "mid")
    s.vector(seed, "seed")
    s.objective(seed, state="EXPLORING", understanding=0.5)
    s.exploration(seed, "ACTIVE", "DIRECT_INTEREST", start=0)
    s.challenge(domain, 0.5)
    return s


def _scenario_o() -> _Builder:
    s = _Builder("scn-O-revisit-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Completed Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="RETAINED", understanding=0.8)
        s.vector(entity_id, "mid")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.exploration(target, "COMPLETED", "DIRECT_INTEREST", start=0, returned=30, completed=60)
    s.challenge(domain, 0.5)
    return s


def _scenario_p() -> _Builder:
    s = _Builder("scn-P-diversity-pressure-001")
    domain_a = s.domain(1, "Domain A")
    domain_b = s.domain(2, "Domain B")
    s.topic("seed", 4, "Seed Topic", domains=[domain_a])
    cluster_a = s.topic("cluster_a", 1, "Cluster Topic A", domains=[domain_a])
    cluster_b = s.topic("cluster_b", 2, "Cluster Topic B", domains=[domain_a])
    spread = s.topic("spread", 3, "Spread Topic", domains=[domain_b])
    for entity_id in (cluster_a, cluster_b, spread):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.vector(cluster_a, "near")
    s.vector(cluster_b, "near")
    s.vector(spread, "mid")
    s.challenge(domain_a, 0.5)
    return s


def _scenario_q() -> _Builder:
    s = _Builder("scn-Q-deterministic-tie-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target_a = s.topic("target_a", 1, "Symmetric Topic A", domains=[domain])
    target_b = s.topic("target_b", 2, "Symmetric Topic B", domains=[domain])
    for entity_id in (target_a, target_b):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.challenge(domain, 0.5)
    return s


def _scenario_r() -> _Builder:
    s = _Builder("scn-R-multisource-duplicate-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 2, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Multi-source Topic", domains=[domain])
    s.relate(target, seed)
    s.objective(target, state="EXPLORING", understanding=0.5)
    s.vector(seed, "seed")
    s.vector(target, "near")
    s.preference(target, "MORE")
    s.challenge(domain, 0.5)
    return s


def _scenario_s() -> _Builder:
    s = _Builder("scn-S-sparse-learner-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 2, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Reachable Topic", domains=[domain])
    s.relate(target, seed)
    s.vector(seed, "seed")
    s.vector(target, "near")
    s.challenge(domain, 0.5)
    return s


def _scenario_t() -> _Builder:
    s = _Builder("scn-T-no-eligible-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    prerequisite = s.topic("prerequisite", 3, "Prerequisite Topic", domains=[domain])
    paused = s.topic("paused", 1, "Paused Topic", domains=[domain])
    disliked = s.topic("disliked", 2, "Disliked Topic", domains=[domain])
    dependent = s.topic("dependent", 5, "Dependent Topic", domains=[domain])
    s.require(dependent, prerequisite)
    for entity_id in (paused, disliked, dependent):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(paused, POSITIVE)
    s.preference(paused, "PAUSED")
    s.preference(disliked, "NOT_INTERESTED")
    s.challenge(domain, 0.5)
    return s


# ===========================================================================
# Compound scenarios X1-X7
# ===========================================================================


def _scenario_x1() -> _Builder:
    s = _Builder("scn-X1-more-unmet-prereq-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    prerequisite = s.topic("prerequisite", 3, "Prerequisite Topic", domains=[domain])
    target = s.topic("target", 1, "Liked but Unready Topic", domains=[domain])
    control = s.topic("control", 2, "Ready Topic", domains=[domain])
    s.require(target, prerequisite)
    s.objective(prerequisite, state="ENCOUNTERED", understanding=0.0)
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.preference(entity_id, "MORE")
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.challenge(domain, 0.5)
    return s


def _scenario_x2() -> _Builder:
    s = _Builder("scn-X2-not-interested-inferred-positive-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Disliked but Inferred Topic", domains=[domain])
    control = s.topic("control", 2, "Control Topic", domains=[domain])
    for entity_id in (target, control):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(target, POSITIVE)
    s.preference(target, "NOT_INTERESTED")
    s.challenge(domain, 0.5)
    return s


def _scenario_x3() -> _Builder:
    s = _Builder("scn-X3-three-source-duplicate-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 3, "Seed Topic", domains=[domain])
    target = s.topic("target", 1, "Three-source Topic", domains=[domain])
    graph_only = s.topic("graph_only", 2, "Graph-only Topic", domains=[domain])
    s.relate(target, seed)
    s.relate(graph_only, seed)
    for entity_id in (target, graph_only):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
    s.vector(seed, "seed")
    s.vector(target, "near")
    s.vector(graph_only, "mid")
    s.preference(target, "MORE")
    s.challenge(domain, 0.5)
    return s


def _scenario_x4() -> _Builder:
    s = _Builder("scn-X4-diversity-ineligible-001")
    domain = s.domain(1, "Domain A")
    s.topic("seed", 4, "Seed Topic", domains=[domain])
    cluster_a = s.topic("cluster_a", 1, "Cluster Topic A", domains=[domain])
    cluster_b = s.topic("cluster_b", 2, "Cluster Topic B", domains=[domain])
    ineligible = s.topic("ineligible", 3, "Paused Cluster Topic", domains=[domain])
    s.inferred(ineligible, POSITIVE)
    s.preference(ineligible, "PAUSED")
    for entity_id in (cluster_a, cluster_b, ineligible):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.vector(cluster_a, "near")
    s.vector(cluster_b, "near")
    s.vector(ineligible, "near")
    s.challenge(domain, 0.5)
    return s


def _scenario_x5() -> _Builder:
    s = _Builder("scn-X5-tie-diversity-001")
    domain_a = s.domain(1, "Domain A")
    domain_b = s.domain(2, "Domain B")
    s.topic("seed", 4, "Seed Topic", domains=[domain_a])
    target_a = s.topic("target_a", 1, "Symmetric Topic A", domains=[domain_a])
    target_b = s.topic("target_b", 2, "Symmetric Topic B", domains=[domain_a])
    spread = s.topic("spread", 3, "Spread Topic", domains=[domain_b])
    s.vector(s.targets["seed"]["entity_id"], "seed")
    for entity_id in (target_a, target_b, spread):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
    s.vector(target_a, "near")
    s.vector(target_b, "near")
    s.vector(spread, "mid")
    s.challenge(domain_a, 0.5)
    return s


def _scenario_x6() -> _Builder:
    s = _Builder("scn-X6-sparse-semantic-001")
    domain = s.domain(1, "Foundations")
    seed = s.topic("seed", 2, "Seed Topic", domains=[domain])
    near = s.topic("near", 1, "Semantic Neighbor", domains=[domain])
    s.vector(seed, "seed")
    s.vector(near, "near")
    s.challenge(domain, 0.5)
    return s


def _scenario_x7() -> _Builder:
    s = _Builder("scn-X7-multi-exclusion-empty-001")
    domain = s.domain(1, "Foundations")
    s.topic("seed", 5, "Seed Topic", domains=[domain])
    unmet_prerequisite = s.topic("unmet_prerequisite", 4, "Unmet Prerequisite", domains=[domain])
    unknown_source = s.topic("unknown_source", 7, "Un-evidenced Prerequisite", domains=[domain])
    paused = s.topic("paused", 1, "Paused Topic", domains=[domain])
    disliked = s.topic("disliked", 2, "Disliked Topic", domains=[domain])
    dependent = s.topic("dependent", 3, "Unready Topic", domains=[domain])
    unknown_dependent = s.topic("unknown_dependent", 6, "Unknown Prereq Topic", domains=[domain])
    s.require(dependent, unmet_prerequisite)
    s.require(unknown_dependent, unknown_source)
    s.objective(unmet_prerequisite, state="ENCOUNTERED", understanding=0.0)
    for entity_id in (paused, disliked, dependent, unknown_dependent):
        s.objective(entity_id, state="EXPLORING", understanding=0.5)
        s.vector(entity_id, "near")
    s.vector(s.targets["seed"]["entity_id"], "seed")
    s.inferred(paused, POSITIVE)
    s.preference(paused, "PAUSED")
    s.preference(disliked, "NOT_INTERESTED")
    s.challenge(domain, 0.5)
    return s


_BUILD_FUNCS: dict[str, Callable[[], _Builder]] = {
    "scn-A-explicit-more-001": _scenario_a,
    "scn-B-explicit-less-001": _scenario_b,
    "scn-C-explicit-paused-001": _scenario_c,
    "scn-D-not-interested-001": _scenario_d,
    "scn-E-preference-conflict-001": _scenario_e,
    "scn-F-prereq-unmet-001": _scenario_f,
    "scn-G-prereq-satisfied-001": _scenario_g,
    "scn-H-prereq-unknown-001": _scenario_h,
    "scn-I-difficulty-too-low-001": _scenario_i,
    "scn-J-difficulty-appropriate-001": _scenario_j,
    "scn-K-difficulty-too-high-001": _scenario_k,
    "scn-L-semantic-neighbor-001": _scenario_l,
    "scn-M-graph-neighbor-001": _scenario_m,
    "scn-N-continuation-001": _scenario_n,
    "scn-O-revisit-001": _scenario_o,
    "scn-P-diversity-pressure-001": _scenario_p,
    "scn-Q-deterministic-tie-001": _scenario_q,
    "scn-R-multisource-duplicate-001": _scenario_r,
    "scn-S-sparse-learner-001": _scenario_s,
    "scn-T-no-eligible-001": _scenario_t,
    "scn-X1-more-unmet-prereq-001": _scenario_x1,
    "scn-X2-not-interested-inferred-positive-001": _scenario_x2,
    "scn-X3-three-source-duplicate-001": _scenario_x3,
    "scn-X4-diversity-ineligible-001": _scenario_x4,
    "scn-X5-tie-diversity-001": _scenario_x5,
    "scn-X6-sparse-semantic-001": _scenario_x6,
    "scn-X7-multi-exclusion-empty-001": _scenario_x7,
}

if set(_BUILD_FUNCS) != set(SCENARIO_IDS):
    raise RuntimeError("scenario registry does not match declared scenario ids")

SCENARIO_BUILDERS: dict[str, _Builder] = {
    scenario_id: build_func() for scenario_id, build_func in _BUILD_FUNCS.items()
}
SCENARIOS: dict[str, dict] = {
    scenario_id: builder.build() for scenario_id, builder in SCENARIO_BUILDERS.items()
}
SCENARIO_TARGETS: dict[str, dict[str, dict]] = {
    scenario_id: dict(builder.targets) for scenario_id, builder in SCENARIO_BUILDERS.items()
}


def build_scenario(scenario_id: str) -> dict:
    """Rebuild a scenario from scratch (used by determinism checks)."""
    try:
        build_func = _BUILD_FUNCS[scenario_id]
    except KeyError as error:
        raise KeyError(f"unknown scenario_id: {scenario_id!r}") from error
    return build_func().build()
