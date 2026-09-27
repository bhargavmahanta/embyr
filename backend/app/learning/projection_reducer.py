"""Pure complete-prefix reduction. No database, clock, claim or mutable sources."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.learning.projection_inputs import (
    CONTRACTS,
    ProjectionError,
    parse_receipt,
    require,
    uuid_text,
)
from app.learning.world_projection import (
    fingerprint,
    node_object,
    region_object,
    semantic_node,
    world_id,
    world_seed,
)

__all__ = ["Projection", "ProjectionError", "reduce_prefix"]


@dataclass(frozen=True)
class Projection:
    user_id: str
    horizon: int
    root: bool
    objectives: list[dict]
    provenance: list[tuple[str, str]]
    regions: list[dict]
    nodes: list[dict]
    input_fingerprint: str
    output_fingerprint: str


def reduce_prefix(user_id, receipts) -> Projection:
    user_id = uuid_text(str(user_id))
    rows = []
    keys = set()
    closed_groups = set()
    group = None
    starts = {}
    pins = {}
    sprouts = set()
    current = {}
    evidence_times = {}
    lineage = {}
    root = False
    for seq, raw in enumerate(receipts, 1):
        r = parse_receipt(user_id, raw)
        require(r["source_sequence"] == seq, "PREFIX_GAP")
        identity = (r["source_kind"], r["source_key"])
        require(identity not in keys, "DUPLICATE_SOURCE")
        keys.add(identity)
        if r["source_group"] != group:
            if group is not None:
                closed_groups.add(group)
            require(r["source_group"] not in closed_groups, "SPLIT_GROUP")
            group = r["source_group"]
        rows.append(r)
        f = r["facts"]
        if r["source_kind"] == "LEDGER":
            ex = f["exploration_id"]
            if ex:
                pin = (f["entity_id"], f["entity_version"])
                require(ex not in lineage or lineage[ex] == pin, "RECEIPT_LINEAGE")
                lineage[ex] = pin
            event = f["event_type"]
            if event == "ONBOARDING_COMPLETED":
                root = True
            if event == "EXPLORATION_STARTED":
                require(ex not in starts, "DUPLICATE_START")
                starts[ex] = r
                root = True
            if event in ["REFLECTION_SUBMITTED", "EXPLORATION_COMPLETED"]:
                sprouts.add((f["entity_id"], f["entity_version"]))
        elif r["source_kind"] == "BOOTSTRAP":
            root = True
        else:
            evid = f["evidence_id"]
            previous = current.get(evid)
            if previous:
                stable = {
                    k: v
                    for k, v in previous.items()
                    if k
                    not in ["resulting_status", "evaluation_status", "transition_at"]
                }
                now = {
                    k: v
                    for k, v in f.items()
                    if k
                    not in ["resulting_status", "evaluation_status", "transition_at"]
                }
                require(stable == now, "EVIDENCE_LINEAGE")
                require(
                    previous["resulting_status"] == "ACTIVE"
                    or (
                        previous["resulting_status"] == "SUPERSEDED"
                        and f["resulting_status"] == "REVOKED"
                    ),
                    "EVIDENCE_TRANSITION",
                )
            current[evid] = f
            require(
                evid not in evidence_times or evidence_times[evid] == r["source_time"],
                "EVIDENCE_LINEAGE",
            )
            if evid not in evidence_times:
                evidence_times[evid] = r["source_time"]
    require(set(lineage) == set(starts), "MISSING_START")
    # Starts were collected in immutable source-sequence order. Rank only
    # after every encountered Exploration has its unique canonical start.
    for start in starts.values():
        facts = start["facts"]
        pins.setdefault(facts["entity_id"], facts["entity_version"])
    eligible = {}
    responses = set()
    young = set()
    for evid, f in sorted(current.items()):
        c = f["classification_confidence"]
        if (
            f["resulting_status"] == "ACTIVE"
            and f["evaluation_status"] == "SUCCEEDED"
            and f["evaluation_result"] == "SUPPORTED"
            and f["evaluator_version"] == "deterministic-evaluation/v1"
            and c is not None
        ):
            require(f["response_id"] not in responses, "DUPLICATE_RESPONSE")
            responses.add(f["response_id"])
            eligible.setdefault(f["objective_id"], []).append(
                (evid, f, evidence_times[evid])
            )
            young.add((f["entity_id"], f["entity_version"]))
    objectives = []
    provenance = []
    for objective, sources in sorted(eligible.items()):
        require(
            len({(f["entity_id"], f["entity_version"]) for _, f, _ in sources}) == 1,
            "OBJECTIVE_LINEAGE",
        )
        objectives.append(
            {
                "objective_id": objective,
                "categorical_state": "DEVELOPING",
                "understanding_estimate": None,
                "evidence_count": len(sources),
                "evaluation_confidence": min(
                    f["classification_confidence"] for _, f, _ in sources
                ),
                "support_required": any(
                    f["support_level"] is not None for _, f, _ in sources
                ),
                "last_evidence_at": max(
                    (t for _, _, t in sources), key=datetime.fromisoformat
                ),
                "model_version": CONTRACTS["learner"],
            }
        )
        provenance.extend((objective, evid) for evid, _, _ in sources)
    nodes = []
    for entity, version in sorted(pins.items()):
        growth = (
            "YOUNG"
            if (entity, version) in young
            else "SPROUT"
            if (entity, version) in sprouts
            else "SEED"
        )
        nodes.append(node_object(user_id, entity, version, growth))
    regions = [region_object(user_id)] if nodes else []
    semantics = {
        "root": {
            "id": str(world_id(user_id)),
            "generation_seed": world_seed(world_id(user_id)),
            "layout_version": 1,
        }
        if root
        else None,
        "objectives": objectives,
        "provenance": provenance,
        "regions": regions,
        "nodes": [semantic_node(n) for n in nodes],
        "connections": [],
        "artifacts": [],
    }
    return Projection(
        user_id,
        len(rows),
        root,
        objectives,
        provenance,
        regions,
        nodes,
        fingerprint({"contracts": CONTRACTS, "receipts": rows}),
        fingerprint(semantics),
    )
