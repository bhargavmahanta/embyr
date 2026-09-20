"""#49 descriptive metric unit tests: populations, maps, zero denominators."""

from __future__ import annotations

from research.recommendation.simulator.eligibility import EXCLUSION_ORDER
from research.recommendation.simulator.metrics import compute_metrics
from research.recommendation.simulator.sources import CANDIDATE_SOURCES
from research.recommendation.tests._runner_helpers import candidate, explanation, ranked


def _excluded(considered):
    return [c for c in considered if c["eligibility_state"] == "INELIGIBLE"]


def _metrics(considered, full_ranked=(), selected=()):
    return compute_metrics(
        considered, _excluded(considered), list(full_ranked), list(selected)
    )


def test_counts_and_source_multi_increment():
    considered = [
        candidate("c1", "e1", sources=("GRAPH", "SEMANTIC")),
        candidate("c2", "e2", sources=("SEMANTIC",)),
    ]
    metrics = _metrics(considered)
    assert metrics["candidate_count"] == 2
    assert metrics["eligible_candidate_count"] == 2
    assert metrics["source_coverage"] == {
        "GRAPH": 1,
        "SEMANTIC": 2,
        "EXPLICIT_INTEREST": 0,
        "HISTORY_CONTINUATION": 0,
        "REVISIT": 0,
    }


def test_exclusion_map_all_keys_and_multi_reason_exceeds_count():
    considered = [
        candidate(
            "c1",
            "e1",
            eligibility="INELIGIBLE",
            exclusion_reasons=("PREREQUISITE_UNMET", "NOT_INTERESTED"),
        )
    ]
    metrics = _metrics(considered)
    counts = metrics["exclusion_count_by_reason"]
    assert list(counts) == list(EXCLUSION_ORDER)
    assert sum(counts.values()) == 2 > len(_excluded(considered))
    assert counts["PREREQUISITE_UNMET"] == 1
    assert counts["NOT_INTERESTED"] == 1


def test_selected_only_vs_considered_populations():
    considered = [
        candidate("c1", "e1", sources=("GRAPH",)),
        candidate("c2", "e2", sources=("REVISIT",)),
    ]
    selected = [explanation("c1", "e1", sources=("GRAPH",))]
    metrics = _metrics(considered, selected=selected)
    assert metrics["source_coverage"]["REVISIT"] == 1
    assert metrics["top_k_source_mix"] == {
        "GRAPH": 1,
        "SEMANTIC": 0,
        "EXPLICIT_INTEREST": 0,
        "HISTORY_CONTINUATION": 0,
        "REVISIT": 0,
    }
    assert list(metrics["source_coverage"]) == list(CANDIDATE_SOURCES)


def test_topic_domain_diversity_uses_rerank_trace_and_empty_selected():
    considered = [candidate("c1", "e1"), candidate("c2", "e2")]
    first = explanation("c1", "e1")
    first["rerank_trace"]["diversity_dimensions"] = {"domain_ids": ["d1", "d2"]}
    second = explanation("c2", "e2")
    second["rerank_trace"]["diversity_dimensions"] = {"domain_ids": ["d2", "d3"]}
    metrics = _metrics(considered, selected=[first, second])
    assert metrics["topic_domain_diversity"] == 3
    assert _metrics(considered)["topic_domain_diversity"] == 0


def test_difficulty_distribution_canonical_keys_and_null():
    considered = [
        candidate("c1", "e1", difficulty_prior=0.5),
        candidate("c2", "e2", difficulty_prior=None),
    ]
    selected = [explanation("c1", "e1"), explanation("c2", "e2")]
    metrics = _metrics(considered, selected=selected)
    assert metrics["difficulty_distribution"] == {"0.5": 1, "null": 1}
    assert _metrics(considered)["difficulty_distribution"] == {}


def test_coverages_shares_and_zero_denominators():
    considered = [
        candidate("c1", "e1", sources=("EXPLICIT_INTEREST",)),
        candidate("c2", "e2", sources=("GRAPH",)),
        candidate("c3", "e3", sources=("GRAPH",)),
    ]
    metrics = _metrics(considered)
    assert metrics["explicit_interest_coverage"] == 1 / 3
    assert metrics["semantic_candidate_coverage"] == 0.0
    assert isinstance(metrics["candidate_count"], int)
    assert isinstance(metrics["explicit_interest_coverage"], float)

    empty = _metrics([])
    assert empty["explicit_interest_coverage"] == 0.0
    assert empty["semantic_candidate_coverage"] == 0.0


def test_revisit_and_continuation_shares_selected_population():
    considered = [candidate("c1", "e1"), candidate("c2", "e2")]
    selected = [
        explanation("c1", "e1", sources=("REVISIT",)),
        explanation("c2", "e2", sources=("HISTORY_CONTINUATION",)),
    ]
    metrics = _metrics(considered, selected=selected)
    assert metrics["revisit_share"] == 0.5
    assert metrics["continuation_share"] == 0.5

    empty = _metrics([])
    assert empty["revisit_share"] == 0.0
    assert empty["continuation_share"] == 0.0


def test_rank_change_uses_full_ranked_population():
    considered = [candidate("c1", "e1"), candidate("c2", "e2")]
    full_ranked = [
        ranked("c1", "e1", rank=1, pre_rerank_rank=2, post_rerank_rank=1),
        ranked("c2", "e2", rank=2, pre_rerank_rank=1, post_rerank_rank=2),
    ]
    selected = [explanation("c1", "e1", rank=1)]
    metrics = _metrics(considered, full_ranked=full_ranked, selected=selected)
    assert metrics["rank_change_due_to_diversity"] == 2


def test_trace_completeness_ignores_empty_explanation_codes():
    considered = [candidate("c1", "e1")]
    complete = explanation("c1", "e1", explanation_codes=())
    metrics = _metrics(considered, selected=[complete])
    assert metrics["trace_completeness"] == 1.0

    incomplete = explanation("c2", "e2")
    del incomplete["rerank_trace"]
    considered_two = [candidate("c2", "e2")]
    metrics = _metrics(considered_two, selected=[incomplete])
    assert metrics["trace_completeness"] == 0.0


def test_all_thirteen_metrics_present():
    metrics = _metrics([candidate("c1", "e1")])
    assert set(metrics) == {
        "candidate_count",
        "eligible_candidate_count",
        "exclusion_count_by_reason",
        "source_coverage",
        "top_k_source_mix",
        "topic_domain_diversity",
        "difficulty_distribution",
        "explicit_interest_coverage",
        "semantic_candidate_coverage",
        "revisit_share",
        "continuation_share",
        "rank_change_due_to_diversity",
        "trace_completeness",
    }
