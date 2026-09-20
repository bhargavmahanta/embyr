"""Structural offline and scope guards for the #46 simulator package (IN-9)."""

from __future__ import annotations

import ast
from pathlib import Path

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.simulator import generate_candidates

SIMULATOR_DIR = Path(__file__).resolve().parents[1] / "simulator"

FORBIDDEN_MODULE_ROOTS = frozenset(
    {
        "requests",
        "httpx",
        "socket",
        "urllib",
        "http",
        "ssl",
        "supabase",
        "storage3",
        "psycopg",
        "psycopg2",
        "sqlalchemy",
        "asyncpg",
        "openai",
        "anthropic",
        "boto3",
        "google",
    }
)

FORBIDDEN_ATTRIBUTES = frozenset(
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

FORBIDDEN_OUTPUT_KEYS = ("pre_rerank_score", "ordering_score", "final_rank", "score_trace", "rerank_trace")


def _source_files() -> list[Path]:
    return sorted(SIMULATOR_DIR.glob("*.py"))


def _import_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            roots.add(node.module.split(".")[0])
    return roots


def _attributes(tree: ast.AST) -> set[str]:
    return {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES
    }


def test_simulator_package_has_sources():
    assert _source_files()


def test_no_forbidden_imports():
    violations = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _import_roots(tree) & FORBIDDEN_MODULE_ROOTS
        if bad:
            violations[path.name] = bad
    assert violations == {}


def test_no_nondeterministic_apis():
    violations = {}
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bad = _attributes(tree)
        if bad:
            violations[path.name] = bad
    assert violations == {}


def test_candidate_output_has_no_scoring_fields():
    for scenario_id, simulation_input in SCENARIOS.items():
        for candidate in generate_candidates(simulation_input):
            for forbidden in FORBIDDEN_OUTPUT_KEYS:
                assert forbidden not in candidate, (scenario_id, forbidden)
