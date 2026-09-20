"""#49 offline/determinism guard for the runtime simulator modules (IN-9)."""

from __future__ import annotations

from pathlib import Path

from research.recommendation.fixtures import SCENARIOS
from research.recommendation.simulator import run_simulation
from research.recommendation.simulator.invariants import (
    FORBIDDEN_MODULE_ROOTS,
    _scan_simulator_modules,
    scan_source,
)

SIMULATOR_DIR = Path(__file__).resolve().parents[1] / "simulator"
RUNTIME_MODULES = ("run.py", "metrics.py", "invariants.py", "evaluate.py")


def test_runtime_modules_exist():
    for module in RUNTIME_MODULES:
        assert (SIMULATOR_DIR / module).exists(), module


def test_no_forbidden_imports_or_nondeterminism_in_simulator_modules():
    assert _scan_simulator_modules() == []


def test_scan_source_detects_synthetic_violations():
    assert scan_source("import socket\n", "x.py") == ["x.py:import:socket"]
    assert "x.py:attr:uuid4" in scan_source("import uuid\nuuid.uuid4()\n", "x.py")
    assert scan_source("import math\nvalue = math.sqrt(4.0)\n", "x.py") == []


def test_scan_source_detects_forbidden_importfrom_symbols():
    assert scan_source("from time import time\ntime()\n", "x.py") == [
        "x.py:import:time.time"
    ]
    assert scan_source("from time import time as clock\nclock()\n", "x.py") == [
        "x.py:import:time.time"
    ]
    assert scan_source("from uuid import uuid4\nuuid4()\n", "x.py") == [
        "x.py:import:uuid.uuid4"
    ]
    assert scan_source("from random import choice\nchoice([1, 2])\n", "x.py") == [
        "x.py:import:random.choice"
    ]
    assert scan_source("from math import sqrt\nsqrt(4)\n", "x.py") == []


def test_forbidden_policy_includes_core_external_roots():
    for root in ("requests", "httpx", "socket", "openai", "supabase", "psycopg"):
        assert root in FORBIDDEN_MODULE_ROOTS


def test_in9_reported_pass_with_no_external_calls():
    result = run_simulation(SCENARIOS["scn-A-explicit-more-001"])
    in9 = next(i for i in result["invariant_results"] if i["invariant_code"] == "IN-9")
    assert in9["status"] == "PASS"
    assert in9["diagnostics"]["external_calls"] == 0


def test_execution_metadata_is_empty_and_timeless():
    result = run_simulation(SCENARIOS["scn-A-explicit-more-001"])
    assert result["execution_metadata"] == {}
    assert not ({"started_at", "finished_at", "duration_ms", "host", "run_id"} & set(result))
