"""Bounded owner-scoped receipt loading and read-only relational validation."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text

from app.learning.projection_inputs import (
    parse_receipt,
    require,
    timestamp,
)

# Current rows validate stable owned references only. Status, current public
# versions and operational start times never substitute historical receipt facts.
COLUMNS = {
    "learning_events": "id,event_type,schema_version,occurred_at,entity_id,exploration_id,assessment_session_id,command_id,event_ordinal",
    "assessment_responses": "id,assessment_session_id,interaction_id,support_used",
    "assessment_interactions": "id,assessment_session_id,objective_id",
    "assessment_sessions": "id,exploration_id,entity_version",
    "explorations": "id,entity_id,entity_version",
    "evaluation_runs": "id,response_id,evaluator_version,rubric_version,result,confidence",
    "learning_evidence": "id,entity_id,objective_id,source_type,source_id,evaluation_run_id,evidence_type,evidence_strength,support_level,evaluation_confidence,created_at",
    "learning_objectives": "id,entity_id,entity_version",
    "reflections": "id,exploration_id,entity_id",
    "recommendations": "id,entity_id,entity_version",
}
REFERENCES = {
    "event_id": "learning_events",
    "response_id": "assessment_responses",
    "assessment_session_id": "assessment_sessions",
    "exploration_id": "explorations",
    "evaluation_run_id": "evaluation_runs",
    "evidence_id": "learning_evidence",
    "objective_id": "learning_objectives",
    "reflection_id": "reflections",
    "recommendation_id": "recommendations",
}


def public_values(row):
    return {k: str(v) if isinstance(v, UUID) else v for k, v in row.items()}


async def validate_lineage(session, user_id, rows):
    ids = {table: set() for table in COLUMNS}
    for r in rows:
        for field, table in REFERENCES.items():
            if r["facts"].get(field):
                ids[table].add(r["facts"][field])
    cache = {}
    for table in [
        "assessment_responses",
        "assessment_sessions",
        "assessment_interactions",
        "explorations",
        "learning_objectives",
        "evaluation_runs",
        "learning_evidence",
        "learning_events",
        "reflections",
        "recommendations",
    ]:
        if ids[table]:
            # Canonical objectives have no user_id; ownership is established
            # through the owned response/session/Exploration chain below.
            scope = (
                "exists(select 1 from app_users where id=:u)"
                if table == "learning_objectives"
                else "user_id=:u"
            )
            result = await session.execute(
                text(
                    f"select {COLUMNS[table]} from {table} where {scope} and id=any(:ids)"
                ),
                {"u": UUID(user_id), "ids": [UUID(x) for x in sorted(ids[table])]},
            )
            cache[table] = {
                str(row["id"]): public_values(row) for row in result.mappings()
            }
            require(set(cache[table]) == ids[table], "RECEIPT_LINEAGE")
        else:
            cache[table] = {}
        for row in cache[table].values():
            if table == "assessment_responses":
                ids["assessment_sessions"].add(row["assessment_session_id"])
                ids["assessment_interactions"].add(row["interaction_id"])
            if table == "assessment_sessions":
                ids["explorations"].add(row["exploration_id"])
            if table == "assessment_interactions":
                ids["learning_objectives"].add(row["objective_id"])
    for r in rows:
        f = r["facts"]
        if r["source_kind"] == "BOOTSTRAP":
            continue
        if r["source_kind"] == "LEDGER":
            event = cache["learning_events"][f["event_id"]]
            require(
                event["event_type"] == f["event_type"]
                and event["schema_version"] == f["source_schema_version"]
                and timestamp(event["occurred_at"]) == r["source_time"],
                "RECEIPT_LINEAGE",
            )
            for key in [
                "entity_id",
                "exploration_id",
                "assessment_session_id",
                "command_id",
                "event_ordinal",
            ]:
                require(event[key] == f[key], "RECEIPT_LINEAGE")
            if f["exploration_id"]:
                ex = cache["explorations"][f["exploration_id"]]
                require(
                    ex["entity_id"] == f["entity_id"]
                    and ex["entity_version"] == f["entity_version"],
                    "RECEIPT_LINEAGE",
                )
            if f["assessment_session_id"]:
                s = cache["assessment_sessions"][f["assessment_session_id"]]
                require(
                    s["exploration_id"] == f["exploration_id"]
                    and s["entity_version"] == f["entity_version"],
                    "RECEIPT_LINEAGE",
                )
            if f["response_id"]:
                resp = cache["assessment_responses"][f["response_id"]]
                require(
                    resp["assessment_session_id"] == f["assessment_session_id"],
                    "RECEIPT_LINEAGE",
                )
            if f["evaluation_run_id"]:
                require(f["response_id"] is not None, "RECEIPT_LINEAGE")
                run = cache["evaluation_runs"][f["evaluation_run_id"]]
                require(run["response_id"] == f["response_id"], "RECEIPT_LINEAGE")
            for field, table in [
                ("reflection_id", "reflections"),
                ("recommendation_id", "recommendations"),
            ]:
                if f[field]:
                    ref = cache[table][f[field]]
                    require(ref["entity_id"] == f["entity_id"], "RECEIPT_LINEAGE")
                    require(
                        ref["exploration_id"] == f["exploration_id"]
                        if table == "reflections"
                        else ref["entity_version"] == f["entity_version"],
                        "RECEIPT_LINEAGE",
                    )
        else:
            ev = cache["learning_evidence"][f["evidence_id"]]
            run = cache["evaluation_runs"][f["evaluation_run_id"]]
            resp = cache["assessment_responses"][f["response_id"]]
            interaction = cache["assessment_interactions"][resp["interaction_id"]]
            sess = cache["assessment_sessions"][resp["assessment_session_id"]]
            ex = cache["explorations"][sess["exploration_id"]]
            objective = cache["learning_objectives"][f["objective_id"]]
            for key in [
                "entity_id",
                "objective_id",
                "source_type",
                "source_id",
                "evaluation_run_id",
                "evidence_type",
                "evidence_strength",
                "support_level",
            ]:
                require(ev[key] == f[key], "EVIDENCE_LINEAGE")
            require(
                ev["evaluation_confidence"] == f["classification_confidence"]
                and run["confidence"] == f["classification_confidence"],
                "EVIDENCE_LINEAGE",
            )
            require(
                run["result"] == f["evaluation_result"]
                and run["evaluator_version"] == f["evaluator_version"]
                and run["rubric_version"] == f["rubric_version"],
                "EVIDENCE_LINEAGE",
            )
            require(
                run["response_id"] == f["response_id"]
                and resp["support_used"] == f["support_level"]
                and timestamp(ev["created_at"]) == r["source_time"],
                "EVIDENCE_LINEAGE",
            )
            require(
                interaction["assessment_session_id"] == sess["id"]
                and interaction["objective_id"] == f["objective_id"],
                "EVIDENCE_LINEAGE",
            )
            require(
                ex["entity_id"] == f["entity_id"]
                and ex["entity_version"]
                == sess["entity_version"]
                == objective["entity_version"]
                == f["entity_version"]
                and objective["entity_id"] == f["entity_id"],
                "EVIDENCE_LINEAGE",
            )


async def load_prefix(session, user_id, target, *, page_size=500):
    require(type(page_size) is int and 1 <= page_size <= 500, "PAGE_SIZE")
    rows = []
    pages = 0
    while len(rows) < target:
        result = await session.execute(
            text(
                "select contract_version,schema_version,user_id,source_sequence,source_kind,source_key,source_group,source_time,facts from projection_inputs where user_id=:u and source_sequence>:after and source_sequence<=:target order by source_sequence limit :limit"
            ),
            {
                "u": UUID(user_id),
                "after": len(rows),
                "target": target,
                "limit": page_size,
            },
        )
        page = [
            parse_receipt(user_id, public_values(dict(r))) for r in result.mappings()
        ]
        require(bool(page), "PREFIX_GAP")
        for r in page:
            require(r["source_sequence"] == len(rows) + 1, "PREFIX_GAP")
            rows.append(r)
        await validate_lineage(session, user_id, page)
        pages += 1
    if rows:
        last = rows[-1]
        end = await session.scalar(
            text(
                "select max(source_sequence) from projection_inputs where user_id=:u and source_group=:g"
            ),
            {"u": UUID(user_id), "g": last["source_group"]},
        )
        require(end == target, "PARTIAL_GROUP")
    return rows, pages
