"""M3 #46 candidate-generation simulator (simulation-only).

Public surface:

* :func:`generate_candidates` -- run input validation, generation from the five
  frozen sources, normalization, prerequisite/readiness evaluation, and hard
  eligibility filtering, returning deterministic ``Candidate`` dictionaries.
* :class:`SimulationInputError` -- raised for structurally invalid input.

This package implements only the candidate stages owned by Issue #46. It does
not score, rank, rerank, explain, persist, or access any network/database.
"""

from __future__ import annotations

from .eligibility import EXCLUSION_ORDER
from .pipeline import generate_candidates
from .sources import CANDIDATE_SOURCES
from .validation import SimulationInputError

__all__ = [
    "CANDIDATE_SOURCES",
    "EXCLUSION_ORDER",
    "SimulationInputError",
    "generate_candidates",
]
