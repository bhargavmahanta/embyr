"""Deterministic, offline M3 recommendation simulation fixtures (Issue #45).

The package builds ``SimulationInput`` snapshots only. It does not generate,
normalize, score, rank, or persist recommendations; those remain #46-#49.

Public surface:

* :data:`SCENARIOS` -- ``scenario_id -> SimulationInput`` for the 27-scenario
  corpus (20 canonical A-T plus 7 compound X1-X7).
* :func:`build_scenario` -- rebuild a scenario from scratch (determinism checks).
* :mod:`research.recommendation.fixtures.expectations` -- future-oracle
  metadata, kept out of ``SimulationInput``.
"""

from __future__ import annotations

from .scenarios import (
    COMPOUND_SCENARIO_IDS,
    CANONICAL_SCENARIO_IDS,
    SCENARIO_IDS,
    SCENARIO_TARGETS,
    SCENARIOS,
    build_scenario,
)

__all__ = [
    "CANONICAL_SCENARIO_IDS",
    "COMPOUND_SCENARIO_IDS",
    "SCENARIO_IDS",
    "SCENARIO_TARGETS",
    "SCENARIOS",
    "build_scenario",
]
