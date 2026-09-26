import json
import logging
import asyncio
import base64
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.deps import get_principal
from app.api.errors import AppError, register_exception_handlers
from app.api.learning import list_explorations, router
from app.learning.transactions import get_learning_session

from app.api.learning_dtos import (
    DeliveryDTO,
    ExplorationDetailDTO,
    AssessmentSessionDTO,
    EvaluationRetryDTO,
)
from app.learning.content import load_package, public_delivery
from app.learning.telemetry import LearningJSONFormatter


def test_structured_telemetry_keeps_correlation_and_excludes_private_fields():
    record = logging.LogRecord(
        "learning", logging.INFO, "", 0, "learning_event_staged", (), None
    )
    record.request_id = "request-reference"
    record.evaluation_run_id = "run-reference"
    record.content_version = 1
    record.option_id = "SECRET_ANSWER"
    record.reflection_text = "SECRET_REFLECTION"
    record.exc_info = (Exception, Exception("SECRET_DIAGNOSTIC"), None)
    encoded = LearningJSONFormatter().format(record)
    parsed = json.loads(encoded)
    assert parsed["request_id"] == "request-reference"
    assert parsed["evaluation_run_id"] == "run-reference"
    assert parsed["content_version"] == 1
    assert "SECRET" not in encoded


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


@pytest.fixture
def exploration_page_client():
    app = FastAPI()
    app.include_router(router)
    register_exception_handlers(app)
    principal = SimpleNamespace(user_id=uuid4())
    session = SimpleNamespace(scalars=AsyncMock())
    app.dependency_overrides[get_principal] = lambda: principal
    app.dependency_overrides[get_learning_session] = lambda: session
    with TestClient(app) as client:
        yield client, session, principal


@pytest.mark.parametrize("cursor", ["a", "abcde", "ab", "abc", "-", "_"])
def test_malformed_base64_cursor_returns_http_invalid_cursor(
    exploration_page_client, cursor
):
    client, session, _ = exploration_page_client
    response = client.get("/api/v1/explorations", params={"cursor": cursor})
    assert response.status_code == 422
    assert response.headers["content-type"] == "application/json"
    assert response.json()["code"] == "INVALID_CURSOR"
    session.scalars.assert_not_awaited()


def test_valid_pagination_cursor_preserves_next_page_boundary(exploration_page_client):
    client, session, principal = exploration_page_client
    timestamp = datetime(2026, 9, 26, 12, tzinfo=timezone.utc)
    rows = [
        SimpleNamespace(
            id=uuid4(),
            entity_id=uuid4(),
            entity_version=1,
            recommendation_id=None,
            practical_challenge_id=None,
            practical_challenge_version_id=None,
            learning_intent="DIRECT_INTEREST",
            status="ACTIVE",
            started_at=timestamp,
            returned_at=None,
            paused_at=None,
            completed_at=None,
            version=1,
        )
        for _ in range(2)
    ]
    rows.sort(key=lambda row: row.id, reverse=True)
    session.scalars.side_effect = [Mock(all=lambda: rows), Mock(all=lambda: rows[1:])]
    first = client.get("/api/v1/explorations", params={"limit": 1})
    assert first.status_code == 200
    assert [item["id"] for item in first.json()["items"]] == [str(rows[0].id)]
    cursor = first.json()["next_cursor"]
    assert json.loads(base64.urlsafe_b64decode(cursor)) == [
        timestamp.isoformat(),
        str(rows[0].id),
    ]
    second = client.get("/api/v1/explorations", params={"limit": 1, "cursor": cursor})
    assert second.status_code == 200
    assert [item["id"] for item in second.json()["items"]] == [str(rows[1].id)]
    assert second.json()["next_cursor"] is None
    query = session.scalars.await_args.args[0].compile()
    assert query.params == {
        "user_id_1": principal.user_id,
        "started_at_1": timestamp,
        "started_at_2": timestamp,
        "id_1": rows[0].id,
        "param_1": 2,
    }
    assert "ORDER BY explorations.started_at DESC, explorations.id DESC" in str(query)


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
