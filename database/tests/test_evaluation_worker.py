"""Real worker-role leasing, atomic finalization and deterministic evidence."""

import asyncio
import json
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.learning.content import load_package, package_digest
from app.learning.provision_content import provision
from app.learning.worker import claim_job, process_claim, run_once
from app.learning.evaluation import TransientEvaluationError


def queued(db):
    definition = load_package()["definitions"][0]
    prompt = definition["assessment"]
    option = next(
        key
        for key, value in prompt["option_results"].items()
        if value["result"] == "SUPPORTED"
    )
    ids = {
        key: uuid4()
        for key in (
            "user",
            "exploration",
            "assessment",
            "interaction",
            "response",
            "run",
            "job",
        )
    }
    with db.engine.begin() as c:
        review = {
            "package_sha256": package_digest(),
            "decision": "APPROVED",
            "review_kind": "TEST",
            "reviewer": "Test reviewer",
            "reviewed_at": "2026-09-26T00:00:00Z",
        }
        provision(c, review, allow_test=True)
        c.execute(
            text(
                "insert into app_users(id,auth_provider,auth_subject) values (:user,'SUPABASE',:subject)"
            ),
            {**ids, "subject": str(uuid4())},
        )
        c.execute(
            text(
                "insert into explorations(id,user_id,entity_id,entity_version,learning_intent,status,started_at,delivery_snapshot,delivery_contract_version) values (:exploration,:user,:entity,1,'DIRECT_INTEREST','ACTIVE',now(),cast(:snapshot as jsonb),'exploration-delivery/v1')"
            ),
            {
                **ids,
                "entity": definition["entity_id"],
                "snapshot": json.dumps(definition),
            },
        )
        c.execute(
            text(
                "insert into assessment_sessions(id,user_id,exploration_id,entity_version,strategy_version,confidence_before,status,started_at) values (:assessment,:user,:exploration,1,'assessment-strategy/v1','FUZZY','ACTIVE',now())"
            ),
            ids,
        )
        c.execute(
            text(
                "insert into assessment_interactions(id,user_id,assessment_session_id,objective_id,interaction_type,prompt_definition,rubric_version,sequence) values (:interaction,:user,:assessment,:objective,'RECOGNITION',cast(:prompt as jsonb),'1',1)"
            ),
            {
                **ids,
                "objective": definition["objective_id"],
                "prompt": json.dumps(prompt),
            },
        )
        c.execute(
            text(
                "insert into assessment_responses(id,user_id,assessment_session_id,interaction_id,response_type,response_content,support_used) values (:response,:user,:assessment,:interaction,'SINGLE_CHOICE',cast(:content as jsonb),'EXPLANATION')"
            ),
            {**ids, "content": json.dumps({"option_id": option})},
        )
        c.execute(
            text(
                "update assessment_sessions set status='WAITING_FOR_EVALUATION' where id=:assessment"
            ),
            ids,
        )
        c.execute(
            text(
                "insert into evaluation_runs(id,user_id,response_id,evaluator_type,evaluator_version,rubric_version,status) values (:run,:user,:response,'DETERMINISTIC','deterministic-evaluation/v1','1','PENDING')"
            ),
            ids,
        )
        payload = {
            "contract_version": "worker-execution/v1",
            "response_id": str(ids["response"]),
            "evaluation_run_id": str(ids["run"]),
            "assessment_session_id": str(ids["assessment"]),
        }
        c.execute(
            text(
                "insert into jobs(id,user_id,job_type,payload,status) values (:job,:user,'ASSESSMENT_EVALUATION',cast(:payload as jsonb),'PENDING')"
            ),
            {**ids, "payload": json.dumps(payload)},
        )
    return ids


async def with_worker(db, operation):
    engine = create_async_engine(db.url)

    @event.listens_for(engine.sync_engine, "connect")
    def role(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("set role app_worker")
        connection.commit()

    try:
        return await operation(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def test_worker_fences_reclaimed_lease_and_late_evaluation_exactly_once(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    ids = queued(db)

    async def exercise(factory):
        old = await claim_job(factory)
        assert old is not None
        assert await claim_job(factory) is None
        with db.engine.begin() as c:
            c.execute(
                text(
                    "update jobs set locked_at=now()-interval '61 seconds' where id=:job"
                ),
                ids,
            )
            c.execute(
                text(
                    "update explorations set status='COMPLETED',completed_at=now(),version=version+1 where id=:exploration"
                ),
                ids,
            )
        new = await claim_job(factory)
        assert new.token != old.token and new.attempt == 2
        assert await process_claim(factory, old) is False
        assert await process_claim(factory, new) is True
        assert await process_claim(factory, new) is False
        assert await run_once(factory) is False

    asyncio.run(with_worker(db, exercise))
    with db.engine.connect() as c:
        assert (
            c.scalar(text("select status from evaluation_runs where id=:run"), ids)
            == "SUCCEEDED"
        )
        assert (
            c.scalar(
                text("select status from assessment_sessions where id=:assessment"), ids
            )
            == "COMPLETED"
        )
        assert (
            c.scalar(text("select status from explorations where id=:exploration"), ids)
            == "COMPLETED"
        )
        evidence = c.execute(
            text(
                "select evidence_type,evidence_strength,support_level from learning_evidence where user_id=:user"
            ),
            ids,
        ).one()
        assert tuple(evidence) == ("RECOGNITION", "WEAK", "EXPLANATION")
        assert (
            c.scalar(
                text(
                    "select count(*) from learning_events where user_id=:user and event_type='ASSESSMENT_EVALUATED'"
                ),
                ids,
            )
            == 1
        )
        assert (
            c.scalar(
                text(
                    "select count(*) from learner_objective_state where user_id=:user"
                ),
                ids,
            )
            == 0
        )


def test_worker_retries_three_attempts_and_preserves_failed_run(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    ids = queued(db)

    def transient(*_):
        raise TransientEvaluationError("Private exception details must not be logged")

    async def exercise(factory):
        for attempt in (1, 2, 3):
            assert await run_once(factory, evaluator=transient)
            with db.engine.begin() as c:
                row = c.execute(
                    text(
                        "select status,attempt_count,available_at-now() as delay from jobs where id=:job"
                    ),
                    ids,
                ).one()
                assert row.attempt_count == attempt
                if attempt < 3:
                    assert row.status == "RETRYABLE_FAILURE"
                    assert 0 < row.delay.total_seconds() <= (5 if attempt == 1 else 30)
                    c.execute(
                        text("update jobs set available_at=now() where id=:job"), ids
                    )
                else:
                    assert row.status == "FAILED"
        assert await run_once(factory) is False

    asyncio.run(with_worker(db, exercise))
    with db.engine.connect() as c:
        assert (
            c.scalar(text("select status from evaluation_runs where id=:run"), ids)
            == "FAILED"
        )
        assert (
            c.scalar(
                text("select status from assessment_sessions where id=:assessment"), ids
            )
            == "WAITING_FOR_EVALUATION"
        )
        assert (
            c.scalar(
                text("select count(*) from learning_evidence where user_id=:user"), ids
            )
            == 0
        )
        assert (
            c.scalar(
                text(
                    "select count(*) from learning_events where user_id=:user and event_type='ASSESSMENT_EVALUATION_FAILED'"
                ),
                ids,
            )
            == 1
        )
        assert (
            c.scalar(
                text("select payload->>'retry_allowed' from jobs where id=:job"), ids
            )
            == "true"
        )


def test_finalization_event_failure_rolls_back_all_outcomes(isolated_migrated_database):
    db = isolated_migrated_database
    ids = queued(db)
    with db.engine.begin() as c:
        c.execute(
            text(
                "create function reject_m5_event() returns trigger language plpgsql as $$ begin if new.event_type='ASSESSMENT_COMPLETED' then raise exception 'injected'; end if; return new; end $$"
            )
        )
        c.execute(
            text(
                "create trigger reject_m5_event before insert on learning_events for each row execute function reject_m5_event()"
            )
        )

    async def exercise(factory):
        claim = await claim_job(factory)
        assert await process_claim(factory, claim) is False
        with db.engine.begin() as c:
            assert (
                c.scalar(text("select status from evaluation_runs where id=:run"), ids)
                == "PENDING"
            )
            assert (
                c.scalar(
                    text("select count(*) from learning_evidence where user_id=:user"),
                    ids,
                )
                == 0
            )
            assert (
                c.scalar(
                    text("select count(*) from learning_events where user_id=:user"),
                    ids,
                )
                == 0
            )
            assert (
                c.scalar(text("select status from jobs where id=:job"), ids)
                == "RUNNING"
            )
            c.execute(text("drop trigger reject_m5_event on learning_events"))
        assert await process_claim(factory, claim) is True

    asyncio.run(with_worker(db, exercise))


def test_expired_unreclaimed_worker_cannot_finalize(isolated_migrated_database):
    db = isolated_migrated_database
    ids = queued(db)

    async def exercise(factory):
        claim = await claim_job(factory)
        with db.engine.begin() as c:
            c.execute(
                text(
                    "update jobs set locked_at=now()-interval '61 seconds' where id=:job"
                ),
                ids,
            )
        assert await process_claim(factory, claim) is False
        with db.engine.connect() as c:
            assert (
                c.scalar(text("select status from evaluation_runs where id=:run"), ids)
                == "PENDING"
            )
        assert await run_once(factory)

    asyncio.run(with_worker(db, exercise))


def test_permanent_error_has_no_retry_or_evidence_and_logs_no_exception_content(
    isolated_migrated_database, caplog
):
    from app.learning.evaluation import PermanentEvaluationError
    import logging

    db = isolated_migrated_database
    ids = queued(db)

    def permanent(*_):
        raise PermanentEvaluationError("SECRET_LEARNER_TEXT")

    async def exercise(factory):
        assert await run_once(factory, evaluator=permanent)
        assert await run_once(factory) is False

    with caplog.at_level(logging.INFO, logger="app.learning.worker"):
        asyncio.run(with_worker(db, exercise))
    assert "SECRET_LEARNER_TEXT" not in caplog.text
    with db.engine.connect() as c:
        assert (
            c.scalar(text("select status from evaluation_runs where id=:run"), ids)
            == "FAILED"
        )
        assert (
            c.scalar(
                text("select count(*) from learning_evidence where user_id=:user"), ids
            )
            == 0
        )
        payload = c.scalar(text("select payload from jobs where id=:job"), ids)
        assert (
            payload["failure_category"] == "INVALID_CONTENT"
            and payload["retry_allowed"] is False
        )
