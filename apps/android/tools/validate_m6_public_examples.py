"""Validate canonical public M6 examples against their individual schema definitions."""

import json
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "docs/api/schemas/m6-v1.schema.json"
FIXTURE_PATH = ROOT / "docs/api/fixtures/m6-v1.json"


def definition_for(name: str) -> str:
    if name.startswith("memory"):
        return "memorySummary"
    if name.startswith("world"):
        return "worldSnapshot"
    if name.startswith("delta"):
        return "worldDeltaPage"
    if name.startswith("resync"):
        return "worldResyncRequired"
    raise ValueError(f"Unreviewed M6 public example: {name}")


def main() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    examples = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["public_examples"]
    if len(examples) != 12:
        raise ValueError(f"Expected 12 reviewed public examples, got {len(examples)}")
    for name, wrapped in examples.items():
        definition = wrapped.get("schema", definition_for(name))
        value = wrapped.get("value", wrapped)
        Draft202012Validator(
            {"$ref": f"#/$defs/{definition}", "$defs": schema["$defs"]},
            format_checker=FormatChecker(),
        ).validate(value)
    print(f"Validated {len(examples)} canonical M6 public examples")


if __name__ == "__main__":
    main()
