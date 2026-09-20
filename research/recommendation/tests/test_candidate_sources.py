"""Unit tests for the five frozen candidate sources (nomination only)."""

from __future__ import annotations

from research.recommendation.fixtures.semantic import FAR, MID, NEAR, OPPOSITE, SEED
from research.recommendation.simulator.sources import (
    CANDIDATE_SOURCES,
    explicit_interest_nominations,
    graph_nominations,
    history_continuation_nominations,
    revisit_nominations,
    semantic_nominations,
)
from research.recommendation.tests._candidate_helpers import (
    exploration,
    make_input,
    preference,
    related,
    requires,
    topic,
    vector,
)

# ---------------------------------------------------------------------------
# GRAPH
# ---------------------------------------------------------------------------


def _graph_provenance(nominations, target_id):
    return [n["provenance"] for n in nominations if n["target_entity_id"] == target_id]


def test_graph_anchor_excluded_and_direct_neighbor_nominated():
    sim = make_input(entities=[topic("a", relationships=[related("b")]), topic("b")], anchors=[("a", 1)])
    nominations = graph_nominations(sim)
    assert [n["target_entity_id"] for n in nominations] == ["b"]
    assert _graph_provenance(nominations, "b")[0]["hop_distance"] == 1


def test_graph_reverse_oriented_edge_nominated():
    sim = make_input(entities=[topic("a"), topic("c", relationships=[related("a")])], anchors=[("a", 1)])
    assert [n["target_entity_id"] for n in graph_nominations(sim)] == ["c"]


def test_graph_multi_hop_and_shortest_path():
    sim = make_input(
        entities=[
            topic("a", relationships=[related("b"), related("c")]),
            topic("b", relationships=[related("t")]),
            topic("c", relationships=[related("d")]),
            topic("d", relationships=[related("t")]),
            topic("t"),
        ],
        anchors=[("a", 1)],
    )
    nominations = graph_nominations(sim)
    assert _graph_provenance(nominations, "t")[0]["hop_distance"] == 2
    assert [ref["entity_id"] for ref in _graph_provenance(nominations, "t")[0]["canonical_path"]] == [
        "a",
        "b",
        "t",
    ]
    assert _graph_provenance(nominations, "d")[0]["hop_distance"] == 2


def test_graph_equal_shortest_path_canonical_choice():
    sim = make_input(
        entities=[
            topic("a", relationships=[related("b"), related("c")]),
            topic("b", relationships=[related("t")]),
            topic("c", relationships=[related("t")]),
            topic("t"),
        ],
        anchors=[("a", 1)],
    )
    provenance = _graph_provenance(graph_nominations(sim), "t")[0]
    assert [ref["entity_id"] for ref in provenance["canonical_path"]] == ["a", "b", "t"]


def test_graph_multiple_anchors_retain_separate_paths():
    sim = make_input(
        entities=[
            topic("a1", relationships=[related("t")]),
            topic("a2", relationships=[related("t")]),
            topic("t"),
        ],
        anchors=[("a1", 1), ("a2", 1)],
    )
    provenance = _graph_provenance(graph_nominations(sim), "t")
    assert {p["anchor_entity_id"] for p in provenance} == {"a1", "a2"}
    assert len(provenance) == 2


def test_graph_duplicate_edges_collapse():
    sim = make_input(
        entities=[topic("a", relationships=[related("b"), related("b")]), topic("b")],
        anchors=[("a", 1)],
    )
    assert len(graph_nominations(sim)) == 1


def test_graph_unrelated_component_excluded():
    sim = make_input(
        entities=[topic("a", relationships=[related("b")]), topic("b"), topic("x")],
        anchors=[("a", 1)],
    )
    assert [n["target_entity_id"] for n in graph_nominations(sim)] == ["b"]


def test_graph_ignores_requires_part_of_builds_on():
    import research.recommendation.fixtures.builders as b

    sim = make_input(
        entities=[
            topic(
                "a",
                relationships=[
                    requires("z", "OBJ-Z"),
                    b.relationship("PART_OF", "y", 1),
                    b.relationship("BUILDS_ON", "w", 1),
                ],
            ),
            topic("z"),
            topic("y"),
            topic("w"),
        ],
        anchors=[("a", 1)],
    )
    assert graph_nominations(sim) == []


def test_graph_hop_distance_matches_canonical_path_length():
    sim = make_input(
        entities=[
            topic("a", relationships=[related("b")]),
            topic("b", relationships=[related("c")]),
            topic("c"),
        ],
        anchors=[("a", 1)],
    )
    for nomination in graph_nominations(sim):
        provenance = nomination["provenance"]
        assert provenance["hop_distance"] == len(provenance["canonical_path"]) - 1
        assert provenance["canonical_path"][0]["entity_id"] == "a"
        assert provenance["canonical_path"][-1]["entity_id"] == nomination["target_entity_id"]


# ---------------------------------------------------------------------------
# SEMANTIC
# ---------------------------------------------------------------------------


def test_semantic_nominates_all_vectors_including_zero_and_negative():
    sim = make_input(
        entities=[topic("a"), topic("n"), topic("m"), topic("f"), topic("o")],
        anchors=[("a", 1)],
        vectors=[vector("a", SEED), vector("n", NEAR), vector("m", MID), vector("f", FAR), vector("o", OPPOSITE)],
    )
    nominations = semantic_nominations(sim)
    assert {n["target_entity_id"] for n in nominations} == {"n", "m", "f", "o"}
    values = {n["target_entity_id"]: n["provenance"]["cosine_similarity"] for n in nominations}
    assert values["n"] > values["m"] > values["f"] > values["o"]
    assert values["f"] == 0.0
    assert values["o"] == -1.0


def test_semantic_anchor_excluded():
    sim = make_input(entities=[topic("a")], anchors=[("a", 1)], vectors=[vector("a", SEED)])
    assert semantic_nominations(sim) == []


def test_semantic_missing_target_vector_not_nominated():
    sim = make_input(
        entities=[topic("a"), topic("b")],
        anchors=[("a", 1)],
        vectors=[vector("a", SEED)],
    )
    assert semantic_nominations(sim) == []


def test_semantic_anchor_without_vector_emits_nothing():
    sim = make_input(entities=[topic("a"), topic("b")], anchors=[("a", 1)], vectors=[vector("b", NEAR)])
    assert semantic_nominations(sim) == []


def test_semantic_multiple_anchors_separate_provenance():
    sim = make_input(
        entities=[topic("a1"), topic("a2"), topic("t")],
        anchors=[("a1", 1), ("a2", 1)],
        vectors=[vector("a1", SEED), vector("a2", NEAR), vector("t", MID)],
    )
    provenance = [n["provenance"] for n in semantic_nominations(sim) if n["target_entity_id"] == "t"]
    assert {p["anchor_entity_id"] for p in provenance} == {"a1", "a2"}
    assert len(provenance) == 2


# ---------------------------------------------------------------------------
# EXPLICIT_INTEREST
# ---------------------------------------------------------------------------


def test_explicit_nominates_non_neutral_only():
    sim = make_input(
        entities=[topic(name) for name in ("a", "b", "c", "d", "e")],
        preferences=[
            preference("a", "MORE"),
            preference("b", "LESS"),
            preference("c", "PAUSED"),
            preference("d", "NOT_INTERESTED"),
            preference("e", "NEUTRAL"),
        ],
    )
    nominations = explicit_interest_nominations(sim)
    assert {n["target_entity_id"] for n in nominations} == {"a", "b", "c", "d"}
    by_target = {n["target_entity_id"]: n["provenance"] for n in nominations}
    assert by_target["a"]["preference"] == "MORE"
    assert by_target["c"]["preference"] == "PAUSED"


def test_explicit_does_not_nominate_without_preferences():
    sim = make_input(entities=[topic("a")])
    assert explicit_interest_nominations(sim) == []


def test_explicit_nominates_carried_entity_version():
    sim = make_input(
        entities=[topic("a", version=2)],
        preferences=[preference("a", "MORE", entity_version=2)],
    )
    nominations = explicit_interest_nominations(sim)
    assert [(n["target_entity_id"], n["target_entity_version"]) for n in nominations] == [("a", 2)]
    assert nominations[0]["provenance"]["entity_version"] == 2


def test_explicit_versions_coexist_deterministically():
    sim = make_input(
        entities=[topic("a", version=1), topic("a", version=2)],
        preferences=[
            preference("a", "MORE", entity_version=2),
            preference("a", "LESS", entity_version=1),
        ],
    )
    nominations = explicit_interest_nominations(sim)
    assert [
        (n["target_entity_id"], n["target_entity_version"]) for n in nominations
    ] == [("a", 1), ("a", 2)]


# ---------------------------------------------------------------------------
# HISTORY_CONTINUATION
# ---------------------------------------------------------------------------


def test_continuation_active_direct_neighbor_only():
    sim = make_input(
        entities=[
            topic("s", relationships=[related("n")]),
            topic("n", relationships=[related("m")]),
            topic("m"),
        ],
        explorations=[exploration("e1", "s", "ACTIVE")],
    )
    nominations = history_continuation_nominations(sim)
    assert [n["target_entity_id"] for n in nominations] == ["n"]
    assert nominations[0]["provenance"]["exploration_id"] == "e1"


def test_continuation_paused_and_completed_emit_nothing():
    sim = make_input(
        entities=[topic("s", relationships=[related("n")]), topic("n")],
        explorations=[
            exploration("e1", "s", "PAUSED"),
            exploration("e2", "s", "COMPLETED"),
        ],
    )
    assert history_continuation_nominations(sim) == []


# ---------------------------------------------------------------------------
# REVISIT
# ---------------------------------------------------------------------------


def test_revisit_completed_target_nominated():
    sim = make_input(
        entities=[topic("s")],
        explorations=[exploration("e1", "s", "COMPLETED", completed_at="2026-01-01T01:00:00Z")],
    )
    nominations = revisit_nominations(sim)
    assert [n["target_entity_id"] for n in nominations] == ["s"]
    assert nominations[0]["provenance"]["status"] == "COMPLETED"


def test_revisit_active_and_paused_emit_nothing():
    sim = make_input(
        entities=[topic("s")],
        explorations=[exploration("e1", "s", "ACTIVE"), exploration("e2", "s", "PAUSED")],
    )
    assert revisit_nominations(sim) == []


def test_frozen_source_order():
    assert CANDIDATE_SOURCES == (
        "GRAPH",
        "SEMANTIC",
        "EXPLICIT_INTEREST",
        "HISTORY_CONTINUATION",
        "REVISIT",
    )
