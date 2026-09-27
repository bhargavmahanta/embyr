"""Atomic projection publication and fencing with PostgreSQL runtime roles."""

import asyncio
import json

import pytest
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_evaluation_supersession import _response_graph
from test_projection_foundation import evidence, onboard, user


def sql(c, statement, **params):
    return c.execute(text(statement), params)


def start(c, owner, entity, ex, when="2026-01-01T00:00:00Z"):
    sql(
        c,
        "insert into learning_events(user_id,event_type,entity_id,exploration_id,occurred_at,schema_version,metadata) values (:u,'EXPLORATION_STARTED',:e,:x,cast(:t as timestamptz),1,'{}'::jsonb)",
        u=owner,
        e=entity,
        x=ex,
        t=when,
    )


def graph(db, *, recognition=True):
    with db.engine.begin() as c:
        g = _response_graph(c)
        ex = c.scalar(
            text(
                "select s.exploration_id from assessment_sessions s join assessment_responses r on r.assessment_session_id=s.id where r.id=:r"
            ),
            {"r": g["response_id"]},
        )
        g["exploration_id"] = ex
        start(c, g["user_id"], g["entity_id"], ex)
        if recognition:
            run = c.scalar(
                text(
                    "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED') returning id"
                ),
                {"u": g["user_id"], "r": g["response_id"]},
            )
            g["run_id"] = run
            g["evidence_id"] = evidence(c, g, run, evaluation_confidence=0.8)
    return g


async def worker(db, operation, *, fault=None):
    engine = create_async_engine(db.url)

    @event.listens_for(engine.sync_engine, "connect")
    def direct_role(connection, _):
        with connection.cursor() as cursor:
            cursor.execute("set session authorization app_worker")
        connection.commit()

    if fault:

        @event.listens_for(engine.sync_engine, "after_cursor_execute")
        def crash(conn, cursor, statement, parameters, context, many):
            normalized = " ".join(statement.lower().split())
            if fault in normalized:
                raise RuntimeError("injected publication fault")

    try:
        return await operation(async_sessionmaker(engine, expire_on_commit=False))
    finally:
        await engine.dispose()


def state(db, u):
    with db.engine.connect() as c:
        return {
            "checkpoint": c.scalar(
                text(
                    "select processed_source_sequence from learner_projection_checkpoints where user_id=:u"
                ),
                {"u": u},
            ),
            "objectives": sql(
                c,
                "select categorical_state,understanding_estimate,evidence_count,evaluation_confidence,support_required from learner_objective_state where user_id=:u",
                u=u,
            ).all(),
            "provenance": sql(
                c,
                "select target_id,learning_evidence_id,learning_event_id,weight from state_evidence_links where user_id=:u and state_dimension='OBJECTIVE'",
                u=u,
            ).all(),
            "root": sql(
                c,
                "select id,current_revision from learner_worlds where user_id=:u",
                u=u,
            ).all(),
            "nodes": sql(
                c,
                "select entity_id,entity_version,growth_state,revision from world_nodes where user_id=:u order by entity_id",
                u=u,
            ).all(),
            "changes": sql(
                c,
                "select revision,change_type,payload from world_changes where user_id=:u order by revision",
                u=u,
            ).all(),
            "fingerprints": sql(
                c,
                "select input_fingerprint,output_fingerprint from learner_projection_checkpoints where user_id=:u",
                u=u,
            ).one(),
        }


def test_supported_group_publishes_final_growth_and_reconstructs_once(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import run_once

        assert await run_once(factory)
        assert not await run_once(factory)

    asyncio.run(worker(db, exercise))
    s = state(db, g["user_id"])
    assert s["checkpoint"] == 2
    assert s["objectives"] == [("DEVELOPING", None, 1, 0.8, False)]
    assert s["provenance"] == [(g["objective_id"], g["evidence_id"], None, None)]
    assert [r[1] for r in s["changes"]] == ["REGION_ADDED", "NODE_ADDED"]
    assert s["nodes"][0][2:] == ("YOUNG", 2)
    assert s["changes"][1][2]["object"]["revision"] == 2
    assert s["root"][0][1] == 2


def test_root_only_has_revision_zero_and_duplicate_ack_does_not_rewrite(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        u = user(c)
        onboard(c, u)

    async def exercise(factory):
        from app.learning.projection_worker import run_once

        assert await run_once(factory)
        before = state(db, u)
        with db.engine.begin() as c:
            sql(
                c,
                "update jobs set status='PENDING',completed_at=null where user_id=:u and job_type='LEARNER_PROJECTION'",
                u=u,
            )
        assert await run_once(factory)
        assert state(db, u) == before

    asyncio.run(worker(db, exercise))
    assert state(db, u)["root"][0][1] == 0 and not state(db, u)["changes"]


@pytest.mark.parametrize(
    "fault",
    [
        "insert into learner_objective_state",
        "insert into state_evidence_links",
        "insert into learner_worlds",
        "insert into world_regions",
        "insert into world_nodes",
        "insert into world_changes",
        "update learner_worlds",
        "update learner_projection_checkpoints",
        "update jobs set status='succeeded'",
    ],
)
def test_every_publication_stage_rolls_back(fault, isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)
    before = state(db, g["user_id"])

    async def exercise(factory):
        from app.learning.projection_worker import run_once

        await run_once(factory)

    asyncio.run(worker(db, exercise, fault=fault))
    # Failure scheduling may change checkpoint failure metadata, never published state.
    assert state(db, g["user_id"]) == before
    with db.engine.connect() as c:
        row = sql(
            c,
            "select status,attempt_count,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'",
            u=g["user_id"],
        ).one()
        assert (
            row.status == "RETRYABLE_FAILURE"
            and row.attempt_count == 1
            and len(row.payload) == 5
        )


def test_stale_token_generation_horizon_and_deleted_owner_publish_nothing(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, finalize, prepare

        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        with db.engine.begin() as c:
            sql(
                c,
                "update learner_projection_checkpoints set generation=generation+1 where user_id=:u",
                u=g["user_id"],
            )
        assert not await finalize(factory, claim, prepared)
        assert state(db, g["user_id"])["checkpoint"] == 0

    asyncio.run(worker(db, exercise))


def drain(db):
    async def exercise(factory):
        from app.learning.projection_worker import run_once

        count = 0
        while await run_once(factory):
            count += 1
        return count

    return asyncio.run(worker(db, exercise))


def baseline(db, u):
    with db.engine.begin() as c:
        cutoff = sql(c, "select clock_timestamp()").scalar_one()
        sequence = sql(
            c,
            "select source_sequence from projection_source_heads where user_id=:u",
            u=u,
        ).scalar_one()
        # Trusted test setup exercises publisher support, never an importer.
        sql(
            c,
            "update projection_source_heads set baseline_through_sequence=:b,cutoff_source_sequence=:s,cutoff_at=:t where user_id=:u",
            b=sequence + 1,
            s=sequence,
            t=cutoff,
            u=u,
        )
        sql(
            c,
            "select m6_append_input(:u,'BOOTSTRAP','learner-projection/v1:baseline',:t,cast(:f as jsonb),null,null)",
            u=u,
            t=cutoff,
            f=json.dumps(
                {
                    "cutoff_source_sequence": sequence,
                    "cutoff_at": cutoff.isoformat().replace("+00:00", "Z"),
                }
            ),
        )
        return sequence + 1


def add_version(db, g, version=2, when="2025-12-01T00:00:00Z"):
    with db.engine.begin() as c:
        sql(
            c,
            "insert into learning_entity_versions(entity_id,version,title,summary,knowledge_types,scope) values (:e,:v,'Other','Summary',array['CONCEPTUAL'],'NORMAL')",
            e=g["entity_id"],
            v=version,
        )
        ex = sql(
            c,
            "insert into explorations(user_id,entity_id,entity_version,learning_intent,status,started_at) values (:u,:e,:v,'DIRECT_INTEREST','ACTIVE',now()) returning id",
            u=g["user_id"],
            e=g["entity_id"],
            v=version,
        ).scalar_one()
        start(c, g["user_id"], g["entity_id"], ex, when)
    return ex


def test_crossed_event_time_live_baseline_and_mutation_keep_same_pin(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db, recognition=False)
    assert drain(db) == 1
    before = state(db, g["user_id"])
    ex = add_version(db, g)
    with db.engine.begin() as c:
        sql(
            c,
            "update explorations set started_at='2020-01-01T00:00:00Z' where user_id=:u and id=:x",
            u=g["user_id"],
            x=ex,
        )
    assert drain(db) == 1
    after = state(db, g["user_id"])
    assert after["nodes"] == before["nodes"] and after["changes"] == before["changes"]

    async def exercise(factory):
        from app.learning.projection_loader import load_prefix
        from app.learning.projection_reducer import reduce_prefix

        async with factory() as s:
            rows, _ = await load_prefix(s, str(g["user_id"]), 2)
        assert reduce_prefix(g["user_id"], rows).nodes[0]["entity_version"] == 1

    asyncio.run(worker(db, exercise))


def test_baseline_publishes_once_at_final_growth_and_covers_old_jobs(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    add_version(db, g)
    b = baseline(db, g["user_id"])
    assert drain(db) == 3  # baseline first; two covered ordinary jobs acknowledged
    s = state(db, g["user_id"])
    assert s["checkpoint"] == b and s["nodes"][0][1:] == (1, "YOUNG", 2)
    assert [r[1] for r in s["changes"]] == ["REGION_ADDED", "NODE_ADDED"]
    with db.engine.begin() as c:
        sql(
            c,
            "update jobs set status='PENDING',completed_at=null where user_id=:u and payload->>'last_source_sequence'=:b",
            u=g["user_id"],
            b=str(b),
        )
    assert drain(db) == 1 and state(db, g["user_id"]) == s


@pytest.mark.parametrize("unknown", ["objective", "world"])
def test_unknown_baseline_origin_is_refused_without_wiping(
    unknown, isolated_migrated_database
):
    db = isolated_migrated_database
    g = graph(db)
    from test_learner_state_schema import _insert_objective_state
    from test_worldmodel_schema import _insert_node, _insert_region, _insert_world

    with db.engine.begin() as c:
        if unknown == "objective":
            _insert_objective_state(
                c, user_id=g["user_id"], objective_id=g["objective_id"]
            )
        else:
            world = _insert_world(c, user_id=g["user_id"])
            region = _insert_region(c, user_id=g["user_id"], world_id=world)
            _insert_node(
                c,
                user_id=g["user_id"],
                world_id=world,
                entity_id=g["entity_id"],
                region_id=region,
            )
    baseline(db, g["user_id"])
    before = state(db, g["user_id"])
    assert drain(db) == 1
    assert state(db, g["user_id"]) == before
    with db.engine.connect() as c:
        assert sql(
            c,
            "select failure_code from learner_projection_checkpoints where user_id=:u",
            u=g["user_id"],
        ).scalar_one() in ["UNKNOWN_PROVENANCE", "UNKNOWN_WORLD"]


def test_required_gate_blocks_without_consuming_attempts(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)
    # Trusted pre-existing-user metadata setup, without changing schema/grants.
    with db.engine.begin() as c:
        sql(
            c,
            "update projection_source_heads set bootstrap_state='REQUIRED' where user_id=:u",
            u=g["user_id"],
        )
    assert drain(db) == 0
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select attempt_count from jobs where user_id=:u and job_type='LEARNER_PROJECTION'",
                u=g["user_id"],
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize(
    "change", ["token", "attempt", "expired", "horizon", "generation", "payload"]
)
def test_finalization_revalidates_every_claim_fence(change, isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, finalize, prepare

        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        with db.engine.begin() as c:
            if change == "token":
                sql(
                    c,
                    "update jobs set locked_by='reclaimed' where user_id=:u and id=:j",
                    u=g["user_id"],
                    j=claim.job_id,
                )
            if change == "attempt":
                sql(
                    c,
                    "update jobs set attempt_count=attempt_count+1 where user_id=:u and id=:j",
                    u=g["user_id"],
                    j=claim.job_id,
                )
            if change == "expired":
                sql(
                    c,
                    "update jobs set locked_at=clock_timestamp()-interval '60 seconds' where user_id=:u and id=:j",
                    u=g["user_id"],
                    j=claim.job_id,
                )
            if change == "horizon":
                sql(
                    c,
                    "update learner_projection_checkpoints set processed_source_sequence=1 where user_id=:u",
                    u=g["user_id"],
                )
            if change == "generation":
                sql(
                    c,
                    "update learner_projection_checkpoints set generation=generation+1 where user_id=:u",
                    u=g["user_id"],
                )
        if change == "payload":
            from dataclasses import replace

            claim = replace(claim, payload={**claim.payload, "source_group": "999"})
        assert not await finalize(factory, claim, prepared)
        assert not state(db, g["user_id"])["root"]

    asyncio.run(worker(db, exercise))


def test_expired_claim_reclaims_fresh_token_without_double_publication(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import (
            claim_job,
            finalize,
            prepare,
            process_claim,
        )

        old = await claim_job(factory)
        prepared = await prepare(factory, old)
        assert await claim_job(factory) is None
        with db.engine.begin() as c:
            sql(
                c,
                "update jobs set locked_at=clock_timestamp()-interval '61 seconds' where user_id=:u",
                u=g["user_id"],
            )
        new = await claim_job(factory)
        assert new.token != old.token and new.attempt == 2
        assert not await finalize(factory, old, prepared)
        assert await process_claim(factory, new)

    asyncio.run(worker(db, exercise))
    assert state(db, g["user_id"])["root"][0][1] == 2


def test_retry_delays_budget_and_owner_isolated_terminal_block(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    other = graph(db)
    with db.engine.begin() as c:
        sql(
            c,
            "update jobs set available_at=clock_timestamp()+interval '1 day' where user_id=:u",
            u=other["user_id"],
        )

    # Enable other owner only after g's retry budget is exhausted.
    async def sequence(factory):
        from app.learning.projection_worker import claim_job, fail_claim, run_once

        for attempt, delay in [(1, 5), (2, 30), (3, 0)]:
            claim = await claim_job(factory)
            assert claim.user_id == str(g["user_id"]) and claim.attempt == attempt
            assert await fail_claim(factory, claim, "PROCESSING_FAILURE")
            with db.engine.connect() as c:
                row = sql(
                    c,
                    "select status,extract(epoch from available_at-clock_timestamp()) as delay,payload from jobs where user_id=:u and id=:j",
                    u=g["user_id"],
                    j=claim.job_id,
                ).one()
                assert len(row.payload) == 5
                assert row.status == ("RETRYABLE_FAILURE" if delay else "FAILED")
                if delay:
                    assert delay - 2 < row.delay <= delay
            with db.engine.begin() as c:
                sql(
                    c,
                    "update jobs set available_at=clock_timestamp() where user_id=:u",
                    u=g["user_id"],
                )
        with db.engine.begin() as c:
            sql(
                c,
                "update jobs set available_at=clock_timestamp() where user_id=:u",
                u=other["user_id"],
            )
        assert await run_once(factory)
        assert (
            state(db, other["user_id"])["checkpoint"] == 2
            and state(db, g["user_id"])["checkpoint"] == 0
        )

    asyncio.run(worker(db, sequence))


def test_deletion_after_detached_reduction_never_resurrects(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import (
            claim_job,
            fail_claim,
            finalize,
            prepare,
        )

        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        async with factory() as s, s.begin():
            await s.execute(
                text("select maintenance_delete_account(:u)"), {"u": g["user_id"]}
            )
        assert not await finalize(factory, claim, prepared)
        assert not await fail_claim(factory, claim, "PROCESSING_FAILURE")

    asyncio.run(worker(db, exercise))
    with db.engine.connect() as c:
        for table in [
            "app_users",
            "learner_projection_checkpoints",
            "learner_worlds",
            "learner_objective_state",
            "jobs",
        ]:
            field = "id" if table == "app_users" else "user_id"
            assert (
                sql(
                    c, f"select count(*) from {table} where {field}=:u", u=g["user_id"]
                ).scalar_one()
                == 0
            )


def test_old_receipt_evidence_status_is_not_replaced_by_current_source_status(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    with db.engine.begin() as c:
        sql(
            c,
            "update learning_evidence set status='REVOKED' where user_id=:u and id=:e",
            u=g["user_id"],
            e=g["evidence_id"],
        )
        sql(
            c,
            "update evaluation_runs set status='REVOKED' where user_id=:u and id=:r",
            u=g["user_id"],
            r=g["run_id"],
        )

    async def exercise(factory):
        from app.learning.projection_worker import run_once

        assert await run_once(factory)
        assert state(db, g["user_id"])["nodes"][0][2] == "YOUNG"
        assert await run_once(factory)
        assert state(db, g["user_id"])["nodes"][0][2] == "SEED"
        assert (
            state(db, g["user_id"])["objectives"] == []
            and state(db, g["user_id"])["provenance"] == []
        )

    asyncio.run(worker(db, exercise))


def test_exhausted_covered_delivery_acknowledges_without_blocking(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    assert drain(db) == 1
    before = state(db, g["user_id"])
    with db.engine.begin() as c:
        sql(
            c,
            "update jobs set status='PENDING',attempt_count=3,completed_at=null where user_id=:u and job_type='LEARNER_PROJECTION'",
            u=g["user_id"],
        )
    assert drain(db) == 1
    assert state(db, g["user_id"]) == before
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select status from jobs where user_id=:u and job_type='LEARNER_PROJECTION'",
                u=g["user_id"],
            ).scalar_one()
            == "SUCCEEDED"
        )
        assert (
            sql(
                c,
                "select blocking_group from learner_projection_checkpoints where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
            is None
        )


def returned(c, g, count=1):
    for _ in range(count):
        sql(
            c,
            "insert into learning_events(user_id,event_type,entity_id,exploration_id,occurred_at,schema_version,metadata) values (:u,'USER_RETURNED',:e,:x,now(),1,'{}'::jsonb)",
            u=g["user_id"],
            e=g["entity_id"],
            x=g["exploration_id"],
        )


def test_factual_noop_advances_only_horizon_and_input_fingerprint(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    assert drain(db) == 1
    before = state(db, g["user_id"])
    with db.engine.begin() as c:
        returned(c, g)
    assert drain(db) == 1
    after = state(db, g["user_id"])
    assert after["checkpoint"] == 3 and before["checkpoint"] == 2
    assert after["fingerprints"][0] != before["fingerprints"][0]
    assert after["fingerprints"][1] == before["fingerprints"][1]
    for key in ["objectives", "provenance", "root", "nodes", "changes"]:
        assert after[key] == before[key]


def test_large_group_crosses_page_boundary_and_partial_group_is_rejected(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db, recognition=False)
    with db.engine.begin() as c:
        returned(c, g, 501)

    async def exercise(factory):
        from app.learning.projection_loader import load_prefix
        from app.learning.projection_reducer import ProjectionError, reduce_prefix

        async with factory() as s, s.begin():
            a, pages = await load_prefix(s, str(g["user_id"]), 502)
            b, other = await load_prefix(s, str(g["user_id"]), 502, page_size=113)
            assert pages == 2 and other == 5 and a == b
            assert reduce_prefix(g["user_id"], a) == reduce_prefix(g["user_id"], b)
            with pytest.raises(ProjectionError, match="PARTIAL_GROUP"):
                await load_prefix(s, str(g["user_id"]), 501)
            with pytest.raises(ProjectionError, match="PAGE_SIZE"):
                await load_prefix(s, str(g["user_id"]), 502, page_size=501)

    asyncio.run(worker(db, exercise))
    assert drain(db) == 2 and state(db, g["user_id"])["checkpoint"] == 502


def test_skip_locked_and_exact_next_group_allow_other_owner(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)
    other = graph(db)
    with db.engine.begin() as c:
        returned(c, g)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, process_claim

        with db.engine.connect() as lock, lock.begin():
            sql(
                lock,
                "select id from jobs where user_id=:u and payload->>'first_source_sequence'='1' for update",
                u=g["user_id"],
            )
            claim = await claim_job(factory)
            assert claim.user_id == str(other["user_id"])
            assert await process_claim(factory, claim)
            assert await claim_job(factory) is None
        claim = await claim_job(factory)
        assert claim.payload["first_source_sequence"] == 1
        assert await claim_job(factory) is None
        assert await process_claim(factory, claim)
        next_claim = await claim_job(factory)
        assert (
            next_claim.user_id == str(g["user_id"])
            and next_claim.payload["first_source_sequence"] == 3
        )
        assert await process_claim(factory, next_claim)

    asyncio.run(worker(db, exercise))


def test_expiry_is_checked_after_waiting_for_checkpoint_lock(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, finalize, prepare

        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        with db.engine.connect() as lock, lock.begin():
            sql(
                lock,
                "select user_id from learner_projection_checkpoints where user_id=:u for update",
                u=g["user_id"],
            )
            task = asyncio.create_task(finalize(factory, claim, prepared))
            try:
                # Observe the actual server wait, rather than assuming a sleep
                # reached the publication lock. Bounded polling is test-only.
                for _ in range(200):
                    with db.engine.connect() as observer:
                        waiting = sql(
                            observer,
                            "select exists(select 1 from pg_stat_activity where datname=current_database() and wait_event_type='Lock' and query like 'select * from learner_projection_checkpoints%')",
                        ).scalar_one()
                    if waiting:
                        break
                    await asyncio.sleep(0.01)
                assert waiting
                with db.engine.begin() as c:
                    sql(
                        c,
                        "update jobs set locked_at=clock_timestamp()-interval '61 seconds' where user_id=:u and id=:j",
                        u=g["user_id"],
                        j=claim.job_id,
                    )
            finally:
                lock.commit()
            assert not await asyncio.wait_for(task, 5)
        assert not state(db, g["user_id"])["root"]

    asyncio.run(worker(db, exercise))


def test_same_group_replacement_changes_provenance_without_growth_jitter(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    assert drain(db) == 1
    before = state(db, g["user_id"])
    with db.engine.begin() as c:
        sql(
            c,
            "update learning_evidence set status='SUPERSEDED' where user_id=:u and id=:e",
            u=g["user_id"],
            e=g["evidence_id"],
        )
        sql(
            c,
            "update evaluation_runs set status='SUPERSEDED' where user_id=:u and id=:r",
            u=g["user_id"],
            r=g["run_id"],
        )
        run = sql(
            c,
            "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status,supersedes_id) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED',:prior) returning id",
            u=g["user_id"],
            r=g["response_id"],
            prior=g["run_id"],
        ).scalar_one()
        ev = evidence(c, g, run, evaluation_confidence=0.8)
    assert drain(db) == 1
    after = state(db, g["user_id"])
    assert (
        after["root"] == before["root"]
        and after["changes"] == before["changes"]
        and after["nodes"] == before["nodes"]
    )
    assert after["provenance"] == [(g["objective_id"], ev, None, None)]
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select status from learning_evidence where user_id=:u and id=:e",
                u=g["user_id"],
                e=g["evidence_id"],
            ).scalar_one()
            == "SUPERSEDED"
        )


@pytest.mark.parametrize(
    "damage",
    ["null_pin", "foreign_pin", "wrong_id", "wrong_seed", "extra_region", "connection"],
)
def test_unknown_materialized_semantics_refused_without_any_repair(
    damage, isolated_migrated_database
):
    from uuid import uuid4

    from test_worldmodel_schema import _insert_connection, _insert_entity, _insert_node

    db = isolated_migrated_database
    g = graph(db)
    assert drain(db) == 1
    with db.engine.begin() as c:
        world = sql(
            c, "select id from learner_worlds where user_id=:u", u=g["user_id"]
        ).scalar_one()
        node, region = sql(
            c, "select id,region_id from world_nodes where user_id=:u", u=g["user_id"]
        ).one()
        if damage == "null_pin":
            sql(
                c,
                "update world_nodes set entity_version=null where user_id=:u",
                u=g["user_id"],
            )
        if damage == "foreign_pin":
            sql(
                c,
                "insert into learning_entity_versions(entity_id,version,title,summary,knowledge_types,scope) values (:e,2,'Other','Summary',array['CONCEPTUAL'],'NORMAL')",
                e=g["entity_id"],
            )
            sql(
                c,
                "update world_nodes set entity_version=2 where user_id=:u",
                u=g["user_id"],
            )
        if damage == "wrong_id":
            sql(
                c,
                "update world_nodes set id=:id where user_id=:u",
                id=uuid4(),
                u=g["user_id"],
            )
        if damage == "wrong_seed":
            sql(
                c,
                "update learner_worlds set generation_seed=:seed where user_id=:u",
                seed="a" * 64,
                u=g["user_id"],
            )
        if damage == "extra_region":
            sql(
                c,
                "insert into world_regions(user_id,world_id,region_key,logical_x,logical_y,logical_width,logical_height,visual_archetype) values (:u,:w,'foreign',0,0,1,1,'grove')",
                u=g["user_id"],
                w=world,
            )
        if damage == "connection":
            second = _insert_node(
                c,
                user_id=g["user_id"],
                world_id=world,
                entity_id=_insert_entity(c),
                region_id=region,
            )
            _insert_connection(
                c,
                user_id=g["user_id"],
                world_id=world,
                source_world_node_id=node,
                target_world_node_id=second,
            )
        returned(c, g)
    before = state(db, g["user_id"])
    assert drain(db) == 1 and state(db, g["user_id"]) == before
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select failure_code from learner_projection_checkpoints where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
            == "UNKNOWN_WORLD"
        )


def test_deletion_during_prefix_loading_publishes_nothing(
    monkeypatch, isolated_migrated_database
):
    from app.learning import projection_loader

    db = isolated_migrated_database
    g = graph(db)
    original = projection_loader.validate_lineage

    async def exercise(factory):
        from app.learning.projection_worker import run_once

        async def delete_before_lineage(session, owner, rows):
            async with factory() as deleting, deleting.begin():
                await deleting.execute(
                    text("select maintenance_delete_account(:u)"), {"u": g["user_id"]}
                )
            return await original(session, owner, rows)

        monkeypatch.setattr(
            projection_loader, "validate_lineage", delete_before_lineage
        )
        assert not await run_once(factory)

    asyncio.run(worker(db, exercise))
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select count(*) from learner_worlds where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
            == 0
        )


def test_owner_deletion_wins_before_publication_owner_lock(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, finalize, prepare

        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        with db.engine.connect() as deleting, deleting.begin():
            sql(
                deleting,
                "select id from app_users where id=:u for update",
                u=g["user_id"],
            )
            task = asyncio.create_task(finalize(factory, claim, prepared))
            for _ in range(200):
                with db.engine.connect() as observer:
                    waiting = sql(
                        observer,
                        "select exists(select 1 from pg_stat_activity where datname=current_database() and wait_event_type='Lock' and query like 'select m6_lock_source_owner%')",
                    ).scalar_one()
                if waiting:
                    break
                await asyncio.sleep(0.01)
            assert waiting
            sql(deleting, "set local role app_maintenance")
            sql(deleting, "select maintenance_delete_account(:u)", u=g["user_id"])
            deleting.commit()
            assert not await asyncio.wait_for(task, 5)

    asyncio.run(worker(db, exercise))
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select count(*) from learner_worlds where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
            == 0
        )


def test_worker_uses_real_runtime_identity_and_owner_scopes(isolated_migrated_database):
    from dataclasses import replace

    db = isolated_migrated_database
    g = graph(db)
    other = graph(db)

    async def exercise(factory):
        from app.learning.projection_worker import claim_job, finalize, prepare

        async with factory() as s:
            row = (
                await s.execute(
                    text("select session_user,current_user,current_setting('role')")
                )
            ).one()
            assert tuple(row) == ("app_worker", "app_worker", "none")
        claim = await claim_job(factory)
        prepared = await prepare(factory, claim)
        foreign = (
            other["user_id"] if claim.user_id == str(g["user_id"]) else g["user_id"]
        )
        forged = replace(
            claim,
            user_id=str(foreign),
            payload={**claim.payload, "user_id": str(foreign)},
        )
        assert not await finalize(factory, forged, prepared)
        assert state(db, foreign)["checkpoint"] == 0 and not state(db, foreign)["root"]
        assert await finalize(factory, claim, prepared)

    asyncio.run(worker(db, exercise))


@pytest.mark.parametrize("count,batch", [(25, 6), (2001, 50)])
def test_complete_prefix_characterization(count, batch, isolated_migrated_database):
    from time import perf_counter

    db = isolated_migrated_database
    g = graph(db, recognition=False)
    for offset in range(1, count, batch):
        with db.engine.begin() as c:
            returned(c, g, min(batch, count - offset))

    async def exercise(factory):
        from app.learning.projection_loader import load_prefix
        from app.learning.projection_reducer import reduce_prefix

        queries = 0
        async with factory() as session, session.begin():
            await session.execute(text("select 1"))
            engine = session.bind.sync_engine

            def count_query(conn, cursor, statement, parameters, context, many):
                nonlocal queries
                queries += 1

            event.listen(engine, "before_cursor_execute", count_query)
            try:
                begin = perf_counter()
                rows, pages = await load_prefix(session, str(g["user_id"]), count)
                out = reduce_prefix(g["user_id"], rows)
                elapsed = perf_counter() - begin
            finally:
                event.remove(engine, "before_cursor_execute", count_query)
            assert out.horizon == count and out.nodes[0]["growth_state"] == "SEED"
        with db.engine.connect() as c:
            groups = sql(
                c,
                "select count(distinct source_group) from projection_inputs where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
        print(
            "M6_PREFIX_PERFORMANCE "
            + json.dumps(
                {
                    "receipts": count,
                    "groups": groups,
                    "pages": pages,
                    "queries": queries,
                    "elapsed_seconds": round(elapsed, 6),
                }
            )
        )

    asyncio.run(worker(db, exercise))


def test_optional_response_without_run_is_validated_independently(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    g = graph(db)
    with db.engine.begin() as c:
        session = sql(
            c,
            "select assessment_session_id from assessment_responses where user_id=:u and id=:r",
            u=g["user_id"],
            r=g["response_id"],
        ).scalar_one()
        sql(
            c,
            "insert into learning_events(user_id,event_type,entity_id,exploration_id,assessment_session_id,occurred_at,schema_version,metadata) values (:u,'ASSESSMENT_ABANDONED',:e,:x,:s,now(),1,'{}'::jsonb)",
            u=g["user_id"],
            e=g["entity_id"],
            x=g["exploration_id"],
            s=session,
        )
    with db.engine.connect() as c:
        row = dict(
            sql(
                c,
                "select contract_version,schema_version,user_id,source_sequence,source_kind,source_key,source_group,source_time,facts from projection_inputs where user_id=:u order by source_sequence desc limit 1",
                u=g["user_id"],
            )
            .mappings()
            .one()
        )

    async def exercise(factory):
        from app.learning.projection_inputs import parse_receipt
        from app.learning.projection_loader import public_values, validate_lineage

        parsed = parse_receipt(str(g["user_id"]), public_values(row))
        parsed["facts"]["response_id"] = str(g["response_id"])
        assert parsed["facts"]["evaluation_run_id"] is None
        async with factory() as s, s.begin():
            await validate_lineage(s, str(g["user_id"]), [parsed])

    asyncio.run(worker(db, exercise))


def test_invalid_overwritten_historical_growth_is_refused(isolated_migrated_database):
    db = isolated_migrated_database
    g = graph(db, recognition=False)
    assert drain(db) == 1
    with db.engine.begin() as c:
        run = sql(
            c,
            "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED') returning id",
            u=g["user_id"],
            r=g["response_id"],
        ).scalar_one()
        evidence(c, g, run, evaluation_confidence=0.8)
    assert drain(db) == 1
    with db.engine.begin() as c:
        sql(
            c,
            "update world_changes set payload=jsonb_set(payload,'{object,growth_state}','\"ESTABLISHED\"'::jsonb) where user_id=:u and change_type='NODE_ADDED'",
            u=g["user_id"],
        )
        returned(c, g)
    before = state(db, g["user_id"])
    assert drain(db) == 1
    assert state(db, g["user_id"]) == before
    with db.engine.connect() as c:
        assert (
            sql(
                c,
                "select failure_code from learner_projection_checkpoints where user_id=:u",
                u=g["user_id"],
            ).scalar_one()
            == "WORLD_HISTORY"
        )


def test_multiple_objects_use_uuid_order_and_all_deltas_reconstruct_exactly(
    isolated_migrated_database,
):
    from app.learning.projection_loader import public_values
    from app.learning.projection_publisher import NODE_KEYS, REGION_KEYS
    from app.learning.world_projection import node_object
    from test_evaluation_supersession import _insert_entity_objective, _insert_response

    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        graphs = []
        for _ in range(3):
            entity, objective = _insert_entity_objective(c)
            response = _insert_response(
                c, user_id=owner, entity_id=entity, objective_id=objective
            )
            ex = sql(
                c,
                "select s.exploration_id from assessment_sessions s join assessment_responses r on r.assessment_session_id=s.id and r.user_id=s.user_id where r.user_id=:u and r.id=:r",
                u=owner,
                r=response,
            ).scalar_one()
            graphs.append(
                {
                    "user_id": owner,
                    "entity_id": entity,
                    "objective_id": objective,
                    "response_id": response,
                    "exploration_id": ex,
                }
            )
        graphs.sort(
            key=lambda g: node_object(owner, g["entity_id"], 1, "SEED")["id"],
            reverse=True,
        )
        for g in graphs:
            start(c, owner, g["entity_id"], g["exploration_id"])
    assert drain(db) == 1
    with db.engine.begin() as c:
        for g in graphs:
            run = sql(
                c,
                "insert into evaluation_runs(user_id,response_id,evaluator_type,evaluator_version,rubric_version,result,confidence,feedback,status) values (:u,:r,'DETERMINISTIC','deterministic-evaluation/v1','rubric-v1','SUPPORTED',.8,'bounded','SUCCEEDED') returning id",
                u=owner,
                r=g["response_id"],
            ).scalar_one()
            evidence(c, g, run, evaluation_confidence=0.8)
    assert drain(db) == 1
    changes = state(db, owner)["changes"]
    assert [x[0] for x in changes] == list(range(1, 8))
    assert [x[1] for x in changes] == ["REGION_ADDED"] + ["NODE_ADDED"] * 3 + [
        "NODE_GROWTH_CHANGED"
    ] * 3
    for group in [changes[1:4], changes[4:]]:
        ids = [x[2]["object"]["id"] for x in group]
        assert ids == sorted(ids)
    reconstructed = {"REGION": {}, "NODE": {}}
    for revision, kind, payload in changes:
        assert (
            set(payload) == {"schema_version", "object"}
            and payload["schema_version"] == "world-delta/v1"
        )
        key = "REGION" if kind == "REGION_ADDED" else "NODE"
        obj = payload["object"]
        if key == "NODE":
            assert obj["revision"] == revision
        reconstructed[key][obj["id"]] = obj
    with db.engine.connect() as c:
        for table, kind, keys, order in [
            ("world_regions", "REGION", REGION_KEYS, ("region_key", "id")),
            ("world_nodes", "NODE", NODE_KEYS, ("entity_id", "id")),
        ]:
            actual = [
                {k: public_values(dict(r))[k] for k in keys}
                for r in sql(
                    c, f"select * from {table} where user_id=:u", u=owner
                ).mappings()
            ]
            assert sorted(actual, key=lambda o: tuple(o[k] for k in order)) == sorted(
                reconstructed[kind].values(), key=lambda o: tuple(o[k] for k in order)
            )
        assert (
            sql(
                c,
                "select current_revision from learner_worlds where user_id=:u",
                u=owner,
            ).scalar_one()
            == 7
        )
        for table in ["world_connections", "world_artifacts"]:
            assert (
                sql(
                    c, f"select count(*) from {table} where user_id=:u", u=owner
                ).scalar_one()
                == 0
            )


def test_exhausted_unprocessed_claim_terminalizes_without_recomputing(
    monkeypatch, isolated_migrated_database
):
    from app.learning import projection_worker

    db = isolated_migrated_database
    g = graph(db)
    with db.engine.begin() as c:
        sql(
            c,
            "update jobs set status='RUNNING',attempt_count=3,locked_at=clock_timestamp()-interval '61 seconds',locked_by='old' where user_id=:u",
            u=g["user_id"],
        )

    async def unexpected_prepare(*args, **kwargs):
        raise AssertionError("Exhaustion must not spend a fourth reduction/lease")

    monkeypatch.setattr(projection_worker, "prepare", unexpected_prepare)

    async def exercise(factory):
        claim = await projection_worker.claim_job(factory)
        assert claim.exhausted and claim.attempt == 3
        assert await projection_worker.process_claim(factory, claim)

    asyncio.run(worker(db, exercise))
    assert (
        state(db, g["user_id"])["checkpoint"] == 0
        and not state(db, g["user_id"])["root"]
    )
    with db.engine.connect() as c:
        assert sql(
            c,
            "select failure_code,blocking_group from learner_projection_checkpoints where user_id=:u",
            u=g["user_id"],
        ).one() == (
            "RETRY_EXHAUSTED",
            sql(
                c,
                "select payload->>'source_group' from jobs where user_id=:u",
                u=g["user_id"],
            ).scalar_one(),
        )
        assert (
            sql(
                c, "select status from jobs where user_id=:u", u=g["user_id"]
            ).scalar_one()
            == "FAILED"
        )
