from copy import deepcopy

import pytest

from app.learning.content import load_package
from app.learning.evaluation import evaluate, PermanentEvaluationError


@pytest.mark.parametrize(
    "result,confidence,evidence",
    [
        ("SUPPORTED", 1.0, True),
        ("INSUFFICIENT_EVIDENCE", 1.0, False),
        ("UNCERTAIN", 0.0, False),
    ],
)
def test_pinned_mapping_is_deterministic_and_evidence_is_weak_only_when_supported(
    result, confidence, evidence
):
    prompt = load_package()["definitions"][0]["assessment"]
    option = next(
        key
        for key, value in prompt["option_results"].items()
        if value["result"] == result
    )
    first = evaluate(prompt, {"option_id": option}, "EXPLANATION")
    assert first == evaluate(deepcopy(prompt), {"option_id": option}, "EXPLANATION")
    assert first.result == result and first.confidence == confidence
    assert first.produces_evidence is evidence
    assert first.feedback == prompt["option_results"][option]["feedback"]


def test_malformed_pinned_mapping_is_permanent_failure():
    prompt = deepcopy(load_package()["definitions"][0]["assessment"])
    prompt["option_results"] = {}
    with pytest.raises(PermanentEvaluationError):
        evaluate(prompt, {"option_id": "unknown"}, None)
