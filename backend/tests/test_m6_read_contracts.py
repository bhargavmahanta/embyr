"""Frozen public fixtures, closed DTOs, query grammar and OpenAPI."""

import json
from pathlib import Path

import pytest
from app.api.m6_read_dtos import (
    MemorySummary,
    WorldDeltaPage,
    WorldSnapshot,
)
from app.api.m6_reads import query_integer
from app.config import Settings
from app.main import create_app
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

ROOT = Path(__file__).parents[2]
SCHEMA = json.loads((ROOT / "docs/api/schemas/m6-v1.schema.json").read_text())
FIXTURES = json.loads((ROOT / "docs/api/fixtures/m6-v1.json").read_text())[
    "public_examples"
]


def validate(name, obj):
    Draft202012Validator(
        {"$ref": "#/$defs/" + name, "$defs": SCHEMA["$defs"]},
        format_checker=FormatChecker(),
    ).validate(obj)


@pytest.mark.parametrize("name", list(FIXTURES))
def test_frozen_public_examples(name):
    example = FIXTURES[name]
    schema_name = example.get("schema")
    value = example.get("value", example)
    if schema_name is None:
        schema_name = (
            "memorySummary"
            if name.startswith("memory")
            else "worldSnapshot"
            if name.startswith("world")
            else "worldResyncRequired"
            if "resync" in name
            else "worldDeltaPage"
        )
    validate(schema_name, value)
    model = {
        "memorySummary": MemorySummary,
        "worldSnapshot": WorldSnapshot,
        "worldDeltaPage": WorldDeltaPage,
    }.get(schema_name)
    if model:
        result = model.model_validate_json(json.dumps(value)).model_dump(mode="json")
        assert result == value
        bad = dict(value, private_metadata="private sentinel")
        with pytest.raises(ValidationError):
            model.model_validate_json(json.dumps(bad))


@pytest.mark.parametrize(
    "raw", ["-1", "1.0", "1e0", "true", "false", "+1", " 1", "1 ", "١", "１", ""]
)
def test_query_grammar_rejects_non_ascii_integers(raw):
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        query_integer(raw, minimum=0, maximum=9223372036854775807)


@pytest.mark.parametrize("raw", ["1001", "9223372036854775808", "9" * 5000])
def test_large_positive_limits_clamp_before_binding(raw):
    assert query_integer(raw, minimum=1) == 1000


def test_openapi_closed_response_models():
    app = create_app(
        settings=Settings(
            database_url="postgresql+psycopg://example/test?sslmode=require",
            supabase_auth_issuer="https://example.test/auth/v1",
        ),
        session_factory=object(),
        verifier=object(),
    )
    schema = app.openapi()
    for path, model in [
        ("/api/v1/memory/summary", "MemorySummary"),
        ("/api/v1/world", "WorldSnapshot"),
        ("/api/v1/world/changes", "WorldDeltaPage"),
    ]:
        assert schema["paths"][path]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]["$ref"].endswith("/" + model)
    for name in [
        "MemorySummary",
        "Projection",
        "Preferences",
        "ExplicitInterest",
        "RecentExploration",
        "RecognitionEvidence",
        "Truncated",
        "WorldSnapshot",
        "Region",
        "Node",
        "WorldChange",
        "RegionPayload",
        "NodePayload",
        "WorldDeltaPage",
    ]:
        assert schema["components"]["schemas"][name]["additionalProperties"] is False


def test_dtos_reject_naive_times_and_string_coordinates():
    m = json.loads(json.dumps(FIXTURES["memory_current"]))
    m["explicit_interests"][0]["updated_at"] = "2026-01-01T00:00:00"
    with pytest.raises(ValidationError):
        MemorySummary.model_validate(m)
    w = json.loads(json.dumps(FIXTURES["world_populated"]))
    w["nodes"][0]["logical_x"] = "0.25"
    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(w)


def test_nested_private_metadata_and_bad_delta_identity_rejected():
    m = json.loads(json.dumps(FIXTURES["memory_current"]))
    m["recognition_evidence"][0]["evaluation_confidence"] = 0.8
    with pytest.raises(ValidationError):
        MemorySummary.model_validate(m)
    d = json.loads(json.dumps(FIXTURES["delta_multiple_changes"]))
    d["changes"][0]["object_id"] = "ffffffff-ffff-4fff-8fff-ffffffffffff"
    with pytest.raises(ValidationError):
        WorldDeltaPage.model_validate(d)


@pytest.mark.parametrize("field", ["layout_version", "region_coordinate", "node_depth"])
def test_numeric_constants_reject_boolean_payloads(field):
    world = json.loads(json.dumps(FIXTURES["world_populated"]))
    if field == "layout_version":
        world["layout_version"] = True
    elif field == "region_coordinate":
        world["regions"][0]["logical_x"] = False
    else:
        world["nodes"][0]["depth"] = False
    with pytest.raises(ValidationError):
        WorldSnapshot.model_validate(world)
