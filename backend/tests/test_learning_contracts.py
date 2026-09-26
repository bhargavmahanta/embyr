import json
import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.api.errors import AppError
from app.api.learning import list_explorations

from app.api.learning_dtos import (
    DeliveryDTO,
    ExplorationDetailDTO,
    AssessmentSessionDTO,
    EvaluationRetryDTO,
)
from app.learning.content import load_package, public_delivery


@pytest.mark.parametrize(
    "payload",
    [
        ["2026-09-26T12:00:00+00:00", 1],
        ["2026-09-26T12:00:00+00:00", []],
        {"2026-09-26T12:00:00+00:00": "unused", str(uuid4()): "unused"},
        ["2026-09-26T12:00:00", str(uuid4())],
    ],
)
def test_malformed_pagination_cursor_returns_validation_error(payload):
    cursor = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    with pytest.raises(AppError) as error:
        asyncio.run(
            list_explorations(
                SimpleNamespace(user_id=uuid4()),
                None,
                status=None,
                limit=50,
                cursor=cursor,
            )
        )
    assert error.value.status == 422 and error.value.code == "INVALID_CURSOR"


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
