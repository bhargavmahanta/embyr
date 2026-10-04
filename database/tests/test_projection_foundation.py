"""M6 capture persistence and security under real PostgreSQL transactions."""

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Event
from uuid import uuid4

import pytest
from alembic import command
from conftest import make_alembic_config
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from test_evaluation_supersession import (
    EVIDENCE_INSERT,
    _evidence_parameters,
    _insert_evaluation,
    _response_graph,
)
from test_learner_state_schema import _insert_objective_state
from test_worldmodel_schema import _insert_node, _insert_region, _insert_world


def execute(c, sql, **args):
    return c.execute(text(sql), args)


def evidence(c, graph, run, **overrides):
    return c.scalar(
        EVIDENCE_INSERT,
        _evidence_parameters(
            graph,
            run,
            evidence_type="RECOGNITION",
            evidence_strength="WEAK",
            **overrides,
        ),
    )


def validate_receipt(row):
    schema = json.loads(
        (Path(__file__).parents[2] / "docs/api/schemas/m6-v1.schema.json").read_text()
    )
    payload = {
        key: row[key]
        for key in schema["$defs"]["projectionInput"]["oneOf"][0]["required"]
    }
    payload["user_id"] = str(payload["user_id"])
    payload["source_time"] = payload["source_time"].isoformat().replace("+00:00", "Z")
    Draft202012Validator(
        {"$ref": "#/$defs/projectionInput", "$defs": schema["$defs"]},
        format_checker=FormatChecker(),
    ).validate(payload)
    assert len(json.dumps(payload, ensure_ascii=False).encode()) <= 8192


def user(connection):
    return connection.scalar(
        text(
            "insert into app_users(auth_provider,auth_subject) "
            "values ('SUPABASE',:subject) returning id"
        ),
        {"subject": str(uuid4())},
    )


def onboard(connection, owner):
    connection.execute(
        text(
            "insert into learner_preferences(user_id,adventure_preference,"
            "preferred_effort,support_style) values (:u,'BALANCED','15_20_MIN','SMALL_HINT')"
        ),
        {"u": owner},
    )
    return connection.scalar(
        text(
            "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) "
            "values (:u,'ONBOARDING_COMPLETED',now(),1,cast(:meta as jsonb)) returning id"
        ),
        {"u": owner, "meta": '{"preferences_version":1}'},
    )


def test_existing_users_require_bootstrap_new_users_start_empty_ready(
    isolated_migration_database,
):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as c:
        old = user(c)
    command.upgrade(config, "head")
    with db.engine.begin() as c:
        new = user(c)
        rows = dict(
            c.execute(
                text("select user_id,bootstrap_state from projection_source_heads")
            ).all()
        )
        assert rows == {old: "REQUIRED", new: "READY"}
        assert (
            c.scalar(text("select max(source_sequence) from projection_source_heads"))
            == 0
        )
        assert (
            c.scalar(text("select count(*) from learner_projection_checkpoints")) == 2
        )


def test_onboarding_commits_one_strict_receipt_and_owned_job(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        event_id = onboard(c, owner)
        group = c.scalar(text("select pg_current_xact_id()::text"))
    with db.engine.connect() as c:
        receipt = c.execute(text("select * from projection_inputs")).mappings().one()
        assert receipt["source_sequence"] == 1
        assert receipt["source_group"] == group
        assert receipt["source_key"] == str(event_id)
        assert receipt["facts"]["preference_version"] == 1
        assert receipt["facts"]["event_type"] == "ONBOARDING_COMPLETED"
        validate_receipt(receipt)
        assert c.scalar(
            text("select payload from jobs where job_type='LEARNER_PROJECTION'")
        ) == {
            "contract_version": "projection-worker/v1",
            "user_id": str(owner),
            "source_group": group,
            "first_source_sequence": 1,
            "last_source_sequence": 1,
        }


def test_migration_roundtrip_preserves_values_null_pins_and_has_no_orm_drift(
    isolated_migration_database,
):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as c:
        graph = _response_graph(c)
        world = _insert_world(c, user_id=graph["user_id"])
        node = _insert_node(
            c, user_id=graph["user_id"], world_id=world, entity_id=graph["entity_id"]
        )
        state = _insert_objective_state(
            c,
            user_id=graph["user_id"],
            objective_id=graph["objective_id"],
            understanding_estimate=0.375,
        )
    for revision in ("head", "0019_response_lock_security", "head"):
        command.upgrade(config, revision) if revision == "head" else command.downgrade(
            config, revision
        )
        with db.engine.connect() as c:
            assert (
                c.scalar(
                    text(
                        "select understanding_estimate from learner_objective_state where id=:id"
                    ),
                    {"id": state},
                )
                == 0.375
            )
            if revision == "head":
                assert (
                    c.scalar(
                        text("select entity_version from world_nodes where id=:id"),
                        {"id": node},
                    )
                    is None
                )
                assert (
                    c.scalar(text("select version_num from alembic_version"))
                    == "0020_learner_projection_foundation"
                )
    command.check(config)


def test_duplicate_regions_abort_upgrade_without_rewriting_history(
    isolated_migration_database,
):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as c:
        owner = user(c)
        world = _insert_world(c, user_id=owner)
        for _ in range(2):
            _insert_region(c, user_id=owner, world_id=world, region_key="same")
    with pytest.raises(DBAPIError, match="M6_REGION_DUPLICATES"):
        command.upgrade(config, "head")
    with db.engine.connect() as c:
        assert c.scalar(text("select count(*) from world_regions")) == 2
        assert (
            c.scalar(text("select version_num from alembic_version"))
            == "0019_response_lock_security"
        )


@pytest.mark.parametrize("version", [0, 2])
def test_world_pin_rejects_nonpositive_or_nonexistent_exact_version(
    isolated_migrated_database, version
):
    with isolated_migrated_database.engine.begin() as c:
        graph = _response_graph(c)
        world = _insert_world(c, user_id=graph["user_id"])
        node = _insert_node(
            c, user_id=graph["user_id"], world_id=world, entity_id=graph["entity_id"]
        )
        with pytest.raises(DBAPIError), c.begin_nested():
            execute(
                c,
                "update world_nodes set entity_version=:v where id=:id",
                v=version,
                id=node,
            )
        execute(c, "update world_nodes set entity_version=1 where id=:id", id=node)


def test_all_twenty_ledger_types_use_closed_owned_facts_and_drop_private_metadata(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
        session, exploration = execute(
            c,
            "select r.assessment_session_id,s.exploration_id from assessment_responses r join assessment_sessions s on s.id=r.assessment_session_id where r.id=:id",
            id=g["response_id"],
        ).one()
        reflection = execute(
            c,
            "insert into reflections(user_id,exploration_id,entity_id,text) values(:u,:ex,:e,'PRIVATE_REFLECTION') returning id",
            u=g["user_id"],
            ex=exploration,
            e=g["entity_id"],
        ).scalar_one()
        reco = execute(
            c,
            "insert into recommendations(user_id,entity_id,entity_version,mode,distance_band,ranking_model_version,score_components,presentation_version,presentation,presented_at) values(:u,:e,1,'EXPLORE','COMFORT','m3','{}','v1','{}',now()) returning id",
            u=g["user_id"],
            e=g["entity_id"],
        ).scalar_one()
        execute(
            c,
            "update explorations set recommendation_id=:r where id=:ex",
            r=reco,
            ex=exploration,
        )
        execute(
            c,
            "insert into explicit_interest_preferences(user_id,entity_id,preference) values(:u,:e,'MORE')",
            u=g["user_id"],
            e=g["entity_id"],
        )
        onboard(c, g["user_id"])
        names = [
            "EXPLICIT_INTEREST_CHANGED",
            "RECOMMENDATION_ACCEPTED",
            "RECOMMENDATION_SKIPPED",
            "EXPLORATION_STARTED",
            "EXPLORATION_WORK_PREPARED",
            "USER_RETURNED",
            "EXPLORATION_PAUSED",
            "EXPLORATION_RESUMED",
            "REFLECTION_SUBMITTED",
            "REFLECTION_UPDATED",
            "ASSESSMENT_STARTED",
            "HINT_REQUESTED",
            "ASSESSMENT_RESPONSE_SUBMITTED",
            "ASSESSMENT_EVALUATED",
            "ASSESSMENT_EVALUATION_FAILED",
            "ASSESSMENT_EVALUATION_RETRY_REQUESTED",
            "ASSESSMENT_COMPLETED",
            "ASSESSMENT_ABANDONED",
            "EXPLORATION_COMPLETED",
        ]
        meta = json.dumps(
            {
                "response_id": str(g["response_id"]),
                "evaluation_run_id": str(run),
                "reflection_id": str(reflection),
                "recommendation_id": str(reco),
                "preference": "MORE",
                "version": 1,
                "answer": "PRIVATE_ANSWER",
                "rubric": "PRIVATE_RUBRIC",
                "motivation": "PRIVATE_MOTIVATION",
                "url": "PRIVATE_SIGNED_URL",
                "token": "PRIVATE_TOKEN",
                "embedding": [99],
                "junk": "PRIVATE_METADATA",
            }
        )
        for name in names:
            execute(
                c,
                "insert into learning_events(user_id,event_type,entity_id,exploration_id,assessment_session_id,occurred_at,schema_version,metadata) values(:u,:name,:e,:ex,:s,now(),1,cast(:m as jsonb))",
                u=g["user_id"],
                name=name,
                e=g["entity_id"],
                ex=None
                if name in ("EXPLICIT_INTEREST_CHANGED", "RECOMMENDATION_SKIPPED")
                else exploration,
                s=session
                if name.startswith("ASSESSMENT_") or name == "HINT_REQUESTED"
                else None,
                m=meta,
            )
    with db.engine.connect() as c:
        rows = (
            execute(c, "select * from projection_inputs order by source_sequence")
            .mappings()
            .all()
        )
        assert len(rows) == 20
        assert [r["source_sequence"] for r in rows] == list(range(1, 21))
        for row in rows:
            validate_receipt(row)
        assert "PRIVATE_" not in json.dumps([r["facts"] for r in rows])
        assert "PRIVATE_" not in json.dumps(
            execute(c, "select payload from jobs").scalars().all()
        )


def test_equivalent_recapture_reuses_sequence_without_job_and_conflict_rolls_back(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        event_id = onboard(c, owner)
    with db.engine.begin() as c:
        assert (
            execute(
                c, "select m6_recapture_event(:u,:e)", u=owner, e=event_id
            ).scalar_one()
            == 1
        )
        row = execute(c, "select * from projection_inputs").mappings().one()
        contradictory = {**row["facts"], "preference_version": 999}
        with pytest.raises(DBAPIError, match="M6_SOURCE_CONFLICT"), c.begin_nested():
            execute(
                c,
                "select m6_append_input(:u,'LEDGER',:key,:time,cast(:facts as jsonb),:e,null)",
                u=owner,
                key=str(event_id),
                time=row["source_time"],
                facts=json.dumps(contradictory),
                e=event_id,
            )
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 1
        )
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 1
        assert execute(c, "select count(*) from jobs").scalar_one() == 1


def test_source_capture_all_rolls_back_and_next_commit_has_no_gap(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
    with db.engine.connect() as c:
        tx = c.begin()
        event_id = onboard(c, owner)
        execute(c, "select m6_recapture_event(:u,:e)", u=owner, e=event_id)
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 1
        tx.rollback()
    with db.engine.begin() as c:
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 0
        )
        assert execute(c, "select count(*) from jobs").scalar_one() == 0
        assert execute(c, "select count(*) from learning_events").scalar_one() == 0
        assert execute(c, "select count(*) from learner_preferences").scalar_one() == 0
        onboard(c, owner)
    with db.engine.connect() as c:
        assert (
            execute(c, "select source_sequence from projection_inputs").scalar_one()
            == 1
        )


def test_evidence_retire_replace_reads_final_run_and_retains_each_transition(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
        old = evidence(c, g, run)
    with db.engine.begin() as c:
        before = execute(c, "select clock_timestamp()").scalar_one()
        assert execute(
            c, "select m6_lock_source_owner(:u)", u=g["user_id"]
        ).scalar_one()
        execute(
            c, "update learning_evidence set status='SUPERSEDED' where id=:e", e=old
        )
        execute(c, "update evaluation_runs set status='SUPERSEDED' where id=:r", r=run)
        replacement = _insert_evaluation(
            c, user_id=g["user_id"], response_id=g["response_id"], supersedes_id=run
        )
        new = evidence(c, g, replacement)
        group = execute(c, "select pg_current_xact_id()::text").scalar_one()
    with db.engine.begin() as c:
        assert execute(
            c, "select m6_lock_source_owner(:u)", u=g["user_id"]
        ).scalar_one()
        execute(c, "update learning_evidence set status='REVOKED' where id=:e", e=old)
        execute(c, "update evaluation_runs set status='REVOKED' where id=:r", r=run)
    with db.engine.connect() as c:
        rows = (
            execute(c, "select * from projection_inputs order by source_sequence")
            .mappings()
            .all()
        )
        assert [r["source_key"] for r in rows] == [
            f"{old}:ACTIVE",
            f"{old}:SUPERSEDED",
            f"{new}:ACTIVE",
            f"{old}:REVOKED",
        ]
        assert [r["facts"]["evaluation_status"] for r in rows] == [
            "SUCCEEDED",
            "SUPERSEDED",
            "SUCCEEDED",
            "REVOKED",
        ]
        assert rows[1]["source_group"] == rows[2]["source_group"] == group
        from datetime import datetime

        assert (
            datetime.fromisoformat(
                rows[1]["facts"]["transition_at"].replace("Z", "+00:00")
            )
            >= before
        )
        for row in rows:
            validate_receipt(row)


@pytest.mark.parametrize(
    "override",
    [
        {"support_level": "EXPLANATION"},
        {"evaluation_confidence": 0.7},
        {"evidence_type": "RECALL"},
        {"evidence_strength": "STRONG"},
        {"evaluation_confidence": float("nan")},
    ],
)
def test_bad_evidence_rolls_back_source_and_all_metadata(
    isolated_migrated_database, override
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
    with pytest.raises(DBAPIError), db.engine.begin() as c:
        args = _evidence_parameters(
            g, run, evidence_type="RECOGNITION", evidence_strength="WEAK"
        )
        args.update(override)
        c.execute(EVIDENCE_INSERT, args)
    with db.engine.connect() as c:
        for table in ("learning_evidence", "projection_inputs", "jobs"):
            assert execute(c, f"select count(*) from {table}").scalar_one() == 0
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 0
        )


@pytest.mark.parametrize("role", ["app_backend", "app_worker"])
@pytest.mark.parametrize(
    "operation",
    [
        "update projection_inputs set facts='{}'",
        "delete from projection_inputs",
        "insert into projection_inputs(user_id) values(gen_random_uuid())",
    ],
)
def test_runtime_roles_cannot_mutate_receipts(
    isolated_migrated_database, role, operation
):
    with isolated_migrated_database.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with isolated_migrated_database.engine.begin() as c:
        execute(c, f"set local role {role}")
        execute(c, "select set_config('app.user_id',:u,true)", u=str(owner))
        with pytest.raises(DBAPIError), c.begin_nested():
            execute(c, operation)


def test_backend_owner_checks_safe_path_and_cannot_advance_metadata(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a, b = user(c), user(c)
        event_a, event_b = onboard(c, a), onboard(c, b)
    with db.engine.begin() as c:
        # Caller-controlled temp relations cannot shadow qualified references.
        execute(c, "create temp table learning_events(id uuid,user_id uuid)")
        execute(c, "create temp table app_users(id uuid)")
        execute(c, "set local search_path=pg_temp,public,pg_catalog")
        execute(c, "set local role app_backend")
        execute(c, "select set_config('app.user_id',:u,true)", u=str(a))
        assert (
            execute(
                c, "select public.m6_recapture_event(:u,:e)", u=a, e=event_a
            ).scalar_one()
            == 1
        )
        for args in ({"u": a, "e": event_b}, {"u": b, "e": event_b}):
            with pytest.raises(DBAPIError, match="M6_SOURCE_OWNER"), c.begin_nested():
                c.execute(text("select public.m6_recapture_event(:u,:e)"), args)
        assert (
            execute(c, "select count(*) from public.projection_inputs").scalar_one()
            == 1
        )
        for sql in (
            "update public.projection_source_heads set bootstrap_state='READY'",
            "update public.learner_projection_checkpoints set processed_source_sequence=1",
            "select public.m6_append_input(null,null,null,null,null,null,null)",
        ):
            with pytest.raises(DBAPIError), c.begin_nested():
                execute(c, sql)


def test_deletion_is_owner_isolated_idempotent_and_removes_claimed_jobs(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a, b = user(c), user(c)
        onboard(c, a)
        onboard(c, b)
    with db.engine.begin() as c:
        execute(
            c,
            "update jobs set status='RUNNING',locked_by='claim',locked_at=now() where user_id=:u",
            u=a,
        )
        execute(c, "set local role app_worker")
        execute(c, "select maintenance_delete_account(:u)", u=a)
        execute(c, "select maintenance_delete_account(:u)", u=a)
    with db.engine.connect() as c:
        for table in (
            "jobs",
            "projection_inputs",
            "projection_source_heads",
            "learner_projection_checkpoints",
        ):
            assert execute(
                c, f"select distinct user_id from {table}"
            ).scalars().all() == [b]
        assert execute(c, "select id from app_users").scalars().all() == [b]


def test_deletion_failure_restores_all_new_and_old_facts(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
        execute(
            c,
            "create function public.m6_test_fault() returns trigger language plpgsql as $$ begin raise exception 'DELETE_FAULT'; end $$",
        )
        execute(
            c,
            "create trigger m6_test_fault before delete on public.learner_preferences for each row execute function public.m6_test_fault()",
        )
    with pytest.raises(DBAPIError, match="DELETE_FAULT"), db.engine.begin() as c:
        execute(c, "set local role app_worker")
        execute(c, "select maintenance_delete_account(:u)", u=a)
    with db.engine.connect() as c:
        for table in (
            "app_users",
            "jobs",
            "projection_inputs",
            "projection_source_heads",
            "learner_projection_checkpoints",
            "learning_events",
            "learner_preferences",
        ):
            assert execute(c, f"select count(*) from {table}").scalar_one() == 1


def test_same_user_serializes_other_user_progresses_and_rollback_has_no_gap(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a, b = user(c), user(c)
        onboard(c, a)
        onboard(c, b)
    waiting = Event()

    def capture(owner):
        with db.engine.begin() as c:
            execute(c, "set local statement_timeout='10s'")
            event_id = execute(
                c,
                "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) values(:u,'ONBOARDING_COMPLETED',now(),1,jsonb_build_object('preferences_version',1)) returning id",
                u=owner,
            ).scalar_one()
            waiting.set()
            return execute(
                c, "select m6_recapture_event(:u,:e)", u=owner, e=event_id
            ).scalar_one()

    with db.engine.connect() as c, ThreadPoolExecutor(max_workers=2) as pool:
        tx = c.begin()
        execute(
            c,
            "select source_sequence from projection_source_heads where user_id=:u for no key update",
            u=a,
        )
        same = pool.submit(capture, a)
        assert waiting.wait(3)
        other = pool.submit(capture, b)
        assert other.result(timeout=5) == 2
        assert not same.done()
        tx.rollback()
        assert same.result(timeout=5) == 2


def test_large_group_has_one_complete_job_across_page_boundaries(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
        execute(
            c,
            "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) select :u,'ONBOARDING_COMPLETED',now(),1,jsonb_build_object('preferences_version',1) from generate_series(1,501)",
            u=a,
        )
        grp = execute(c, "select pg_current_xact_id()::text").scalar_one()
    with db.engine.connect() as c:
        assert execute(
            c,
            "select count(*),min(source_sequence),max(source_sequence) from projection_inputs",
        ).one() == (502, 1, 502)
        assert (
            execute(
                c, "select count(distinct source_group) from projection_inputs"
            ).scalar_one()
            == 1
        )
        assert execute(c, "select payload from jobs").scalar_one() == {
            "contract_version": "projection-worker/v1",
            "user_id": str(a),
            "source_group": grp,
            "first_source_sequence": 1,
            "last_source_sequence": 502,
        }


@pytest.mark.parametrize(
    "change",
    [
        {"contract_version": None},
        {"user_id": None},
        {"source_group": None},
        {"source_group": 123},
        {"contract_version": 1},
        {"first_source_sequence": None},
        {"last_source_sequence": 1.5},
        {"first_source_sequence": 0},
        {"last_source_sequence": 2},
        {"answer": "PRIVATE_ANSWER"},
    ],
)
def test_projection_job_rejects_null_wrong_types_and_incomplete_ranges(
    isolated_migrated_database, change
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
    with pytest.raises(DBAPIError), db.engine.begin() as c:
        old = execute(c, "select payload from jobs").scalar_one()
        execute(c, "delete from jobs")
        execute(
            c,
            "insert into jobs(user_id,job_type,status,payload) values(:u,'LEARNER_PROJECTION','PENDING',cast(:p as jsonb))",
            u=a,
            p=json.dumps({**old, **change}),
        )


def test_receipt_size_failure_rolls_back_allocation(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        event_id = onboard(c, a)
        with pytest.raises(DBAPIError, match="M6_RECEIPT_TOO_LARGE"), c.begin_nested():
            execute(
                c,
                "select m6_append_input(:u,'LEDGER',:key,now(),cast(:f as jsonb),:e,null)",
                u=a,
                key=str(event_id),
                f=json.dumps({"event_id": str(event_id), "oversized": "x" * 8192}),
                e=event_id,
            )
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 0
        )


def test_clients_have_no_metadata_or_privileged_function_access_even_with_unsafe_defaults(
    isolated_migration_database,
):
    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as c:
        for role in ("anon", "authenticated", "service_role"):
            if not execute(
                c, "select 1 from pg_roles where rolname=:r", r=role
            ).scalar():
                execute(c, f"create role {role} nologin")
        # Model unexpectedly permissive defaults on the actual migration owner.
        execute(
            c,
            "alter default privileges in schema public grant all on tables to anon,authenticated,service_role",
        )
        execute(
            c,
            "alter default privileges in schema public grant execute on functions to anon,authenticated,service_role",
        )
    command.upgrade(config, "head")
    with db.engine.begin() as c:
        for role in ("anon", "authenticated", "service_role"):
            execute(c, f"set local role {role}")
            for table in (
                "projection_inputs",
                "projection_source_heads",
                "learner_projection_checkpoints",
            ):
                with pytest.raises(DBAPIError), c.begin_nested():
                    execute(c, f"select * from public.{table}")
            for sql in (
                "select m6_lock_source_owner(gen_random_uuid())",
                "select m6_append_input(null,null,null,null,null,null,null)",
                "select m6_recapture_event(gen_random_uuid(),gen_random_uuid())",
            ):
                with (
                    pytest.raises(DBAPIError, match="permission denied"),
                    c.begin_nested(),
                ):
                    execute(c, sql)
            execute(c, "reset role")


def test_deleted_owner_cannot_be_resurrected_by_late_source_or_job(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
    waiting = Event()

    def late():
        with pytest.raises(DBAPIError), db.engine.begin() as c:
            execute(c, "set local role app_worker")
            waiting.set()
            execute(
                c,
                "insert into learning_events(user_id,event_type,occurred_at,schema_version) values(:u,'ONBOARDING_COMPLETED',now(),1)",
                u=a,
            )

    with db.engine.connect() as c, ThreadPoolExecutor(max_workers=1) as pool:
        tx = c.begin()
        execute(c, "set local role app_worker")
        execute(c, "select maintenance_delete_account(:u)", u=a)
        task = pool.submit(late)
        assert waiting.wait(3)
        tx.commit()
        task.result(timeout=5)
    with db.engine.connect() as c:
        for table in (
            "jobs",
            "learning_events",
            "projection_inputs",
            "projection_source_heads",
            "learner_projection_checkpoints",
            "app_users",
        ):
            assert execute(c, f"select count(*) from {table}").scalar_one() == 0


def test_hosted_owner_can_upgrade_0020_with_noninherited_maintenance_role(
    isolated_migration_server,
):
    from sqlalchemy.engine import make_url

    db = isolated_migration_server
    with db.engine.begin() as c:
        for role in ("anon", "authenticated", "service_role"):
            execute(c, f"create role {role} nologin")
        execute(c, "grant app_maintenance to app_owner with inherit false, set true")
        # These are installed by Supabase before Embyr migrations.
        execute(c, "create extension if not exists pgcrypto")
        execute(c, "create extension if not exists vector")
    owner_config = make_alembic_config(
        make_url(db.url)
        .set(username="app_owner")
        .render_as_string(hide_password=False)
    )
    command.upgrade(owner_config, "0019_response_lock_security")
    with db.engine.connect() as c:
        assert not execute(
            c, "select pg_has_role('app_owner','app_maintenance','USAGE')"
        ).scalar_one()
        assert execute(
            c, "select pg_has_role('app_owner','app_maintenance','SET')"
        ).scalar_one()
    command.upgrade(owner_config, "head")
    with db.engine.connect() as c:
        assert (
            execute(c, "select version_num from alembic_version").scalar_one()
            == "0020_learner_projection_foundation"
        )
        assert (
            execute(
                c,
                "select pg_get_userbyid(proowner) from pg_proc where "
                "oid='public.m6_append_input(uuid,text,text,timestamptz,jsonb,uuid,uuid)'::regprocedure",
            ).scalar_one()
            == "app_maintenance"
        )
        for role in ("anon", "authenticated", "service_role"):
            assert not execute(
                c,
                "select has_function_privilege(:role,"
                "'public.m6_append_input(uuid,text,text,timestamptz,jsonb,uuid,uuid)',"
                "'EXECUTE')",
                role=role,
            ).scalar_one()


def test_non_superuser_migration_owner_sees_preflight_and_initializes_old_users(
    isolated_migration_database,
):
    from sqlalchemy.engine import make_url

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as c:
        a = user(c)
        # Match ownership established when a provisioned app_owner applies M1.
        tables = (
            execute(c, "select tablename from pg_tables where schemaname='public'")
            .scalars()
            .all()
        )
        for table in tables:
            execute(c, f'alter table public."{table}" owner to app_owner')
    owner_config = make_alembic_config(
        make_url(db.url).set(username="app_owner").render_as_string(hide_password=False)
    )
    command.upgrade(owner_config, "head")
    with db.engine.connect() as c:
        assert (
            execute(
                c,
                "select bootstrap_state from projection_source_heads where user_id=:u",
                u=a,
            ).scalar_one()
            == "REQUIRED"
        )
    with db.engine.begin() as c:
        onboard(c, a)
    command.downgrade(owner_config, "0019_response_lock_security")
    with db.engine.connect() as c:
        assert (
            execute(
                c, "select count(*) from jobs where job_type='LEARNER_PROJECTION'"
            ).scalar_one()
            == 0
        )
        assert execute(c, "select count(*) from learning_events").scalar_one() == 1
    command.upgrade(owner_config, "head")


def test_forcing_constraints_immediate_cannot_commit_stale_run_snapshot(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
        ev = evidence(c, g, run)
    with (
        pytest.raises(DBAPIError, match="M6_FINAL_STATUS_CHANGED"),
        db.engine.begin() as c,
    ):
        execute(c, "select m6_lock_source_owner(:u)", u=g["user_id"])
        execute(c, "set constraints all immediate")
        execute(
            c,
            "update learning_evidence set status='SUPERSEDED' where id=:id",
            id=ev,
        )
        execute(
            c, "update evaluation_runs set status='SUPERSEDED' where id=:id", id=run
        )
    with db.engine.connect() as c:
        assert (
            execute(
                c, "select status from learning_evidence where id=:id", id=ev
            ).scalar_one()
            == "ACTIVE"
        )
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 1


def test_fenced_correction_and_deletion_complete_without_deadlock(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
        ev = evidence(c, g, run)
    started = Event()

    def deletion():
        with db.engine.begin() as c:
            execute(c, "set local role app_worker")
            execute(c, "set local statement_timeout='10s'")
            started.set()
            execute(c, "select maintenance_delete_account(:u)", u=g["user_id"])

    with db.engine.connect() as c, ThreadPoolExecutor(max_workers=1) as pool:
        tx = c.begin()
        execute(c, "set local role app_worker")
        assert execute(
            c, "select m6_lock_source_owner(:u)", u=g["user_id"]
        ).scalar_one()
        execute(c, "update learning_evidence set status='SUPERSEDED' where id=:e", e=ev)
        execute(c, "update evaluation_runs set status='SUPERSEDED' where id=:r", r=run)
        task = pool.submit(deletion)
        assert started.wait(3)
        tx.commit()
        task.result(timeout=5)
    with db.engine.connect() as c:
        assert execute(c, "select count(*) from app_users").scalar_one() == 0
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 0


@pytest.mark.parametrize(
    "metadata",
    [
        {"reflection_id": str(uuid4())},
        {"reflection_id": "PRIVATE_BAD_UUID"},
    ],
)
def test_invalid_typed_reflection_reference_fails_capture_without_private_error(
    isolated_migrated_database, metadata
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        exploration = execute(
            c,
            "select s.exploration_id from assessment_responses r join assessment_sessions s on s.id=r.assessment_session_id where r.id=:id",
            id=g["response_id"],
        ).scalar_one()
    with (
        pytest.raises(DBAPIError, match="M6_SOURCE_LINEAGE") as error,
        db.engine.begin() as c,
    ):
        execute(
            c,
            "insert into learning_events(user_id,event_type,entity_id,exploration_id,occurred_at,schema_version,metadata) values(:u,'REFLECTION_SUBMITTED',:e,:ex,now(),1,cast(:m as jsonb))",
            u=g["user_id"],
            e=g["entity_id"],
            ex=exploration,
            m=json.dumps(metadata),
        )
    assert "PRIVATE_BAD_UUID" not in str(error.value.orig)
    with db.engine.connect() as c:
        assert execute(c, "select count(*) from learning_events").scalar_one() == 0
        assert execute(c, "select count(*) from jobs").scalar_one() == 0


@pytest.mark.parametrize(
    "event_type,schema_version", [("FUTURE_EVENT", 1), ("ONBOARDING_COMPLETED", 2)]
)
def test_unknown_event_vocabulary_or_version_aborts_source(
    isolated_migrated_database, event_type, schema_version
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
    with (
        pytest.raises(DBAPIError, match="M6_UNSUPPORTED_SOURCE"),
        db.engine.begin() as c,
    ):
        execute(
            c,
            "insert into learning_events(user_id,event_type,occurred_at,schema_version) values(:u,:t,now(),:v)",
            u=a,
            t=event_type,
            v=schema_version,
        )
    with db.engine.connect() as c:
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 0
        )


def test_missing_metadata_does_not_reclassify_old_user_as_ready(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        execute(c, "set local role app_maintenance")
        execute(c, "delete from projection_source_heads where user_id=:u", u=a)
    with (
        pytest.raises(DBAPIError, match="M6_SOURCE_HEAD_MISSING"),
        db.engine.begin() as c,
    ):
        onboard(c, a)
    with db.engine.connect() as c:
        assert (
            execute(c, "select count(*) from projection_source_heads").scalar_one() == 0
        )
        assert execute(c, "select count(*) from jobs").scalar_one() == 0


def test_cross_owner_and_version_drift_are_rejected_before_evidence_receipt(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        other = _response_graph(c)
        run = _insert_evaluation(c, user_id=g["user_id"], response_id=g["response_id"])
    with pytest.raises(DBAPIError), db.engine.begin() as c:
        evidence(c, g, run, source_id=other["response_id"])
    with db.engine.begin() as c:
        execute(
            c,
            "insert into learning_entity_versions(entity_id,version,title,summary,knowledge_types,scope) values(:e,2,'v2','summary',array['CONCEPTUAL'],'NORMAL')",
            e=g["entity_id"],
        )
        with (
            pytest.raises(DBAPIError, match="cannot change entity version"),
            c.begin_nested(),
        ):
            execute(
                c,
                "update learning_objectives set entity_version=2 where id=:o",
                o=g["objective_id"],
            )
        wrong_objective = execute(
            c,
            "insert into learning_objectives(entity_id,entity_version,objective_type,description,importance) values(:e,2,'RECOGNITION','Other version',1) returning id",
            e=g["entity_id"],
        ).scalar_one()
    with pytest.raises(DBAPIError), db.engine.begin() as c:
        evidence(c, g, run, objective_id=wrong_objective)
    with db.engine.connect() as c:
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 0


def test_storage_guard_rejects_extra_private_fact_keys_even_for_maintenance(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
    with db.engine.begin() as c:
        new_event = execute(
            c,
            "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) values(:u,'ONBOARDING_COMPLETED',now(),1,jsonb_build_object('preferences_version',1)) returning id",
            u=a,
        ).scalar_one()
        execute(c, "set local role app_maintenance")
        with pytest.raises(DBAPIError, match="M6_FACT_SHAPE"), c.begin_nested():
            execute(
                c,
                "insert into projection_inputs(user_id,source_sequence,source_kind,source_key,source_group,source_time,facts,ledger_event_id) select user_id,2,source_kind,cast(:e as text),source_group,source_time,facts||jsonb_build_object('event_id',cast(:e as text),'reflection_text','PRIVATE_REFLECTION'),cast(cast(:e as text) as uuid) from projection_inputs",
                e=str(new_event),
            )


def test_baseline_reference_can_cover_existing_groups_without_bootstrap_operator(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
    with db.engine.begin() as c:
        cutoff = execute(c, "select clock_timestamp()").scalar_one()
        # Exercise storage/job capability only, not an import/replay operator.
        execute(
            c,
            "update projection_source_heads set baseline_through_sequence=2,cutoff_source_sequence=1,cutoff_at=:t where user_id=:u",
            t=cutoff,
            u=a,
        )
        marker = {
            "cutoff_source_sequence": 1,
            "cutoff_at": cutoff.isoformat().replace("+00:00", "Z"),
        }
        group = execute(c, "select pg_current_xact_id()::text").scalar_one()
        assert (
            execute(
                c,
                "select m6_append_input(:u,'BOOTSTRAP','learner-projection/v1:baseline',:t,cast(:f as jsonb),null,null)",
                u=a,
                t=cutoff,
                f=json.dumps(marker),
            ).scalar_one()
            == 2
        )
    with db.engine.connect() as c:
        payload = execute(
            c, "select payload from jobs where payload->>'source_group'=:g", g=group
        ).scalar_one()
        assert (payload["first_source_sequence"], payload["last_source_sequence"]) == (
            1,
            2,
        )
        assert (
            execute(
                c,
                "select processed_source_sequence from learner_projection_checkpoints",
            ).scalar_one()
            == 0
        )


def test_downgrade_cannot_invent_numeric_estimate_for_null_projection(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        g = _response_graph(c)
        state = _insert_objective_state(
            c,
            user_id=g["user_id"],
            objective_id=g["objective_id"],
            understanding_estimate=None,
        )
    with pytest.raises(DBAPIError, match="M6_DOWNGRADE_NULL_ESTIMATE"):
        command.downgrade(make_alembic_config(db.url), "0019_response_lock_security")
    with db.engine.connect() as c:
        assert (
            execute(
                c,
                "select understanding_estimate from learner_objective_state where id=:s",
                s=state,
            ).scalar_one()
            is None
        )
        assert (
            execute(c, "select version_num from alembic_version").scalar_one()
            == "0020_learner_projection_foundation"
        )


@pytest.mark.parametrize(
    "timestamp",
    ["infinity", "-infinity", "10000-01-01 00:00:00+00", "0001-01-01 00:00:00+00 BC"],
)
def test_non_rfc3339_source_time_aborts_source_and_capture(
    isolated_migrated_database, timestamp
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        a = user(c)
        onboard(c, a)
    with pytest.raises(DBAPIError, match="M6_SOURCE_TIME"), db.engine.begin() as c:
        execute(
            c,
            "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) values(:u,'ONBOARDING_COMPLETED',cast(:t as timestamptz),1,jsonb_build_object('preferences_version',1))",
            u=a,
            t=timestamp,
        )
    with db.engine.connect() as c:
        assert execute(c, "select count(*) from learning_events").scalar_one() == 1
        assert (
            execute(
                c, "select source_sequence from projection_source_heads"
            ).scalar_one()
            == 1
        )


def projection_role(c, role, owner):
    # Match a direct runtime login, including role='none'. A guard based only on
    # current_setting('role') would miss these connections. LOCAL resets on exit.
    execute(c, f"set local session authorization {role}")
    execute(c, "select set_config('app.user_id',:u,true)", u=str(owner))
    assert execute(
        c, "select current_user,session_user,current_setting('role')"
    ).one() == (role, role, "none")


def test_backend_cannot_insert_projection_job_directly(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with db.engine.begin() as c:
        payload = execute(c, "select payload from jobs").scalar_one()
        execute(c, "delete from jobs")
        projection_role(c, "app_backend", owner)
        with pytest.raises(DBAPIError, match="M6_JOB_ROLE") as error, c.begin_nested():
            execute(
                c,
                "insert into jobs(user_id,job_type,status,payload) values(:u,'LEARNER_PROJECTION','PENDING',cast(:p as jsonb))",
                u=owner,
                p=json.dumps(payload),
            )
        assert error.value.orig.sqlstate == "42501"
        assert execute(c, "select count(*) from jobs").scalar_one() == 0


@pytest.mark.parametrize(
    "change",
    [
        "status='SUCCEEDED'",
        "status='FAILED'",
        "attempt_count=1",
        "locked_at=now()",
        "locked_by='request'",
        "available_at=now()+interval '1 hour'",
        "completed_at=now()",
        "payload=payload",
        "user_id=user_id",
        "job_type='ASSESSMENT_EVALUATION'",
    ],
)
def test_backend_cannot_update_projection_job(isolated_migrated_database, change):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with db.engine.begin() as c:
        before = execute(c, "select to_jsonb(j) from jobs j").scalar_one()
        projection_role(c, "app_backend", owner)
        with pytest.raises(DBAPIError, match="M6_JOB_ROLE") as error, c.begin_nested():
            execute(c, f"update jobs set {change} where user_id=:u", u=owner)
        assert error.value.orig.sqlstate == "42501"
        assert execute(c, "select to_jsonb(j) from jobs j").scalar_one() == before


@pytest.mark.parametrize(
    "change",
    [
        "status='SUCCEEDED'",
        "status='FAILED'",
        "attempt_count=1",
        "locked_at=now()",
        "locked_by='maintenance'",
        "available_at=now()+interval '1 hour'",
        "completed_at=now()",
    ],
)
def test_capture_role_cannot_change_projection_lifecycle_even_in_source_group(
    isolated_migrated_database, change
):
    with isolated_migrated_database.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
        execute(c, "set constraints all immediate")
        execute(c, "set local role app_maintenance")
        with pytest.raises(DBAPIError, match="M6_JOB_LIFECYCLE"), c.begin_nested():
            execute(c, f"update jobs set {change} where user_id=:u", u=owner)


@pytest.mark.parametrize(
    "change",
    [
        "status='RUNNING'",
        "attempt_count=1",
        "locked_at=now()",
        "locked_by='claim'",
        "completed_at=now()",
    ],
)
def test_projection_job_initial_state_is_pending_unclaimed(
    isolated_migrated_database, change
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with db.engine.begin() as c:
        row = execute(c, "select to_jsonb(j) from jobs j").scalar_one()
        execute(c, "delete from jobs")
        execute(c, "set local role app_maintenance")
        column, value = change.split("=", 1)
        with pytest.raises(DBAPIError, match="M6_JOB_INITIAL_STATE"), c.begin_nested():
            if column == "status":
                execute(
                    c,
                    f"insert into jobs(user_id,job_type,status,payload) values(:u,'LEARNER_PROJECTION',{value},cast(:p as jsonb))",
                    u=owner,
                    p=json.dumps(row["payload"]),
                )
            else:
                execute(
                    c,
                    f"insert into jobs(user_id,job_type,status,payload,{column}) values(:u,'LEARNER_PROJECTION','PENDING',cast(:p as jsonb),{value})",
                    u=owner,
                    p=json.dumps(row["payload"]),
                )


def test_backend_sources_still_create_and_extend_one_trusted_pending_job(
    isolated_migrated_database,
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
    with db.engine.begin() as c:
        projection_role(c, "app_backend", owner)
        onboard(c, owner)
        execute(
            c,
            "insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata) select :u,'ONBOARDING_COMPLETED',now(),1,jsonb_build_object('preferences_version',1) from generate_series(1,2)",
            u=owner,
        )
    with db.engine.connect() as c:
        row = execute(
            c,
            "select status,attempt_count,locked_at,locked_by,completed_at,payload from jobs",
        ).one()
        assert row[:5] == ("PENDING", 0, None, None, None)
        assert row.payload["first_source_sequence"] == 1
        assert row.payload["last_source_sequence"] == 3
        assert execute(c, "select count(*) from projection_inputs").scalar_one() == 3


@pytest.mark.parametrize("terminal", ["SUCCEEDED", "FAILED"])
def test_worker_can_update_projection_lifecycle(isolated_migrated_database, terminal):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with db.engine.begin() as c:
        projection_role(c, "app_worker", owner)
        execute(
            c,
            "update jobs set status='RUNNING',attempt_count=attempt_count+1,locked_at=now(),locked_by='future-worker',available_at=now()+interval '1 minute' where user_id=:u",
            u=owner,
        )
    with db.engine.begin() as c:
        projection_role(c, "app_worker", owner)
        execute(
            c,
            "update jobs set status=:s,locked_at=null,locked_by=null,completed_at=now() where user_id=:u",
            u=owner,
            s=terminal,
        )
    with db.engine.connect() as c:
        row = execute(
            c, "select status,attempt_count,locked_at,locked_by,completed_at from jobs"
        ).one()
        assert row[:4] == (terminal, 1, None, None)
        assert row.completed_at is not None


def test_backend_evaluation_job_insert_update_is_unchanged(isolated_migrated_database):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
    with db.engine.begin() as c:
        projection_role(c, "app_backend", owner)
        job = execute(
            c,
            "insert into jobs(user_id,job_type,status,payload) values(:u,'ASSESSMENT_EVALUATION','PENDING','{}') returning id",
            u=owner,
        ).scalar_one()
        execute(
            c,
            "update jobs set status='RUNNING',attempt_count=1,available_at=now(),locked_at=now(),locked_by='request',payload=cast(:p as jsonb) where id=:j",
            j=job,
            p=json.dumps({"retry": True}),
        )
        execute(
            c,
            "update jobs set status='SUCCEEDED',locked_at=null,locked_by=null,completed_at=now() where id=:j",
            j=job,
        )
        row = execute(
            c,
            "select status,attempt_count,payload,completed_at from jobs where id=:j",
            j=job,
        ).one()
        assert row[:3] == ("SUCCEEDED", 1, {"retry": True})
        assert row.completed_at is not None


@pytest.mark.parametrize("status", ["PENDING", "SUCCEEDED"])
def test_maintenance_cannot_convert_other_job_into_projection(
    isolated_migrated_database, status
):
    db = isolated_migrated_database
    with db.engine.begin() as c:
        owner = user(c)
        onboard(c, owner)
    with db.engine.begin() as c:
        payload = execute(c, "select payload from jobs").scalar_one()
        execute(c, "delete from jobs")
        job = execute(
            c,
            "insert into jobs(user_id,job_type,status,attempt_count,payload) values(:u,'ASSESSMENT_EVALUATION',:s,1,cast(:p as jsonb)) returning id",
            u=owner,
            s=status,
            p=json.dumps(payload),
        ).scalar_one()
        execute(c, "set local role app_maintenance")
        with pytest.raises(DBAPIError, match="M6_JOB_IDENTITY"), c.begin_nested():
            execute(
                c, "update jobs set job_type='LEARNER_PROJECTION' where id=:j", j=job
            )
        assert execute(
            c, "select job_type,status from jobs where id=:j", j=job
        ).one() == ("ASSESSMENT_EVALUATION", status)
