"""#49 runner determinism, fingerprint behavior, and IN-1 non-recursion."""

from __future__ import annotations

import copy

from research.recommendation.fixtures import SCENARIOS, build_scenario
from research.recommendation.simulator import input_fingerprint, run_simulation
from research.recommendation.simulator.identity import canonical_json

SCENARIO = "scn-R-multisource-duplicate-001"


def test_repeated_execution_is_byte_equivalent():
    simulation_input = SCENARIOS[SCENARIO]
    first = run_simulation(simulation_input)
    second = run_simulation(simulation_input)
    assert canonical_json(first) == canonical_json(second)


def test_key_insertion_order_does_not_change_result():
    simulation_input = build_scenario(SCENARIO)
    permuted = dict(reversed(list(simulation_input.items())))
    assert canonical_json(run_simulation(permuted)) == canonical_json(
        run_simulation(simulation_input)
    )


def test_fingerprint_key_order_independent_and_config_sensitive():
    simulation_input = build_scenario(SCENARIO)
    permuted = dict(reversed(list(simulation_input.items())))
    assert input_fingerprint(permuted) == input_fingerprint(simulation_input)

    other_top_k = copy.deepcopy(simulation_input)
    other_top_k["simulation_config"]["top_k"] += 1
    assert input_fingerprint(other_top_k) != input_fingerprint(simulation_input)

    other_config = copy.deepcopy(simulation_input)
    other_config["simulation_config"]["config_version"] = "m3-sim-config/edited"
    assert input_fingerprint(other_config) != input_fingerprint(simulation_input)


def test_in1_is_non_recursive(monkeypatch):
    import research.recommendation.simulator.run as run_module

    calls = {"core": 0, "invariants": 0}
    original_core = run_module._execute_core
    original_invariants = run_module.evaluate_invariants

    def counting_core(simulation_input):
        calls["core"] += 1
        return original_core(simulation_input)

    def counting_invariants(core, second):
        calls["invariants"] += 1
        return original_invariants(core, second)

    monkeypatch.setattr(run_module, "_execute_core", counting_core)
    monkeypatch.setattr(run_module, "evaluate_invariants", counting_invariants)

    run_module.run_simulation(SCENARIOS[SCENARIO])

    assert calls["core"] == 2
    assert calls["invariants"] == 1
