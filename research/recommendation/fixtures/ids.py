"""Stable synthetic identities for M3 simulation fixtures.

Every identifier is deterministic and offline: no ``uuid4``, no randomness,
no wall-clock. The UUID-shaped strings reuse the frozen contract's synthetic
namespace style (``20000000-0000-4000-8000-000000000001``).

Candidate ids are deliberately absent. The frozen contract requires a
deterministic derivation from target identity but does not freeze an encoding
algorithm, so target identity is carried as ``(entity_id, entity_version,
entity_type)`` and the derivation stays in #46.
"""

from __future__ import annotations

LEARNER_NAMESPACE = 10000000
ENTITY_NAMESPACE = 20000000
DOMAIN_NAMESPACE = 30000000
OBJECTIVE_NAMESPACE = 40000000

_NAMESPACES = (LEARNER_NAMESPACE, ENTITY_NAMESPACE, DOMAIN_NAMESPACE, OBJECTIVE_NAMESPACE)

#: Canonical A-T scenarios, one per frozen §21 category.
CANONICAL_SCENARIO_IDS = (
    "scn-A-explicit-more-001",
    "scn-B-explicit-less-001",
    "scn-C-explicit-paused-001",
    "scn-D-not-interested-001",
    "scn-E-preference-conflict-001",
    "scn-F-prereq-unmet-001",
    "scn-G-prereq-satisfied-001",
    "scn-H-prereq-unknown-001",
    "scn-I-difficulty-too-low-001",
    "scn-J-difficulty-appropriate-001",
    "scn-K-difficulty-too-high-001",
    "scn-L-semantic-neighbor-001",
    "scn-M-graph-neighbor-001",
    "scn-N-continuation-001",
    "scn-O-revisit-001",
    "scn-P-diversity-pressure-001",
    "scn-Q-deterministic-tie-001",
    "scn-R-multisource-duplicate-001",
    "scn-S-sparse-learner-001",
    "scn-T-no-eligible-001",
)

#: Approved compound interaction scenarios X1-X7.
COMPOUND_SCENARIO_IDS = (
    "scn-X1-more-unmet-prereq-001",
    "scn-X2-not-interested-inferred-positive-001",
    "scn-X3-three-source-duplicate-001",
    "scn-X4-diversity-ineligible-001",
    "scn-X5-tie-diversity-001",
    "scn-X6-sparse-semantic-001",
    "scn-X7-multi-exclusion-empty-001",
)

SCENARIO_IDS = CANONICAL_SCENARIO_IDS + COMPOUND_SCENARIO_IDS

#: Frozen §21 category letter for each canonical scenario.
CATEGORY_BY_SCENARIO_ID = {
    scenario_id: scenario_id.split("-")[1]
    for scenario_id in CANONICAL_SCENARIO_IDS
}

#: Stable 1-based index drives the synthetic id block for a scenario.
SCENARIO_INDEX = {
    scenario_id: index + 1 for index, scenario_id in enumerate(SCENARIO_IDS)
}


def synthetic_id(namespace: int, n: int) -> str:
    """Return a stable UUID-shaped synthetic identifier.

    ``namespace`` selects a contract-style 8-digit prefix; ``n`` is the
    deterministic numeric index.
    """
    if namespace not in _NAMESPACES:
        raise ValueError(f"unknown synthetic namespace: {namespace!r}")
    if not 0 <= n < 1_000_000_000_000:
        raise ValueError("synthetic id index out of range")
    return f"{namespace:08d}-0000-4000-8000-{n:012d}"


class IdSpace:
    """Per-scenario deterministic identifier allocator.

    Entity ids are globally unique across the corpus because the scenario index
    forms a higher-order digit block (``scenario_index * 1000 + local``).
    """

    __slots__ = ("_scenario_index",)

    def __init__(self, scenario_index: int) -> None:
        if scenario_index < 1:
            raise ValueError("scenario_index must be >= 1")
        self._scenario_index = scenario_index

    def _local(self, local: int) -> int:
        if local < 1:
            raise ValueError("local id index must be >= 1")
        return self._scenario_index * 1000 + local

    def learner(self) -> str:
        return synthetic_id(LEARNER_NAMESPACE, self._scenario_index)

    def entity(self, local: int) -> str:
        return synthetic_id(ENTITY_NAMESPACE, self._local(local))

    def domain(self, local: int) -> str:
        return synthetic_id(DOMAIN_NAMESPACE, self._local(local))

    def objective(self, local: int) -> str:
        return synthetic_id(OBJECTIVE_NAMESPACE, self._local(local))
