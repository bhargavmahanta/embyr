"""Explicit, per-user M6 projection maintenance; no public or bulk surface.

The caller supplies a trusted, already provisioned connection. Each operation
sets the narrow existing database role transaction-locally; dry runs roll back.
Only bounded identifiers, counts, horizons, and status codes leave this module.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import create_async_database_engine
from app.learning.projection_inputs import (
    CONTRACTS,
    EVENTS,
    LEDGER_KEYS,
    ProjectionError,
    require,
    timestamp,
)
from app.learning.projection_loader import load_prefix
from app.learning.projection_publisher import verify_existing
from app.learning.projection_reducer import reduce_prefix
from app.learning.projection_worker import Claim, _group, _payload


def _uuid(value: UUID | str) -> UUID:
    try:
        value = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ProjectionError("INVALID_USER_ID") from None
    return value


async def _one(session, statement: str, **params):
    return (await session.execute(text(statement), params)).mappings().first()


async def _owner(session, user_id: UUID) -> None:
    require(
        await session.scalar(text("select m6_lock_source_owner(:u)"), {"u": user_id}),
        "OWNER_MISSING",
    )


async def _head(session, user_id: UUID, *, lock: bool = False):
    suffix = " for update" if lock else ""
    head = await _one(
        session,
        "select * from projection_source_heads where user_id=:u" + suffix,
        u=user_id,
    )
    require(head is not None, "SOURCE_HEAD_MISSING")
    return head


async def _checkpoint(session, user_id: UUID, *, lock: bool = False):
    suffix = " for update" if lock else ""
    cp = await _one(
        session,
        "select * from learner_projection_checkpoints where user_id=:u" + suffix,
        u=user_id,
    )
    require(cp is not None, "CHECKPOINT_MISSING")
    require(
        cp["input_contract_version"] == CONTRACTS["input"]
        and cp["worker_contract_version"] == CONTRACTS["worker"]
        and cp["learner_contract_version"] == CONTRACTS["learner"]
        and cp["world_contract_version"] == CONTRACTS["world"],
        "CHECKPOINT_VERSION",
    )
    return cp


async def _root(session, user_id: UUID):
    return await _one(
        session, "select * from learner_worlds where user_id=:u", u=user_id
    )


async def _ready_state(session, user_id: UUID, head, cp) -> str:
    baseline = head["baseline_through_sequence"]
    cutoff = head["cutoff_source_sequence"]
    cutoff_at = head["cutoff_at"]
    marker = await _one(
        session,
        "select * from projection_inputs where user_id=:u and source_kind='BOOTSTRAP'",
        u=user_id,
    )
    if baseline is None and cutoff is None and cutoff_at is None and marker is None:
        require(
            cp["processed_source_sequence"] <= head["source_sequence"], "READY_METADATA"
        )
        return "FRESH_READY"
    require(
        baseline is not None
        and cutoff is not None
        and cutoff_at is not None
        and marker is not None
        and 0 <= cutoff < baseline <= head["source_sequence"]
        and marker["source_sequence"] == baseline
        and marker["source_key"] == "learner-projection/v1:baseline"
        and marker["facts"]
        == {
            "cutoff_source_sequence": cutoff,
            "cutoff_at": timestamp(cutoff_at),
        }
        and timestamp(marker["source_time"]) == timestamp(cutoff_at)
        and cp["processed_source_sequence"] <= head["source_sequence"],
        "READY_METADATA",
    )
    rows, _ = await load_prefix(session, str(user_id), baseline)
    reduce_prefix(str(user_id), rows)
    job = await _one(
        session,
        """select * from jobs where user_id=:u and job_type='LEARNER_PROJECTION'
and payload->>'source_group'=:g""",
        u=user_id,
        g=marker["source_group"],
    )
    require(job is not None, "READY_METADATA")
    claim = Claim(
        job["id"],
        str(user_id),
        job["payload"],
        "",
        0,
        cp["generation"],
        cp["processed_source_sequence"],
    )
    await _group(session, claim, head)
    return "ALREADY_BOOTSTRAPPED"


async def _preflight_empty(session, user_id: UUID, head, cp) -> None:
    require(
        head["bootstrap_state"] == "REQUIRED"
        and head["baseline_through_sequence"] is None
        and head["cutoff_source_sequence"] is None
        and head["cutoff_at"] is None,
        "BOOTSTRAP_METADATA",
    )
    require(
        cp["processed_source_sequence"] == 0
        and cp["generation"] == 1
        and cp["input_fingerprint"] is None
        and cp["output_fingerprint"] is None
        and cp["blocking_group"] is None
        and cp["failure_code"] is None,
        "BOOTSTRAP_CHECKPOINT",
    )
    require(
        await session.scalar(
            text(
                "select count(*) from projection_inputs where user_id=:u and source_kind='BOOTSTRAP'"
            ),
            {"u": user_id},
        )
        == 0,
        "BOOTSTRAP_METADATA",
    )
    empty = reduce_prefix(str(user_id), [])
    await verify_existing(session, empty, await _root(session, user_id))


PREFERENCES = frozenset({"NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"})


def _metadata_uuid(metadata: dict, key: str) -> UUID:
    try:
        return UUID(metadata[key])
    except (KeyError, TypeError, ValueError, AttributeError):
        raise ProjectionError("LEDGER_LINEAGE") from None


def _preference_version(value) -> int:
    require(type(value) is int and 1 <= value <= 2**31 - 1, "HISTORICAL_PREFERENCE")
    return value


async def _historical_ledger_facts(session, event) -> dict:
    """Select only frozen v1 facts; validate IDs against owned resource rows."""
    kind = event["event_type"]
    require(event["schema_version"] == 1 and kind in EVENTS, "UNSUPPORTED_LEDGER")
    metadata = event["metadata"]
    require(isinstance(metadata, dict), "LEDGER_LINEAGE")
    user_id = event["user_id"]
    entity_version = None
    ex = sess = None
    response_id = run_id = reflection_id = recommendation_id = None

    if event["exploration_id"] is not None:
        ex = await _one(
            session,
            "select * from explorations where user_id=:u and id=:id",
            u=user_id,
            id=event["exploration_id"],
        )
        require(
            ex is not None and ex["entity_id"] == event["entity_id"], "LEDGER_LINEAGE"
        )
        entity_version = ex["entity_version"]
    else:
        require(
            kind
            in {
                "ONBOARDING_COMPLETED",
                "EXPLICIT_INTEREST_CHANGED",
                "RECOMMENDATION_SKIPPED",
            },
            "LEDGER_LINEAGE",
        )

    if kind.startswith("ASSESSMENT_") or kind == "HINT_REQUESTED":
        sess = await _one(
            session,
            "select * from assessment_sessions where user_id=:u and id=:id",
            u=user_id,
            id=event["assessment_session_id"],
        )
        require(
            sess is not None
            and ex is not None
            and sess["exploration_id"] == ex["id"]
            and sess["entity_version"] == entity_version,
            "LEDGER_LINEAGE",
        )

    if kind in {
        "ASSESSMENT_RESPONSE_SUBMITTED",
        "ASSESSMENT_EVALUATED",
        "ASSESSMENT_EVALUATION_FAILED",
        "ASSESSMENT_EVALUATION_RETRY_REQUESTED",
        "ASSESSMENT_COMPLETED",
    }:
        run_id = _metadata_uuid(metadata, "evaluation_run_id")
        run = await _one(
            session,
            "select * from evaluation_runs where user_id=:u and id=:id",
            u=user_id,
            id=run_id,
        )
        require(run is not None, "LEDGER_LINEAGE")
        response_id = run["response_id"]
        response = await _one(
            session,
            "select * from assessment_responses where user_id=:u and id=:id",
            u=user_id,
            id=response_id,
        )
        require(
            response is not None
            and response["assessment_session_id"] == sess["id"]
            and (
                kind == "ASSESSMENT_COMPLETED"
                or response_id == _metadata_uuid(metadata, "response_id")
            ),
            "LEDGER_LINEAGE",
        )

    if kind in {"REFLECTION_SUBMITTED", "REFLECTION_UPDATED"}:
        reflection_id = _metadata_uuid(metadata, "reflection_id")
        reflection = await _one(
            session,
            "select * from reflections where user_id=:u and id=:id",
            u=user_id,
            id=reflection_id,
        )
        require(
            reflection is not None
            and ex is not None
            and reflection["exploration_id"] == ex["id"]
            and reflection["entity_id"] == event["entity_id"],
            "LEDGER_LINEAGE",
        )

    if kind in {"RECOMMENDATION_ACCEPTED", "RECOMMENDATION_SKIPPED"} or (
        kind == "EXPLORATION_STARTED"
        and ex is not None
        and ex["recommendation_id"] is not None
    ):
        recommendation_id = _metadata_uuid(metadata, "recommendation_id")
        recommendation = await _one(
            session,
            "select * from recommendations where user_id=:u and id=:id",
            u=user_id,
            id=recommendation_id,
        )
        require(
            recommendation is not None
            and recommendation["entity_id"] == event["entity_id"]
            and (
                ex is None
                or (
                    ex["recommendation_id"] == recommendation["id"]
                    and ex["entity_version"] == recommendation["entity_version"]
                )
            ),
            "LEDGER_LINEAGE",
        )
        entity_version = recommendation["entity_version"]

    preference = preference_version = None
    if kind == "EXPLICIT_INTEREST_CHANGED":
        preference = metadata.get("preference")
        require(
            preference in PREFERENCES and event["entity_id"] is not None,
            "HISTORICAL_PREFERENCE",
        )
        preference_version = _preference_version(metadata.get("version"))
    elif kind == "ONBOARDING_COMPLETED":
        preference_version = _preference_version(metadata.get("preferences_version"))
        current_version = await session.scalar(
            text("select version from learner_preferences where user_id=:u"),
            {"u": user_id},
        )
        # Onboarding is the only supported writer of learner_preferences.
        require(current_version == preference_version, "HISTORICAL_PREFERENCE")

    facts = {
        "event_id": str(event["id"]),
        "event_type": kind,
        "source_schema_version": event["schema_version"],
        "entity_id": str(event["entity_id"]) if event["entity_id"] else None,
        "entity_version": entity_version,
        "exploration_id": str(event["exploration_id"])
        if event["exploration_id"]
        else None,
        "assessment_session_id": str(event["assessment_session_id"])
        if event["assessment_session_id"]
        else None,
        "response_id": str(response_id) if response_id else None,
        "evaluation_run_id": str(run_id) if run_id else None,
        "reflection_id": str(reflection_id) if reflection_id else None,
        "recommendation_id": str(recommendation_id) if recommendation_id else None,
        "command_id": str(event["command_id"]) if event["command_id"] else None,
        "event_ordinal": event["event_ordinal"],
        "preference": preference,
        "preference_version": preference_version,
    }
    require(set(facts) == LEDGER_KEYS, "LEDGER_LINEAGE")
    return facts


async def _ledger_import(session, user_id: UUID, cutoff: int) -> tuple[int, int]:
    events = (
        (
            await session.execute(
                text("""select * from learning_events where user_id=:u
order by occurred_at,received_at,coalesce(command_id::text,''),coalesce(event_ordinal,-1),id"""),
                {"u": user_id},
            )
        )
        .mappings()
        .all()
    )
    imported = 0
    reused = 0
    choices: dict[UUID, tuple[str, int]] = {}
    for event in events:
        event_id = event["id"]
        facts = await _historical_ledger_facts(session, event)
        if event["event_type"] == "EXPLICIT_INTEREST_CHANGED":
            entity_id = event["entity_id"]
            prior_choice = choices.get(entity_id)
            require(
                facts["preference_version"]
                == (prior_choice[1] + 1 if prior_choice else 1),
                "HISTORICAL_PREFERENCE",
            )
            choices[entity_id] = (facts["preference"], facts["preference_version"])
        prior = await _one(
            session,
            "select source_sequence from projection_inputs where user_id=:u and source_kind='LEDGER' and source_key=:k",
            u=user_id,
            k=str(event_id),
        )
        require(
            prior is None or prior["source_sequence"] <= cutoff, "BOOTSTRAP_SOURCE_RACE"
        )
        sequence = await session.scalar(
            text(
                "select m6_append_input(:u,'LEDGER',:k,:t,cast(:facts as jsonb),:id,null)"
            ),
            {
                "u": user_id,
                "k": str(event_id),
                "t": event["occurred_at"],
                "facts": json.dumps(facts),
                "id": event_id,
            },
        )
        require(
            prior is None or sequence == prior["source_sequence"],
            "BOOTSTRAP_SOURCE_RACE",
        )
        if prior is None:
            imported += 1
        else:
            reused += 1
    current = (
        await session.execute(
            text("""select entity_id,preference,version
from explicit_interest_preferences where user_id=:u"""),
            {"u": user_id},
        )
    ).all()
    require(
        {entity_id: (preference, version) for entity_id, preference, version in current}
        == choices,
        "HISTORICAL_PREFERENCE",
    )
    return imported, reused


EVIDENCE_FACTS = """jsonb_build_object(
 'evidence_id',ev.id,'resulting_status',ev.status,
 'source_type',ev.source_type,'source_id',ev.source_id,
 'evidence_type',ev.evidence_type,'evidence_strength',ev.evidence_strength,
 'objective_id',ev.objective_id,'entity_id',ev.entity_id,
 'entity_version',ex.entity_version,'response_id',resp.id,
 'evaluation_run_id',ev.evaluation_run_id,'evaluation_status',run.status,
 'evaluation_result',run.result,'evaluator_version',run.evaluator_version,
 'rubric_version',run.rubric_version,'support_level',ev.support_level,
 'classification_confidence',ev.evaluation_confidence,'transition_at',null)"""


async def _evidence_import(session, user_id: UUID, cutoff: int) -> tuple[int, int]:
    evidence_ids = (
        (
            await session.execute(
                text("select id from learning_evidence where user_id=:u order by id"),
                {"u": user_id},
            )
        )
        .scalars()
        .all()
    )
    imported = 0
    reused = 0
    for evidence_id in evidence_ids:
        row = await _one(
            session,
            f"""select ev.status,ev.created_at,{EVIDENCE_FACTS} as facts
from learning_evidence ev
join evaluation_runs run on run.user_id=ev.user_id and run.id=ev.evaluation_run_id
join assessment_responses resp on resp.user_id=run.user_id and resp.id=run.response_id
join assessment_interactions ai on ai.user_id=resp.user_id and ai.id=resp.interaction_id
 and ai.assessment_session_id=resp.assessment_session_id
join assessment_sessions sess on sess.user_id=resp.user_id and sess.id=resp.assessment_session_id
join explorations ex on ex.user_id=sess.user_id and ex.id=sess.exploration_id
 and ex.entity_version=sess.entity_version
join learning_objectives obj on obj.id=ai.objective_id and obj.entity_id=ex.entity_id
 and obj.entity_version=ex.entity_version
where ev.user_id=:u and ev.id=:id and ev.source_id=resp.id
 and ev.objective_id=obj.id and ev.entity_id=ex.entity_id""",
            u=user_id,
            id=evidence_id,
        )
        require(row is not None, "EVIDENCE_LINEAGE")
        key = f"{evidence_id}:{row['status']}"
        prior = await _one(
            session,
            "select source_sequence from projection_inputs where user_id=:u and source_kind='EVIDENCE' and source_key=:k",
            u=user_id,
            k=key,
        )
        require(
            prior is None or prior["source_sequence"] <= cutoff, "BOOTSTRAP_SOURCE_RACE"
        )
        await session.scalar(
            text(
                """select m6_append_input(:u,'EVIDENCE',:k,:t,cast(:facts as jsonb),null,:id)"""
            ),
            {
                "u": user_id,
                "k": key,
                "t": row["created_at"],
                "facts": json.dumps(row["facts"]),
                "id": evidence_id,
            },
        )
        if prior is None:
            imported += 1
        else:
            reused += 1
    return imported, reused


async def bootstrap(
    factory: async_sessionmaker, user_id: UUID | str, *, apply: bool = False
) -> dict:
    """Import a single historical owner, or rollback a complete preflight."""
    user_id = _uuid(user_id)
    async with factory() as session:
        await session.begin()
        try:
            await session.execute(
                text("set transaction isolation level read committed")
            )
            await session.execute(text("set local role app_maintenance"))
            await _owner(session, user_id)
            head = await _head(session, user_id, lock=True)
            cp = await _checkpoint(session, user_id)
            if head["bootstrap_state"] == "READY":
                status = await _ready_state(session, user_id, head, cp)
                result = {
                    "user_id": str(user_id),
                    "status": status,
                    "cutoff_source_sequence": head["cutoff_source_sequence"],
                    "baseline_through_sequence": head["baseline_through_sequence"],
                }
                await session.rollback()
                return result
            await _preflight_empty(session, user_id, head, cp)
            cutoff = head["source_sequence"]
            cutoff_at = await session.scalar(text("select clock_timestamp()"))
            ledger_new, ledger_reused = await _ledger_import(session, user_id, cutoff)
            evidence_new, evidence_reused = await _evidence_import(
                session, user_id, cutoff
            )
            baseline = await session.scalar(
                text("""select m6_append_input(:u,'BOOTSTRAP','learner-projection/v1:baseline',
 :at,cast(:facts as jsonb),null,null)"""),
                {
                    "u": user_id,
                    "at": cutoff_at,
                    "facts": json.dumps(
                        {
                            "cutoff_source_sequence": cutoff,
                            "cutoff_at": timestamp(cutoff_at),
                        }
                    ),
                },
            )
            updated_head = await session.execute(
                text("""update projection_source_heads set bootstrap_state='READY',
baseline_through_sequence=:b,cutoff_source_sequence=:c,cutoff_at=:at,
updated_at=clock_timestamp() where user_id=:u and bootstrap_state='REQUIRED'"""),
                {"u": user_id, "b": baseline, "c": cutoff, "at": cutoff_at},
            )
            require(updated_head.rowcount == 1, "BOOTSTRAP_RACE")
            rows, _ = await load_prefix(session, str(user_id), baseline)
            reduce_prefix(str(user_id), rows)
            # Exercise deferred job/source guards even when this is a dry-run.
            await session.execute(text("set constraints all immediate"))
            result = {
                "user_id": str(user_id),
                "status": "APPLIED" if apply else "READY_TO_APPLY",
                "cutoff_source_sequence": cutoff,
                "baseline_through_sequence": baseline,
                "ledger_imported": ledger_new,
                "ledger_reused": ledger_reused,
                "evidence_imported": evidence_new,
                "evidence_reused": evidence_reused,
            }
            if apply:
                await session.commit()
            else:
                await session.rollback()
            return result
        except Exception:
            await session.rollback()
            raise


async def audit(factory: async_sessionmaker, user_id: UUID | str) -> dict:
    """Compare the committed checkpoint to immutable facts without mutation."""
    user_id = _uuid(user_id)
    async with factory() as session:
        await session.begin()
        try:
            await session.execute(
                text("set transaction isolation level repeatable read read only")
            )
            await session.execute(text("set local role app_backend"))
            await session.execute(
                text("select set_config('app.user_id',:u,true)"),
                {"u": str(user_id)},
            )
            require(
                await session.scalar(
                    text("select 1 from app_users where id=:u"), {"u": user_id}
                )
                == 1,
                "OWNER_MISSING",
            )
            head = await _head(session, user_id)
            cp = await _checkpoint(session, user_id)
            horizon = cp["processed_source_sequence"]
            require(horizon <= head["source_sequence"], "CHECKPOINT_HORIZON")
            rows, pages = await load_prefix(session, str(user_id), horizon)
            projection = reduce_prefix(str(user_id), rows)
            require(
                (cp["input_fingerprint"], cp["output_fingerprint"])
                == (
                    (projection.input_fingerprint, projection.output_fingerprint)
                    if horizon
                    else (None, None)
                ),
                "CHECKPOINT_FINGERPRINT",
            )
            await verify_existing(session, projection, await _root(session, user_id))
            result = {
                "user_id": str(user_id),
                "status": "PASS",
                "horizon": horizon,
                "source_sequence": head["source_sequence"],
                "pending": head["source_sequence"] - horizon,
                "blocked": cp["blocking_group"] is not None,
                "pages": pages,
            }
            await session.rollback()
            return result
        except Exception:
            await session.rollback()
            raise


async def requeue(
    factory: async_sessionmaker,
    user_id: UUID | str,
    source_group: str,
    *,
    apply: bool = False,
) -> dict:
    """Reset only the validated, earliest blocked FAILED projection job."""
    user_id = _uuid(user_id)
    require(
        isinstance(source_group, str) and re.fullmatch(r"[0-9]{1,20}", source_group),
        "INVALID_GROUP",
    )
    async with factory() as session:
        await session.begin()
        try:
            await session.execute(text("set local role app_worker"))
            await _owner(session, user_id)
            cp = await _checkpoint(session, user_id, lock=True)
            require(cp["blocking_group"] == source_group, "NOT_BLOCKED_GROUP")
            jobs = (
                (
                    await session.execute(
                        text("""select * from jobs where user_id=:u and job_type='LEARNER_PROJECTION'
and payload->>'source_group'=:g for update"""),
                        {"u": user_id, "g": source_group},
                    )
                )
                .mappings()
                .all()
            )
            require(len(jobs) == 1 and jobs[0]["status"] == "FAILED", "NOT_FAILED_JOB")
            job = jobs[0]
            head = await _head(session, user_id)
            require(head["bootstrap_state"] == "READY", "BOOTSTRAP_REQUIRED")
            await _ready_state(session, user_id, head, cp)
            claim = Claim(
                job["id"],
                str(user_id),
                job["payload"],
                "",
                0,
                cp["generation"],
                cp["processed_source_sequence"],
            )
            payload = _payload(claim)
            await _group(session, claim, head)
            horizon = cp["processed_source_sequence"]
            first, last = (
                payload["first_source_sequence"],
                payload["last_source_sequence"],
            )
            baseline = head["baseline_through_sequence"]
            expected = first == horizon + 1
            if baseline is not None and horizon < baseline:
                expected = horizon == 0 and first == 1 and last == baseline
            require(expected and last <= head["source_sequence"], "NOT_EARLIEST_GROUP")
            rows, _ = await load_prefix(session, str(user_id), last)
            prior = reduce_prefix(str(user_id), rows[:horizon])
            reduce_prefix(str(user_id), rows)
            require(
                (cp["input_fingerprint"], cp["output_fingerprint"])
                == (
                    (prior.input_fingerprint, prior.output_fingerprint)
                    if horizon
                    else (None, None)
                ),
                "CHECKPOINT_FINGERPRINT",
            )
            await verify_existing(session, prior, await _root(session, user_id))
            result = {
                "user_id": str(user_id),
                "source_group": source_group,
                "job_id": str(job["id"]),
                "status": "REQUEUED" if apply else "READY_TO_REQUEUE",
                "horizon": horizon,
                "first_source_sequence": first,
                "last_source_sequence": last,
            }
            if apply:
                updated_job = await session.execute(
                    text("""update jobs set status='PENDING',attempt_count=0,
available_at=clock_timestamp(),locked_at=null,locked_by=null,completed_at=null
where user_id=:u and id=:id and job_type='LEARNER_PROJECTION' and status='FAILED'"""),
                    {"u": user_id, "id": job["id"]},
                )
                updated_checkpoint = await session.execute(
                    text("""update learner_projection_checkpoints set blocking_group=null,
failure_code=null,updated_at=clock_timestamp() where user_id=:u
and generation=:generation and processed_source_sequence=:h and blocking_group=:g"""),
                    {
                        "u": user_id,
                        "generation": cp["generation"],
                        "h": horizon,
                        "g": source_group,
                    },
                )
                require(
                    updated_job.rowcount == 1 and updated_checkpoint.rowcount == 1,
                    "REQUEUE_RACE",
                )
                await session.commit()
            else:
                await session.rollback()
            return result
        except Exception:
            await session.rollback()
            raise


async def _main(args) -> int:
    url = os.environ.get("EMBYR_DATABASE_URL")
    if not url:
        print(json.dumps({"status": "CONFIGURATION_REQUIRED"}))
        return 2
    engine = None
    try:
        engine = create_async_database_engine(url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        if args.operation == "bootstrap":
            result = await bootstrap(factory, args.user_id, apply=args.apply)
        elif args.operation == "audit":
            result = await audit(factory, args.user_id)
        else:
            result = await requeue(
                factory, args.user_id, args.source_group, apply=args.apply
            )
        await engine.dispose()
        engine = None
        print(json.dumps(result, sort_keys=True))
        return 0
    except ProjectionError as error:
        print(json.dumps({"status": "REFUSED", "category": error.code}))
        return 1
    except Exception:  # noqa: BLE001 - CLI must never expose SQL or connection details.
        print(json.dumps({"status": "REFUSED", "category": "DATABASE_ERROR"}))
        return 1
    finally:
        if engine is not None:
            try:
                await engine.dispose()
            except Exception:  # noqa: BLE001, S110 - teardown must not leak configuration.
                pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Internal per-user projection operator"
    )
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("bootstrap", "audit", "requeue"):
        command = commands.add_parser(name)
        command.add_argument("--user-id", required=True)
        if name == "requeue":
            command.add_argument("--source-group", required=True)
        if name != "audit":
            command.add_argument("--apply", action="store_true")
    return asyncio.run(_main(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
