from __future__ import annotations

import pytest

from app.recommendation.service import distance_band


@pytest.mark.parametrize("paths, expected", [
    ([{"source": "HISTORY_CONTINUATION", "provenance": {}}], "COMFORT"),
    ([{"source": "GRAPH", "provenance": {"hop_distance": 1}}], "ADJACENT"),
    ([{"source": "GRAPH", "provenance": {"hop_distance": 2}}], "FRONTIER"),
    ([{"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.55}}], "WILD"),
    ([{"source": "SEMANTIC", "provenance": {"cosine_similarity": 0.8}},
      {"source": "REVISIT", "provenance": {}}], "COMFORT"),
    ([], "ADJACENT"),
])
def test_distance_band_v1(paths, expected):
    assert distance_band(paths) == expected
