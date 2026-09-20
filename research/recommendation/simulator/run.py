"""#49 SimulationResult runner (m3-simulation/v5).

Orchestrates the frozen #46 -> #47 -> #48 pipeline, applies the frozen ``top_k``
prefix selection, computes the thirteen descriptive metrics, evaluates the ten
hard invariants, and assembles a ``SimulationResult`` (§17, §17.1, §17.2, §19).

The generic engine is fixture-free: it never imports fixture scenario IDs,
expectations, or manifests. Fixture comparison lives in
``research.recommendation.simulator.evaluate``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from .explain import build_recommendation_results
from .identity import canonical_json, canonicalize_simulation_input_for_identity
from .invariants import evaluate_invariants
from .metrics import compute_metrics
from .pipeline import generate_candidates
from .scoring import rank_candidates
from .validation import validate_simulation_input

CONTRACT_VERSION = "m3-simulation/v5"


@dataclass
class CoreExecution:
    """Transient populations from one deterministic core execution.

    Internal only. Non-selected eligible results are never exposed publicly
    (§17.1).
    """

    candidates_considered: list
    candidates_excluded: list
    full_ranked_candidates: list
    full_recommendation_results: list
    selected_recommendations: list
    metrics: dict


def input_fingerprint(simulation_input: dict) -> str:
    """Return ``sha256:<hex>`` over the engine canonical ``SimulationInput``.

    The validated input is first placed into the contract §4 canonical snapshot
    form (order-insensitive arrays canonically ordered), then serialized with the
    engine-owned ``canonical_json`` (§17.2). It never imports fixture
    canonicalization and never mutates the caller's input.
    """
    canonical_input = canonicalize_simulation_input_for_identity(simulation_input)
    digest = hashlib.sha256(canonical_json(canonical_input).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"


def _execute_core(simulation_input: dict) -> CoreExecution:
    """Run the deterministic pipeline once, without evaluating invariants."""
    candidates_considered = generate_candidates(simulation_input)
    full_ranked_candidates = rank_candidates(simulation_input, candidates_considered)
    full_recommendation_results = build_recommendation_results(full_ranked_candidates)

    top_k = simulation_input["simulation_config"]["top_k"]
    selected_count = min(top_k, len(full_recommendation_results))
    selected_recommendations = full_recommendation_results[:selected_count]

    candidates_excluded = [
        candidate
        for candidate in candidates_considered
        if candidate["eligibility_state"] == "INELIGIBLE"
    ]

    metrics = compute_metrics(
        candidates_considered,
        candidates_excluded,
        full_ranked_candidates,
        selected_recommendations,
    )

    return CoreExecution(
        candidates_considered=candidates_considered,
        candidates_excluded=candidates_excluded,
        full_ranked_candidates=full_ranked_candidates,
        full_recommendation_results=full_recommendation_results,
        selected_recommendations=selected_recommendations,
        metrics=metrics,
    )


def run_simulation(simulation_input: dict) -> dict:
    """Return a deterministic ``SimulationResult`` for one ``SimulationInput``.

    Structural invalidity raises via the existing validator. Invariant failure
    never raises; it is returned as ``FAIL`` invariant results (§19.2).
    """
    validate_simulation_input(simulation_input)

    core = _execute_core(simulation_input)
    second = _execute_core(simulation_input)
    invariant_results = evaluate_invariants(core, second)

    return {
        "contract_version": simulation_input["contract_version"],
        "scenario_id": simulation_input["scenario_id"],
        "config_version": simulation_input["simulation_config"]["config_version"],
        "input_fingerprint": input_fingerprint(simulation_input),
        "candidates_considered": core.candidates_considered,
        "candidates_excluded": core.candidates_excluded,
        "ranked_recommendations": core.selected_recommendations,
        "invariant_results": invariant_results,
        "metrics": core.metrics,
        "execution_metadata": {},
    }
