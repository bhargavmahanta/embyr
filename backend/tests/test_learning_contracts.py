import json
from pathlib import Path

from app.api.learning_dtos import (
    DeliveryDTO,
    ExplorationDetailDTO,
    AssessmentSessionDTO,
    EvaluationRetryDTO,
)
from app.learning.content import load_package, public_delivery


def test_public_delivery_schema_cannot_contain_private_mapping():
    definition = load_package()["definitions"][0]
    parsed = DeliveryDTO.model_validate(public_delivery(definition))
    encoded = parsed.model_dump(mode="json")
    assert "assessment" not in encoded
    assert "option_results" not in json.dumps(encoded)


def test_client_fixtures_match_frozen_public_response_schemas():
    examples = json.loads(
        (
            Path(__file__).parents[2] / "docs/api/fixtures/learning-lifecycle-v1.json"
        ).read_text()
    )
    for model, key in [
        (ExplorationDetailDTO, "exploration"),
        (AssessmentSessionDTO, "session"),
        (EvaluationRetryDTO, "retry"),
    ]:
        assert (
            model.model_validate(examples[key]).model_dump(mode="json") == examples[key]
        )
