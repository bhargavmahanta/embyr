"""Frozen v1 identities reject changes to checked-in policy content."""
from __future__ import annotations

import json

import pytest

from app.recommendation import persistence, retrieval, service


def _mutated_file(monkeypatch, tmp_path, module, path_name, keys, value):
    profile = json.loads(getattr(module, path_name).read_text(encoding="utf-8"))
    target = profile
    for key in keys[:-1]:
        target = target[key]
    target[keys[-1]] = value
    path = tmp_path / "mutated-policy.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(module, path_name, path)


RETRIEVAL_MUTATIONS = [
    (("policy_version",), "recommendation-retrieval/v2"),
    (("embedding", "provider"), "other-provider"),
    (("embedding", "model"), "other-model"),
    (("embedding", "dimension"), 512),
    (("embedding", "metric"), "dot"),
    (("embedding", "document_input_type"), "query"),
    (("embedding", "query_input_type"), "document"),
    (("embedding", "query_input_version"), "semantic-query-text/v2"),
    (("embedding", "query_text_template"), "{canonical_title}"),
    (("embedding", "document_input_version"), "ontology-entity/v2"),
    (("embedding", "document_text_template"), "{canonical_summary}"),
    (("semantic", "search"), "ann"),
    (("semantic", "minimum_cosine_similarity"), 0.99),
    (("semantic", "max_candidates"), 41),
    (("semantic", "query_per_anchor"), False),
    (("graph", "relationship"), "OTHER"),
    (("graph", "bidirectional"), False),
    (("graph", "max_hops"), 3),
    (("graph", "max_candidates"), 101),
    (("graph", "tie_break"), "other"),
    (("semantic", "query_per_anchor"), 1),
    (("embedding", "dimension"), 1024.0),
    (("graph", "bidirectional"), 1),
    (("extra",), True),
]


@pytest.mark.parametrize("keys,value", RETRIEVAL_MUTATIONS)
def test_retrieval_loader_rejects_same_version_mutations(monkeypatch, tmp_path, keys, value):
    _mutated_file(monkeypatch, tmp_path, retrieval, "PROFILE_PATH", keys, value)
    with pytest.raises(ValueError, match="unsupported retrieval policy"):
        retrieval.load_retrieval_policy()


def test_exact_checked_in_retrieval_profile_loads():
    assert retrieval.load_retrieval_policy()["policy_version"] == "recommendation-retrieval/v1"


DISTANCE_MUTATIONS = [
    (("policy_version",), "distance-band/v2"),
    (("meaning",), "changed meaning"),
    (("precedence",), ["WILD", "FRONTIER", "ADJACENT", "COMFORT"]),
    (("comfort_sources",), ["REVISIT"]),
    (("adjacent", "graph_hops"), 2),
    (("adjacent", "minimum_cosine_similarity"), 0.81),
    (("frontier", "graph_hops"), 3),
    (("frontier", "minimum_cosine_similarity"), 0.66),
    (("frontier", "maximum_cosine_similarity_exclusive"), 0.81),
    (("wild", "minimum_cosine_similarity"), 0.56),
    (("wild", "maximum_cosine_similarity_exclusive"), 0.66),
    (("no_qualifying_signal",), "WILD"),
    (("uses_readiness",), True),
    (("uses_difficulty_fit",), True),
    (("uses_final_score_or_rank",), True),
    (("uses_readiness",), 0),
    (("adjacent", "graph_hops"), 1.0),
    (("extra",), True),
]


@pytest.mark.parametrize("keys,value", DISTANCE_MUTATIONS)
def test_distance_loader_rejects_same_version_mutations(monkeypatch, tmp_path, keys, value):
    _mutated_file(monkeypatch, tmp_path, service, "BAND_PATH", keys, value)
    with pytest.raises(ValueError, match="unsupported distance-band policy"):
        service.load_distance_band_policy()


def test_exact_checked_in_distance_profile_loads():
    assert service.load_distance_band_policy()["policy_version"] == "distance-band/v1"


COPY_CODES = [
    "EXPLICIT_INTEREST_MATCH", "RELATED_TO_RECENT_EXPLORATION",
    "PREREQUISITES_SATISFIED", "GOOD_DIFFICULTY_FIT",
    "SEMANTICALLY_RELATED", "REVISIT_OPPORTUNITY",
    "DIVERSITY_ADJUSTMENT", "EXPLICIT_PREFERENCE_OVERRIDES_INFERRED",
]


@pytest.mark.parametrize("code", COPY_CODES)
@pytest.mark.parametrize("field", ["hook", "reason"])
def test_copy_loader_rejects_each_template_mutation(monkeypatch, tmp_path, code, field):
    _mutated_file(
        monkeypatch, tmp_path, persistence, "COPY_PATH",
        ("templates", code, field), "changed copy",
    )
    with pytest.raises(ValueError, match="unsupported recommendation copy version"):
        persistence.load_copy_policy()


@pytest.mark.parametrize("mutation", [
    "unknown-version", "removed-code", "extra-code", "renamed-code",
    "missing-hook", "missing-reason", "extra-template-key", "extra-top-level-key",
])
def test_copy_loader_rejects_structure_mutations(monkeypatch, tmp_path, mutation):
    profile = json.loads(persistence.COPY_PATH.read_text(encoding="utf-8"))
    templates = profile["templates"]
    code = "EXPLICIT_INTEREST_MATCH"
    if mutation == "unknown-version":
        profile["copy_version"] = "recommendation-copy/v2"
    elif mutation == "removed-code":
        del templates[code]
    elif mutation == "extra-code":
        templates["UNREVIEWED_CODE"] = {"hook": "New", "reason": "New."}
    elif mutation == "renamed-code":
        templates["RENAMED_CODE"] = templates.pop(code)
    elif mutation == "missing-hook":
        del templates[code]["hook"]
    elif mutation == "missing-reason":
        del templates[code]["reason"]
    elif mutation == "extra-template-key":
        templates[code]["extra"] = "unreviewed"
    else:
        profile["extra"] = "unreviewed"
    path = tmp_path / "mutated-copy.json"
    path.write_text(json.dumps(profile), encoding="utf-8")
    monkeypatch.setattr(persistence, "COPY_PATH", path)
    with pytest.raises(ValueError, match="unsupported recommendation copy version"):
        persistence.load_copy_policy()


def test_exact_checked_in_copy_profile_loads():
    copy = persistence.load_copy_policy()
    assert copy["copy_version"] == "recommendation-copy/v1"
    assert set(copy["templates"]) == set(COPY_CODES)
