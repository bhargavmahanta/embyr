"""Structural offline/scope guards for the #48 explanation module (IN-9)."""

from __future__ import annotations

import ast
from pathlib import Path

SIMULATOR_DIR = Path(__file__).resolve().parents[1] / "simulator"
MODULES = ("explain.py",)

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


def _path(module: str) -> Path:
    return SIMULATOR_DIR / module


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


def test_explain_module_exists():
    for module in MODULES:
        assert _path(module).exists(), module


def test_no_forbidden_imports():
    violations = {}
    for module in MODULES:
        tree = ast.parse(_path(module).read_text(encoding="utf-8"))
        bad = _import_roots(tree) & FORBIDDEN_MODULE_ROOTS
        if bad:
            violations[module] = bad
    assert violations == {}


def test_no_nondeterministic_apis():
    violations = {}
    for module in MODULES:
        tree = ast.parse(_path(module).read_text(encoding="utf-8"))
        bad = _attributes(tree)
        if bad:
            violations[module] = bad
    assert violations == {}


def test_no_human_readable_prose_in_output():
    source = _path("explain.py").read_text(encoding="utf-8").lower()
    for phrase in ("because", "recommended because", "you might like"):
        assert phrase not in source, phrase
