"""Structural offline and determinism checks for the fixture package (IN-9).

The fixture corpus must be reproducible with no external model, network, or
database dependency. These checks scan the package source rather than trusting
imports at runtime.
"""

from __future__ import annotations

import ast
from pathlib import Path

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.fixtures.canonical import canonical_json

FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures"

FORBIDDEN_MODULE_ROOTS = frozenset(
    {
        "requests",
        "httpx",
        "aiohttp",
        "urllib",
        "http",
        "socket",
        "ssl",
        "ftplib",
        "smtplib",
        "supabase",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "asyncpg",
        "storage3",
        "openai",
        "anthropic",
        "boto3",
        "google",
        "testcontainers",
    }
)

WALL_CLOCK_ATTRIBUTES = frozenset(
    {
        "now",
        "today",
        "utcnow",
        "time",
        "monotonic",
        "urandom",
        "getrandbits",
        "random",
        "randint",
        "randrange",
        "choice",
        "shuffle",
        "sample",
        "uuid4",
        "uuid1",
        "token_hex",
        "token_bytes",
    }
)


def _fixture_source_files() -> list[Path]:
    return sorted(path for path in FIXTURES_DIR.glob("*.py"))


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def _nondeterministic_attributes(tree: ast.AST) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in WALL_CLOCK_ATTRIBUTES:
            found.add(node.attr)
    return found


def test_fixture_package_has_sources():
    assert _fixture_source_files(), "expected fixture package sources"


def test_no_forbidden_imports_in_fixture_package():
    violations: dict[str, set[str]] = {}
    for path in _fixture_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _import_roots(tree) & FORBIDDEN_MODULE_ROOTS
        if bad:
            violations[path.name] = bad
    assert violations == {}


def test_no_nondeterministic_apis_in_fixture_package():
    violations: dict[str, set[str]] = {}
    for path in _fixture_source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _nondeterministic_attributes(tree)
        if bad:
            violations[path.name] = bad
    assert violations == {}


def test_no_execution_metadata_key_in_scenarios():
    for scenario_id, simulation_input in SCENARIOS.items():
        assert "execution_metadata" not in canonical_json(simulation_input), scenario_id


def test_no_expectation_metadata_key_in_scenarios():
    for scenario_id, simulation_input in SCENARIOS.items():
        serialized = canonical_json(simulation_input)
        for forbidden in ("hard_expectations", "relative_expectations", "descriptive_observations"):
            assert forbidden not in serialized, (scenario_id, forbidden)


def test_no_hosted_identifiers_in_scenarios():
    hosted_markers = ("supabase.co", "supabase.in", "http://", "https://")
    for scenario_id, simulation_input in SCENARIOS.items():
        serialized = canonical_json(simulation_input)
        for marker in hosted_markers:
            assert marker not in serialized, (scenario_id, marker)
