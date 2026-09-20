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
* :class:`SimulationInputError` -- raised for structurally invalid input.

The package does not assemble ``SimulationResult`` metrics, apply ``top_k``,
persist, or access any network/database.
"""

from __future__ import annotations

from .eligibility import EXCLUSION_ORDER
from .explain import EXPLANATION_CODES, build_recommendation_results
from .pipeline import generate_candidates
from .scoring import rank_candidates
from .sources import CANDIDATE_SOURCES
from .validation import SimulationInputError

__all__ = [
    "CANDIDATE_SOURCES",
    "EXCLUSION_ORDER",
    "EXPLANATION_CODES",
    "SimulationInputError",
    "build_recommendation_results",
    "generate_candidates",
    "rank_candidates",
]
