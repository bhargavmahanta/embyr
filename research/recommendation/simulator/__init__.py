"""M3 recommendation simulator (simulation-only).

Public surface:

* :func:`generate_candidates` (#46) -- input validation, generation from the
  five frozen sources, normalization, prerequisite/readiness evaluation, and
  hard eligibility filtering, returning deterministic ``Candidate`` dictionaries.
* :func:`rank_candidates` (#47) -- score eligible candidates with the frozen v3
  features, apply optional ``DOMAIN_COVERAGE`` reranking, and return the full
  ``RankedCandidate`` list (§14.2).
* :func:`build_recommendation_results` (#48) -- derive deterministic explanation
  codes and assemble ``RecommendationResult`` objects from ``RankedCandidate``
  input (§14.3, §15).
* :func:`run_simulation` (#49) -- orchestrate #46 -> #47 -> #48, apply the frozen
  ``top_k`` prefix selection, compute descriptive metrics and hard invariants,
  and assemble ``SimulationResult`` (§17, §19).
* :class:`SimulationInputError` -- raised for structurally invalid input.

The M3 fixture evaluation harness lives separately in
``research.recommendation.simulator.evaluate`` so the generic engine stays
fixture-free. The package does not persist or access any network/database.
"""

from __future__ import annotations

from .eligibility import EXCLUSION_ORDER
from .explain import EXPLANATION_CODES, build_recommendation_results
from .invariants import INVARIANT_CODES, evaluate_invariants
from .metrics import compute_metrics
from .pipeline import generate_candidates
from .run import input_fingerprint, run_simulation
from .scoring import rank_candidates
from .sources import CANDIDATE_SOURCES
from .validation import SimulationInputError

__all__ = [
    "CANDIDATE_SOURCES",
    "EXCLUSION_ORDER",
    "EXPLANATION_CODES",
    "INVARIANT_CODES",
    "SimulationInputError",
    "build_recommendation_results",
    "compute_metrics",
    "evaluate_invariants",
    "generate_candidates",
    "input_fingerprint",
    "rank_candidates",
    "run_simulation",
]
