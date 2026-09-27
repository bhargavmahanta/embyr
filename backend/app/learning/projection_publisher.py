"""Publication under the worker's owner/checkpoint/World/job fences.

No factual writes, operational source locks, commits or ownership inference.
"""

from __future__ import annotations

import math
from datetime import datetime
from uuid import UUID

from sqlalchemy import text

from app.learning.projection_inputs import require, timestamp
from app.learning.projection_loader import public_values
from app.learning.world_projection import (
    canonical_json,
    region_object,
    semantic_node,
    world_id,
    world_seed,
)

REGION_KEYS = set(region_object("11111111-1111-4111-8111-111111111111"))
NODE_KEYS = {
    "id",
    "entity_id",
    "entity_version",
    "region_id",
    "logical_x",
    "logical_y",
    "depth",
    "visual_archetype",
    "visual_seed",
    "growth_state",
    "revision",
}
OBJECTIVE_KEYS = {
    "objective_id",
    "categorical_state",
    "understanding_estimate",
    "evidence_count",
    "evaluation_confidence",
    "support_required",
    "last_evidence_at",
    "model_version",
}


async def _rows(session, table, user, columns="*"):
    result = await session.execute(
        text(f"select {columns} from {table} where user_id=:u"), {"u": user}
    )
    return [public_values(dict(row)) for row in result.mappings()]


def _objects(rows, keys):
    return [{key: row[key] for key in keys} for row in rows]


def _params(obj):
    return {
        key: UUID(value)
        if value is not None and (key == "id" or key.endswith("_id"))
        else value
        for key, value in obj.items()
    }


async def verify_existing(session, prior, root):
    """Refuse incompatible/unknown projections rather than adopt or wipe them."""
    user = UUID(prior.user_id)
    states = _objects(
        await _rows(session, "learner_objective_state", user), OBJECTIVE_KEYS
    )
    for obj in states:
        if obj["last_evidence_at"] is not None:
            obj["last_evidence_at"] = timestamp(obj["last_evidence_at"])
    require(
        sorted(states, key=lambda o: o["objective_id"]) == prior.objectives,
        "UNKNOWN_PROVENANCE",
    )
    links = await _rows(session, "state_evidence_links", user)
    links = [r for r in links if r["state_dimension"] == "OBJECTIVE"]
    require(
        all(
            r["learning_event_id"] is None
            and r["weight"] is None
            and r["learning_evidence_id"] is not None
            for r in links
        ),
        "UNKNOWN_PROVENANCE",
    )
    require(
        sorted((r["target_id"], r["learning_evidence_id"]) for r in links)
        == prior.provenance,
        "UNKNOWN_PROVENANCE",
    )
    regions = _objects(await _rows(session, "world_regions", user), REGION_KEYS)
    nodes = _objects(await _rows(session, "world_nodes", user), NODE_KEYS)
    require(
        not await _rows(session, "world_connections", user, "id")
        and not await _rows(session, "world_artifacts", user, "id"),
        "UNKNOWN_WORLD",
    )
    if root is None:
        require(not regions and not nodes and not prior.root, "UNKNOWN_WORLD")
        return {}, {}
    require(
        str(root["id"]) == str(world_id(user))
        and root["generation_seed"] == world_seed(root["id"])
        and root["layout_version"] == 1,
        "UNKNOWN_WORLD",
    )
    # A canonical empty root at revision zero can be adopted; unknown objects
    # or objective rows cannot. All later checkpoints must match prior semantics.
    require(
        sorted(regions, key=lambda r: (r["region_key"], r["id"])) == prior.regions,
        "UNKNOWN_WORLD",
    )
    require(
        sorted(
            (semantic_node(n) for n in nodes), key=lambda n: (n["entity_id"], n["id"])
        )
        == [semantic_node(n) for n in prior.nodes],
        "UNKNOWN_WORLD",
    )
    result = await session.execute(
        text(
            "select revision,change_type,object_type,object_id,payload from world_changes where user_id=:u and world_id=:w order by revision"
        ),
        {"u": user, "w": root["id"]},
    )
    reconstructed = {"REGION": {}, "NODE": {}}
    last = 0
    for change in result.mappings():
        last += 1
        require(change["revision"] == last, "WORLD_HISTORY")
        p = change["payload"]
        require(
            isinstance(p, dict)
            and set(p) == {"schema_version", "object"}
            and p["schema_version"] == "world-delta/v1",
            "WORLD_HISTORY",
        )
        obj = p["object"]
        kind = change["object_type"]
        ctype = change["change_type"]
        require(kind in ["REGION", "NODE"] and isinstance(obj, dict), "WORLD_HISTORY")
        require(
            set(obj) == (REGION_KEYS if kind == "REGION" else NODE_KEYS)
            and obj["id"] == str(change["object_id"]),
            "WORLD_HISTORY",
        )
        coordinates = (
            ("logical_x", "logical_y", "logical_width", "logical_height")
            if kind == "REGION"
            else ("logical_x", "logical_y")
        )
        require(
            all(
                type(obj[k]) in [int, float]
                and math.isfinite(obj[k])
                and 0 <= obj[k] <= 1
                for k in coordinates
            ),
            "WORLD_HISTORY",
        )
        if kind == "NODE":
            require(
                obj["growth_state"] in ["SEED", "SPROUT", "YOUNG"]
                and type(obj["entity_version"]) is int
                and obj["entity_version"] >= 1
                and type(obj["depth"]) is int
                and obj["depth"] == 0
                and type(obj["revision"]) is int,
                "WORLD_HISTORY",
            )
        previous = reconstructed[kind].get(obj["id"])
        if ctype in ["REGION_ADDED", "NODE_ADDED"]:
            require(
                previous is None
                and kind == ("REGION" if ctype == "REGION_ADDED" else "NODE"),
                "WORLD_HISTORY",
            )
        else:
            require(
                ctype == "NODE_GROWTH_CHANGED"
                and kind == "NODE"
                and previous is not None
                and previous["growth_state"] != obj["growth_state"],
                "WORLD_HISTORY",
            )
            require(
                {
                    k: v
                    for k, v in previous.items()
                    if k not in ["revision", "growth_state"]
                }
                == {
                    k: v
                    for k, v in obj.items()
                    if k not in ["revision", "growth_state"]
                },
                "WORLD_HISTORY",
            )
        if kind == "NODE":
            require(obj["revision"] == last, "WORLD_HISTORY")
        reconstructed[kind][obj["id"]] = obj
    require(root["current_revision"] == last, "WORLD_HISTORY")
    require(
        sorted(reconstructed["REGION"].values(), key=lambda r: r["id"])
        == sorted(regions, key=lambda r: r["id"])
        and sorted(reconstructed["NODE"].values(), key=lambda r: r["id"])
        == sorted(nodes, key=lambda r: r["id"]),
        "WORLD_HISTORY",
    )
    return {r["id"]: r for r in regions}, {n["id"]: n for n in nodes}


async def publish(session, projection, prior, root):
    user = UUID(projection.user_id)
    wid = world_id(user)
    regions, nodes = await verify_existing(session, prior, root)
    if projection.objectives != prior.objectives:
        wanted = {o["objective_id"] for o in projection.objectives}
        for old in prior.objectives:
            if old["objective_id"] not in wanted:
                await session.execute(
                    text(
                        "delete from learner_objective_state where user_id=:u and objective_id=:o and model_version='learner-projection/v1'"
                    ),
                    {"u": user, "o": UUID(old["objective_id"])},
                )
        for obj in projection.objectives:
            if obj in prior.objectives:
                continue
            params = _params(obj)
            params["u"] = user
            params["last_evidence_at"] = datetime.fromisoformat(obj["last_evidence_at"])
            await session.execute(
                text("""insert into learner_objective_state(user_id,objective_id,categorical_state,understanding_estimate,evidence_count,evaluation_confidence,support_required,last_evidence_at,model_version)
values (:u,:objective_id,:categorical_state,:understanding_estimate,:evidence_count,:evaluation_confidence,:support_required,:last_evidence_at,:model_version)
on conflict(user_id,objective_id) do update set categorical_state=excluded.categorical_state,understanding_estimate=excluded.understanding_estimate,evidence_count=excluded.evidence_count,evaluation_confidence=excluded.evaluation_confidence,support_required=excluded.support_required,last_evidence_at=excluded.last_evidence_at,model_version=excluded.model_version,computed_at=clock_timestamp() where learner_objective_state.user_id=:u"""),
                params,
            )
    if projection.provenance != prior.provenance:
        await session.execute(
            text(
                "delete from state_evidence_links where user_id=:u and state_dimension='OBJECTIVE'"
            ),
            {"u": user},
        )
        for objective, evid in projection.provenance:
            await session.execute(
                text(
                    "insert into state_evidence_links(user_id,state_dimension,target_id,learning_evidence_id,learning_event_id,weight) values (:u,'OBJECTIVE',:o,:e,null,null)"
                ),
                {"u": user, "o": UUID(objective), "e": UUID(evid)},
            )
    if projection.root and root is None:
        await session.execute(
            text(
                "insert into learner_worlds(id,user_id,generation_seed,layout_version,current_revision) values (:w,:u,:seed,1,0)"
            ),
            {"w": wid, "u": user, "seed": world_seed(wid)},
        )
    revision = root["current_revision"] if root else 0
    changes = []
    for region in sorted(projection.regions, key=lambda o: o["id"]):
        if region["id"] not in regions:
            changes.append(("REGION_ADDED", "REGION", region))
    for node in sorted(projection.nodes, key=lambda o: o["id"]):
        if node["id"] not in nodes:
            changes.append(("NODE_ADDED", "NODE", node))
    for node in sorted(projection.nodes, key=lambda o: o["id"]):
        if node["id"] in nodes and semantic_node(node) != semantic_node(
            nodes[node["id"]]
        ):
            changes.append(("NODE_GROWTH_CHANGED", "NODE", node))
    for ctype, kind, semantic in changes:
        revision += 1
        require(revision <= 2**31 - 1, "WORLD_REVISION_LIMIT")
        obj = dict(semantic)
        if kind == "NODE":
            obj["revision"] = revision
        params = _params(obj)
        params.update(u=user, w=wid)
        if ctype == "REGION_ADDED":
            await session.execute(
                text(
                    "insert into world_regions(id,user_id,world_id,region_key,primary_domain_id,logical_x,logical_y,logical_width,logical_height,visual_archetype) values (:id,:u,:w,:region_key,:primary_domain_id,:logical_x,:logical_y,:logical_width,:logical_height,:visual_archetype)"
                ),
                params,
            )
        elif ctype == "NODE_ADDED":
            await session.execute(
                text(
                    "insert into world_nodes(id,user_id,world_id,entity_id,entity_version,region_id,logical_x,logical_y,depth,visual_archetype,visual_seed,growth_state,revision) values (:id,:u,:w,:entity_id,:entity_version,:region_id,:logical_x,:logical_y,:depth,:visual_archetype,:visual_seed,:growth_state,:revision)"
                ),
                params,
            )
        else:
            await session.execute(
                text(
                    "update world_nodes set growth_state=:growth_state,revision=:revision,last_growth_at=clock_timestamp() where user_id=:u and world_id=:w and id=:id"
                ),
                params,
            )
        await session.execute(
            text(
                "insert into world_changes(user_id,world_id,revision,change_type,object_type,object_id,payload) values (:u,:w,:r,:ctype,:kind,:id,cast(:p as jsonb))"
            ),
            {
                "u": user,
                "w": wid,
                "r": revision,
                "ctype": ctype,
                "kind": kind,
                "id": UUID(obj["id"]),
                "p": canonical_json(
                    {"schema_version": "world-delta/v1", "object": obj}
                ),
            },
        )
    if changes:
        await session.execute(
            text(
                "update learner_worlds set current_revision=:r,updated_at=clock_timestamp() where user_id=:u and id=:w"
            ),
            {"r": revision, "u": user, "w": wid},
        )
    return revision, len(changes)
