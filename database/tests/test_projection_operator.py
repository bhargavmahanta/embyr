"""M6-05 operator gates against the real migration and role boundary."""

import asyncio
import json
import os
import subprocess
import sys
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from pathlib import Path
from threading import Event
from time import perf_counter

import pytest
from alembic import command
from conftest import make_alembic_config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from test_learner_state_schema import _insert_objective, _insert_objective_state
from test_projection_foundation import onboard, user
from test_projection_publisher import graph, worker


@pytest.mark.parametrize(
    "url",
    [
        "not-a-database-url-secretP4ss",
        "postgresql+psycopg://reviewer:secretP4ss@127.0.0.1/embyr_test?sslmode=disable",
    ],
)
def test_cli_engine_configuration_errors_are_bounded(url):
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "app.learning.projection_operator",
            "bootstrap",
            "--user-id",
            "11111111-1111-4111-8111-111111111111",
        ],
        cwd=Path(__file__).resolve().parents[2] / "backend",
        env={**os.environ, "EMBYR_DATABASE_URL": url},
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 1
    assert len(result.stdout.splitlines()) == 1
    assert json.loads(result.stdout) == {
        "status": "REFUSED",
        "category": "DATABASE_ERROR",
    }
    assert result.stderr == ""
    assert "Traceback" not in result.stdout
    assert "secretP4ss" not in result.stdout + result.stderr
    assert url not in result.stdout + result.stderr
    assert "SELECT" not in result.stdout + result.stderr


def test_cli_teardown_error_is_bounded(monkeypatch, capsys):
    import app.learning.projection_operator as operator

    class BrokenEngine:
        async def dispose(self):
            raise RuntimeError("private database teardown detail")

    monkeypatch.setenv("EMBYR_DATABASE_URL", "placeholder")
    monkeypatch.setattr(
        operator, "create_async_database_engine", lambda _: BrokenEngine()
    )
    monkeypatch.setattr(operator, "async_sessionmaker", lambda *a, **kw: object())

    async def successful_bootstrap(*args, **kwargs):
        return {"status": "APPLIED"}

    monkeypatch.setattr(operator, "bootstrap", successful_bootstrap)
    code = asyncio.run(
        operator._main(
            Namespace(
                operation="bootstrap",
                user_id="11111111-1111-4111-8111-111111111111",
                apply=True,
            )
        )
    )
    output = capsys.readouterr()
    assert code == 1
    assert json.loads(output.out) == {"status": "REFUSED", "category": "DATABASE_ERROR"}
    assert output.err == ""
    assert "private database teardown detail" not in output.out + output.err


def test_cli_help_still_parses():
    result = subprocess.run(
        [sys.executable, "-m", "app.learning.projection_operator", "--help"],
        cwd=Path(__file__).resolve().parents[2] / "backend",
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == 0
    assert "bootstrap" in result.stdout
    assert "audit" in result.stdout
    assert "requeue" in result.stdout
    assert result.stderr == ""


def operate(db, action):
    async def run():
        engine = create_async_engine(db.url)
        try:
            return await action(async_sessionmaker(engine, expire_on_commit=False))
        finally:
            await engine.dispose()

    return asyncio.run(run())


def old_user(db):
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
    command.upgrade(config, "head")
    return owner


def old_preference_history(db, changes, *, terminal=None):
    """Create an immutable pre-0020 choice chain and its current row."""
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
        entity, _ = _insert_objective(connection)
        event_ids = []
        for ordinal, (preference, version) in enumerate(changes, start=1):
            if ordinal == 1:
                connection.execute(
                    text("""insert into explicit_interest_preferences
(user_id,entity_id,preference,version) values (:u,:e,:p,:v)"""),
                    {"u": owner, "e": entity, "p": preference, "v": version},
                )
            else:
                connection.execute(
                    text("""update explicit_interest_preferences
set preference=:p,version=:v where user_id=:u and entity_id=:e"""),
                    {"u": owner, "e": entity, "p": preference, "v": version},
                )
            event_ids.append(
                connection.scalar(
                    text("""insert into learning_events
(user_id,event_type,entity_id,occurred_at,schema_version,metadata)
values (:u,'EXPLICIT_INTEREST_CHANGED',:e,
now()+(:ordinal * interval '1 second'),1,cast(:metadata as jsonb)) returning id"""),
                    {
                        "u": owner,
                        "e": entity,
                        "ordinal": ordinal,
                        "metadata": json.dumps(
                            {"preference": preference, "version": version}
                        ),
                    },
                )
            )
        if terminal is not None:
            connection.execute(
                text("""update explicit_interest_preferences
set preference=:p,version=:v where user_id=:u and entity_id=:e"""),
                {"u": owner, "e": entity, "p": terminal[0], "v": terminal[1]},
            )
    command.upgrade(config, "head")
    return owner, entity, event_ids


def test_historical_preference_versions_dry_run_then_apply(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    owner, entity, event_ids = old_preference_history(db, [("MORE", 1), ("PAUSED", 2)])
    preview = operate(db, lambda factory: bootstrap(factory, owner))
    assert preview["status"] == "READY_TO_APPLY"
    assert (preview["ledger_imported"], preview["ledger_reused"]) == (3, 0)
    assert (
        preview["cutoff_source_sequence"],
        preview["baseline_through_sequence"],
    ) == (
        0,
        4,
    )
    with db.engine.connect() as connection:
        assert connection.execute(
            text("""select bootstrap_state,source_sequence
from projection_source_heads where user_id=:u"""),
            {"u": owner},
        ).one() == ("REQUIRED", 0)
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0
        assert (
            connection.scalar(
                text("select count(*) from jobs where job_type='LEARNER_PROJECTION'")
            )
            == 0
        )
    applied = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert applied["status"] == "APPLIED"
    assert (applied["ledger_imported"], applied["ledger_reused"]) == (3, 0)
    with db.engine.connect() as connection:
        rows = connection.execute(
            text("""select source_sequence,source_kind,source_key,facts
from projection_inputs where user_id=:u order by source_sequence"""),
            {"u": owner},
        ).all()
        assert [(row.source_sequence, row.source_kind) for row in rows] == [
            (1, "LEDGER"),
            (2, "LEDGER"),
            (3, "LEDGER"),
            (4, "BOOTSTRAP"),
        ]
        assert [row.source_key for row in rows[1:3]] == [str(id) for id in event_ids]
        assert [
            (
                row.facts["entity_id"],
                row.facts["preference"],
                row.facts["preference_version"],
            )
            for row in rows[1:3]
        ] == [(str(entity), "MORE", 1), (str(entity), "PAUSED", 2)]


@pytest.mark.parametrize(
    "changes,terminal",
    [
        ([("PAUSED", 2)], None),
        ([("MORE", 1), ("PAUSED", 3)], None),
        ([("MORE", 1), ("PAUSED", 1)], None),
        ([("MORE", 1), ("PAUSED", 2)], ("MORE", 2)),
    ],
)
def test_contradictory_historical_preference_chain_rolls_back(
    isolated_migration_database, changes, terminal
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    owner, _, _ = old_preference_history(db, changes, terminal=terminal)
    with pytest.raises(ProjectionError, match="HISTORICAL_PREFERENCE"):
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    with db.engine.connect() as connection:
        assert connection.execute(
            text("""select bootstrap_state,source_sequence
from projection_source_heads where user_id=:u"""),
            {"u": owner},
        ).one() == ("REQUIRED", 0)
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0
        assert (
            connection.scalar(
                text("select count(*) from jobs where job_type='LEARNER_PROJECTION'")
            )
            == 0
        )


def test_historical_preference_overlap_reuses_live_receipt(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    owner, entity, event_ids = old_preference_history(db, [("MORE", 1)])
    with db.engine.begin() as connection:
        prior_sequence = connection.scalar(
            text("select m6_capture_ledger(e) from learning_events e where e.id=:id"),
            {"id": event_ids[0]},
        )
        prior_facts = connection.scalar(
            text("""select facts from projection_inputs
where user_id=:u and source_kind='LEDGER' and source_key=:key"""),
            {"u": owner, "key": str(event_ids[0])},
        )
    with db.engine.begin() as connection:
        connection.execute(
            text("""update explicit_interest_preferences
set preference='PAUSED',version=2 where user_id=:u and entity_id=:e"""),
            {"u": owner, "e": entity},
        )
        connection.execute(
            text("""insert into learning_events
(user_id,event_type,entity_id,occurred_at,schema_version,metadata)
values (:u,'EXPLICIT_INTEREST_CHANGED',:e,now()+interval '2 seconds',1,
cast(:metadata as jsonb))"""),
            {
                "u": owner,
                "e": entity,
                "metadata": json.dumps({"preference": "PAUSED", "version": 2}),
            },
        )
    result = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert result["ledger_reused"] == 2
    assert result["ledger_imported"] == 1
    with db.engine.connect() as connection:
        row = connection.execute(
            text("""select source_sequence,facts from projection_inputs
where user_id=:u and source_kind='LEDGER' and source_key=:key"""),
            {"u": owner, "key": str(event_ids[0])},
        ).one()
        assert row == (prior_sequence, prior_facts)
        assert (
            connection.scalar(
                text("""select count(*) from projection_inputs
where user_id=:u and source_kind='LEDGER' and source_key=:key"""),
                {"u": owner, "key": str(event_ids[0])},
            )
            == 1
        )


def test_historical_onboarding_version_must_match_current_row(
    isolated_migration_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
        connection.execute(
            text("update learner_preferences set version=2 where user_id=:u"),
            {"u": owner},
        )
    command.upgrade(config, "head")
    with pytest.raises(ProjectionError, match="HISTORICAL_PREFERENCE"):
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))


def test_historical_onboarding_preserves_its_nondefault_version(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        connection.execute(
            text("""insert into learner_preferences
(user_id,adventure_preference,preferred_effort,support_style,version)
values (:u,'BALANCED','15_20_MIN','SMALL_HINT',2)"""),
            {"u": owner},
        )
        connection.execute(
            text("""insert into learning_events
(user_id,event_type,occurred_at,schema_version,metadata)
values (:u,'ONBOARDING_COMPLETED',now(),1,
jsonb_build_object('preferences_version',2))"""),
            {"u": owner},
        )
    command.upgrade(config, "head")
    assert (
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))["status"]
        == "APPLIED"
    )
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text("""select facts->>'preference_version' from projection_inputs
where user_id=:u and source_kind='LEDGER'"""),
                {"u": owner},
            )
            == "2"
        )


def test_bootstrap_dry_run_rolls_back_then_apply_is_idempotent(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    owner = old_user(db)
    preview = operate(db, lambda factory: bootstrap(factory, owner))
    assert preview["status"] == "READY_TO_APPLY"
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select source_sequence from projection_source_heads where user_id=:u"
                ),
                {"u": owner},
            )
            == 0
        )
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0
    applied = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert applied["status"] == "APPLIED"
    assert applied["cutoff_source_sequence"] == 0
    assert applied["baseline_through_sequence"] == 1
    assert (
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))["status"]
        == "ALREADY_BOOTSTRAPPED"
    )
    with db.engine.connect() as connection:
        assert connection.scalar(text("select count(*) from projection_inputs")) == 1
        marker = connection.execute(
            text("select source_kind,source_key,facts from projection_inputs")
        ).one()
        assert marker.source_kind == "BOOTSTRAP"
        assert marker.source_key == "learner-projection/v1:baseline"
        assert marker.facts["cutoff_source_sequence"] == 0


def test_bootstrap_imports_historical_ledger_before_marker(
    isolated_migration_database,
):
    from app.learning.projection_operator import audit, bootstrap
    from app.learning.projection_worker import run_once

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        event_id = onboard(connection, owner)
    command.upgrade(config, "head")
    result = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert result["ledger_imported"] == 1
    assert result["cutoff_source_sequence"] == 0
    assert result["baseline_through_sequence"] == 2
    with db.engine.connect() as connection:
        rows = connection.execute(
            text(
                "select source_sequence,source_kind,source_key from projection_inputs where user_id=:u order by source_sequence"
            ),
            {"u": owner},
        ).all()
        assert rows == [
            (1, "LEDGER", str(event_id)),
            (2, "BOOTSTRAP", "learner-projection/v1:baseline"),
        ]
    assert asyncio.run(worker(db, run_once)) is True
    assert operate(db, lambda factory: audit(factory, owner))["status"] == "PASS"


def test_historical_evidence_snapshot_has_unknown_transition_time(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    journey = graph(db)
    command.upgrade(config, "head")
    result = operate(
        db, lambda factory: bootstrap(factory, journey["user_id"], apply=True)
    )
    assert result["evidence_imported"] == 1
    with db.engine.connect() as connection:
        row = connection.execute(
            text(
                "select source_kind,source_key,facts from projection_inputs where user_id=:u and source_kind='EVIDENCE'"
            ),
            {"u": journey["user_id"]},
        ).one()
        assert row.source_key == f"{journey['evidence_id']}:ACTIVE"
        assert row.facts["transition_at"] is None


def test_bootstrap_reuses_live_overlap_and_refuses_unknown_state(
    isolated_migration_database,
):
    from app.learning.projection_operator import bootstrap
    from test_projection_publisher import drain

    db = isolated_migration_database
    owner = old_user(db)
    with db.engine.begin() as connection:
        onboard(connection, owner)
    assert drain(db) == 0  # REQUIRED blocks the pre-cutoff ordinary job.
    result = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert result["cutoff_source_sequence"] == 1
    assert result["ledger_reused"] == 1
    assert result["ledger_imported"] == 0
    assert result["baseline_through_sequence"] == 2
    assert drain(db) == 2  # Baseline publishes; covered ordinary job only acks.


def test_inconsistent_ready_metadata_refuses_without_rebaseline(
    isolated_migration_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    owner = old_user(db)
    applied = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "update projection_source_heads set cutoff_at=cutoff_at+interval '1 second' where user_id=:u"
            ),
            {"u": owner},
        )
    with pytest.raises(ProjectionError, match="READY_METADATA"):
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select source_sequence from projection_source_heads where user_id=:u"
                ),
                {"u": owner},
            )
            == applied["baseline_through_sequence"]
        )
        assert (
            connection.scalar(
                text("select count(*) from projection_inputs where user_id=:u"),
                {"u": owner},
            )
            == 1
        )


def test_bootstrap_refuses_unknown_legacy_projection_without_mutation(
    isolated_migration_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        _, objective = _insert_objective(connection)
        _insert_objective_state(
            connection,
            user_id=owner,
            objective_id=objective,
            understanding_estimate=0.375,
        )
    command.upgrade(config, "head")
    with pytest.raises(ProjectionError, match="UNKNOWN_PROVENANCE"):
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    with db.engine.connect() as connection:
        head = connection.execute(
            text(
                "select bootstrap_state,source_sequence from projection_source_heads where user_id=:u"
            ),
            {"u": owner},
        ).one()
        assert head == ("REQUIRED", 0)
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0


def test_source_waiting_on_bootstrap_head_gets_post_baseline_sequence(
    isolated_migration_database,
    monkeypatch,
):
    import app.learning.projection_operator as operator

    db = isolated_migration_database
    owner = old_user(db)
    locked, release, inserted = Event(), Event(), Event()
    original = operator._ledger_import

    async def pause_after_cutoff(session, user_id, cutoff):
        locked.set()
        assert await asyncio.to_thread(release.wait, 10)
        return await original(session, user_id, cutoff)

    monkeypatch.setattr(operator, "_ledger_import", pause_after_cutoff)

    def source():
        with db.engine.begin() as connection:
            connection.execute(text("set local role app_backend"))
            connection.execute(
                text("select set_config('app.user_id',:u,true)"),
                {"u": str(owner)},
            )
            event_id = onboard(connection, owner)
            inserted.set()
        return event_id

    with ThreadPoolExecutor(max_workers=2) as pool:
        bootstrap_future = pool.submit(
            lambda: operate(
                db, lambda factory: operator.bootstrap(factory, owner, apply=True)
            )
        )
        assert locked.wait(10)
        source_future = pool.submit(source)
        assert inserted.wait(10)
        assert not source_future.done()
        release.set()
        result = bootstrap_future.result(timeout=15)
        event_id = source_future.result(timeout=15)
    assert result["cutoff_source_sequence"] == 0
    assert result["baseline_through_sequence"] == 1
    with db.engine.connect() as connection:
        rows = connection.execute(
            text(
                "select source_sequence,source_kind,source_key from projection_inputs where user_id=:u order by source_sequence"
            ),
            {"u": owner},
        ).all()
        assert rows == [
            (1, "BOOTSTRAP", "learner-projection/v1:baseline"),
            (2, "LEDGER", str(event_id)),
        ]


def test_failed_historical_import_rolls_back_all_earlier_receipts(
    isolated_migration_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
        connection.execute(
            text("""insert into learning_events(user_id,event_type,occurred_at,schema_version,metadata)
values (:u,'EXPLORATION_STARTED',now()+interval '1 second',1,'{}'::jsonb)"""),
            {"u": owner},
        )
    command.upgrade(config, "head")
    with pytest.raises(ProjectionError, match="LEDGER_LINEAGE"):
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    with db.engine.connect() as connection:
        assert connection.execute(
            text(
                "select bootstrap_state,source_sequence from projection_source_heads where user_id=:u"
            ),
            {"u": owner},
        ).one() == ("REQUIRED", 0)
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0
        assert (
            connection.scalar(
                text("select count(*) from jobs where job_type='LEARNER_PROJECTION'")
            )
            == 0
        )


def test_fresh_user_bootstrap_is_noop_and_audit_is_read_only(
    isolated_migrated_database,
):
    from app.learning.projection_operator import audit, bootstrap

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        owner = user(connection)
    assert (
        operate(db, lambda factory: bootstrap(factory, owner, apply=True))["status"]
        == "FRESH_READY"
    )
    report = operate(db, lambda factory: audit(factory, owner))
    assert report["status"] == "PASS"
    assert report["horizon"] == 0
    with db.engine.connect() as connection:
        assert connection.scalar(text("select count(*) from projection_inputs")) == 0


def test_failed_job_requeue_dry_run_apply_and_audit(isolated_migrated_database):
    from app.learning.projection_operator import audit, requeue
    from app.learning.projection_worker import run_once
    from test_m6_reads import client_for, headers, subject_for

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
        connection.execute(
            text("update app_users set onboarding_completed_at=now() where id=:u"),
            {"u": owner},
        )
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        job = (
            connection.execute(
                text(
                    "select id,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            .mappings()
            .one()
        )
        group = job["payload"]["source_group"]
        connection.execute(
            text(
                "update jobs set status='FAILED',attempt_count=3,completed_at=clock_timestamp() where id=:id"
            ),
            {"id": job["id"]},
        )
        connection.execute(
            text(
                "update learner_projection_checkpoints set blocking_group=:g,failure_code='PROCESSING_FAILURE' where user_id=:u"
            ),
            {"g": group, "u": owner},
        )
    started = perf_counter()
    preview = operate(db, lambda factory: requeue(factory, owner, group))
    requeue_seconds = perf_counter() - started
    assert preview["status"] == "READY_TO_REQUEUE"
    print(
        "M6_REQUEUE_PERFORMANCE "
        + json.dumps(
            {"receipts": 1, "groups": 1, "dry_seconds": round(requeue_seconds, 6)},
            sort_keys=True,
        )
    )
    client, _ = client_for(db)
    with client:
        auth = headers(subject_for(db, owner))
        assert (
            client.get("/api/v1/memory/summary", headers=auth).json()["projection"][
                "status"
            ]
            == "FAILED"
        )
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text("select status from jobs where id=:id"), {"id": job["id"]}
            )
            == "FAILED"
        )
    applied = operate(db, lambda factory: requeue(factory, owner, group, apply=True))
    assert applied["status"] == "REQUEUED"
    assert applied["job_id"] == str(job["id"])
    client, _ = client_for(db)
    with client:
        assert (
            client.get("/api/v1/memory/summary", headers=auth).json()["projection"][
                "status"
            ]
            == "PENDING"
        )
    with db.engine.connect() as connection:
        row = connection.execute(
            text(
                "select status,attempt_count,payload,locked_at,locked_by,completed_at from jobs where id=:id"
            ),
            {"id": job["id"]},
        ).one()
        assert row.status == "PENDING" and row.attempt_count == 0
        assert row.payload == job["payload"]
        assert row.locked_at is row.locked_by is row.completed_at is None
    assert asyncio.run(worker(db, run_once)) is True
    assert operate(db, lambda factory: audit(factory, owner))["status"] == "PASS"
    client, _ = client_for(db)
    with client:
        assert (
            client.get("/api/v1/memory/summary", headers=auth).json()["projection"][
                "status"
            ]
            == "CURRENT"
        )
    from app.learning.projection_inputs import ProjectionError

    with pytest.raises(ProjectionError, match="NOT_BLOCKED_GROUP"):
        operate(db, lambda factory: requeue(factory, owner, group, apply=True))


def test_failed_baseline_job_can_requeue_without_new_job(
    isolated_migration_database,
):
    from app.learning.projection_operator import audit, bootstrap, requeue
    from app.learning.projection_worker import run_once

    db = isolated_migration_database
    owner = old_user(db)
    result = operate(db, lambda factory: bootstrap(factory, owner, apply=True))
    assert result["baseline_through_sequence"] == 1
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        job = (
            connection.execute(
                text(
                    "select id,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            .mappings()
            .one()
        )
        group = job["payload"]["source_group"]
        connection.execute(
            text(
                "update jobs set status='FAILED',attempt_count=3,completed_at=clock_timestamp() where id=:id"
            ),
            {"id": job["id"]},
        )
        connection.execute(
            text(
                "update learner_projection_checkpoints set blocking_group=:g,failure_code='PROCESSING_FAILURE' where user_id=:u"
            ),
            {"u": owner, "g": group},
        )
    assert operate(db, lambda factory: requeue(factory, owner, group, apply=True))[
        "job_id"
    ] == str(job["id"])
    assert asyncio.run(worker(db, run_once)) is True
    assert operate(db, lambda factory: audit(factory, owner))["status"] == "PASS"
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select count(*) from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            == 1
        )


def test_requeued_world_group_publishes_one_delta_stream(
    isolated_migrated_database,
):
    from app.learning.projection_operator import audit, requeue
    from test_projection_publisher import drain

    db = isolated_migrated_database
    journey = graph(db)
    owner = journey["user_id"]
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        job = (
            connection.execute(
                text(
                    "select id,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            .mappings()
            .one()
        )
        group = job["payload"]["source_group"]
        connection.execute(
            text(
                "update jobs set status='FAILED',attempt_count=3,completed_at=clock_timestamp() where id=:id"
            ),
            {"id": job["id"]},
        )
        connection.execute(
            text(
                "update learner_projection_checkpoints set blocking_group=:g,failure_code='PROCESSING_FAILURE' where user_id=:u"
            ),
            {"u": owner, "g": group},
        )
    assert (
        operate(db, lambda factory: requeue(factory, owner, group, apply=True))[
            "status"
        ]
        == "REQUEUED"
    )
    assert drain(db) == 1
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text("select count(*) from world_changes where user_id=:u"),
                {"u": owner},
            )
            == 2
        )
    assert operate(db, lambda factory: audit(factory, owner))["status"] == "PASS"


def test_corrupt_prefix_refuses_requeue_and_preserves_failed_state(
    isolated_migrated_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import requeue

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        job = (
            connection.execute(
                text(
                    "select id,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            .mappings()
            .one()
        )
        group = job["payload"]["source_group"]
        connection.execute(
            text(
                "update jobs set status='FAILED',completed_at=clock_timestamp() where id=:id"
            ),
            {"id": job["id"]},
        )
        connection.execute(
            text(
                "update learner_projection_checkpoints set blocking_group=:g,failure_code='INVALID_RECEIPT' where user_id=:u"
            ),
            {"u": owner, "g": group},
        )
    with db.engine.begin() as connection:
        connection.execute(
            text("alter table projection_inputs disable trigger trg_m6_input_immutable")
        )
        connection.execute(
            text(
                "update projection_inputs set facts=facts || jsonb_build_object('unexpected',true) where user_id=:u"
            ),
            {"u": owner},
        )
        connection.execute(
            text("alter table projection_inputs enable trigger trg_m6_input_immutable")
        )
    with pytest.raises(ProjectionError):
        operate(db, lambda factory: requeue(factory, owner, group, apply=True))
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text("select status from jobs where id=:id"), {"id": job["id"]}
            )
            == "FAILED"
        )
        assert (
            connection.scalar(
                text(
                    "select blocking_group from learner_projection_checkpoints where user_id=:u"
                ),
                {"u": owner},
            )
            == group
        )


def test_requeue_refuses_other_job_states_and_wrong_group(
    isolated_migrated_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import requeue

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
    with db.engine.connect() as connection:
        job = (
            connection.execute(
                text(
                    "select id,payload from jobs where user_id=:u and job_type='LEARNER_PROJECTION'"
                ),
                {"u": owner},
            )
            .mappings()
            .one()
        )
        group = job["payload"]["source_group"]
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        connection.execute(
            text(
                "update learner_projection_checkpoints set blocking_group=:g,failure_code='PROCESSING_FAILURE' where user_id=:u"
            ),
            {"u": owner, "g": group},
        )
    for status in ("PENDING", "RUNNING", "RETRYABLE_FAILURE", "SUCCEEDED"):
        with db.engine.begin() as connection:
            connection.execute(text("set local role app_worker"))
            connection.execute(
                text("update jobs set status=:status where id=:id"),
                {"id": job["id"], "status": status},
            )
        with pytest.raises(ProjectionError, match="NOT_FAILED_JOB"):
            operate(db, lambda factory: requeue(factory, owner, group, apply=True))
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        connection.execute(
            text("update jobs set status='FAILED' where id=:id"), {"id": job["id"]}
        )
    with pytest.raises(ProjectionError, match="NOT_BLOCKED_GROUP"):
        operate(db, lambda factory: requeue(factory, owner, "123456789", apply=True))


def test_audit_detects_checkpoint_corruption_without_repair(isolated_migrated_database):
    from app.learning.projection_operator import audit
    from app.learning.projection_worker import run_once

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        owner = user(connection)
        onboard(connection, owner)
    assert asyncio.run(worker(db, run_once)) is True
    with db.engine.begin() as connection:
        connection.execute(
            text(
                "update learner_projection_checkpoints set output_fingerprint=repeat('0',64) where user_id=:u"
            ),
            {"u": owner},
        )
    from app.learning.projection_inputs import ProjectionError

    with pytest.raises(ProjectionError, match="CHECKPOINT_FINGERPRINT"):
        operate(db, lambda factory: audit(factory, owner))
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text(
                    "select output_fingerprint from learner_projection_checkpoints where user_id=:u"
                ),
                {"u": owner},
            )
            == "0" * 64
        )


@pytest.mark.parametrize(
    "damage,category",
    [("seed", "UNKNOWN_WORLD"), ("delta_gap", "WORLD_HISTORY")],
)
def test_audit_detects_world_corruption_without_repair(
    isolated_migrated_database,
    damage,
    category,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import audit
    from test_projection_publisher import drain

    db = isolated_migrated_database
    journey = graph(db)
    assert drain(db) == 1
    assert (
        operate(db, lambda factory: audit(factory, journey["user_id"]))["status"]
        == "PASS"
    )
    with db.engine.begin() as connection:
        if damage == "seed":
            connection.execute(
                text(
                    "update learner_worlds set generation_seed=repeat('0',64) where user_id=:u"
                ),
                {"u": journey["user_id"]},
            )
        else:
            connection.execute(
                text("delete from world_changes where user_id=:u and revision=1"),
                {"u": journey["user_id"]},
            )
    with pytest.raises(ProjectionError, match=category):
        operate(db, lambda factory: audit(factory, journey["user_id"]))
    with db.engine.connect() as connection:
        if damage == "seed":
            assert (
                connection.scalar(
                    text("select generation_seed from learner_worlds where user_id=:u"),
                    {"u": journey["user_id"]},
                )
                == "0" * 64
            )
        else:
            assert (
                connection.scalar(
                    text("select count(*) from world_changes where user_id=:u"),
                    {"u": journey["user_id"]},
                )
                == 1
            )


def test_trusted_deletion_removes_published_m6_rows_and_preserves_other_owner(
    isolated_migrated_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import audit, requeue
    from app.learning.projection_worker import run_once

    db = isolated_migrated_database
    with db.engine.begin() as connection:
        deleted, survivor = user(connection), user(connection)
        onboard(connection, deleted)
        onboard(connection, survivor)
    assert asyncio.run(worker(db, run_once)) is True
    assert asyncio.run(worker(db, run_once)) is True
    with db.engine.begin() as connection:
        connection.execute(text("set local role app_worker"))
        connection.execute(
            text("select maintenance_delete_account(:u)"), {"u": deleted}
        )
    with db.engine.connect() as connection:
        for table in (
            "projection_source_heads",
            "projection_inputs",
            "learner_projection_checkpoints",
            "jobs",
            "learner_objective_state",
            "state_evidence_links",
            "learner_worlds",
            "world_regions",
            "world_nodes",
            "world_changes",
            "learning_events",
        ):
            assert (
                connection.scalar(
                    text(f"select count(*) from {table} where user_id=:u"),
                    {"u": deleted},
                )
                == 0
            )
        assert (
            connection.scalar(
                text("select count(*) from app_users where id=:u"), {"u": deleted}
            )
            == 0
        )
    assert operate(db, lambda factory: audit(factory, survivor))["status"] == "PASS"
    with pytest.raises(ProjectionError, match="OWNER_MISSING"):
        operate(db, lambda factory: audit(factory, deleted))
    with pytest.raises(ProjectionError, match="OWNER_MISSING"):
        operate(db, lambda factory: requeue(factory, deleted, "1"))


def test_deletion_winning_owner_lock_refuses_late_bootstrap(
    isolated_migration_database,
):
    from app.learning.projection_inputs import ProjectionError
    from app.learning.projection_operator import bootstrap

    db = isolated_migration_database
    deleted = old_user(db)
    with db.engine.begin() as connection:
        survivor = user(connection)
    with ThreadPoolExecutor(max_workers=1) as pool:
        with db.engine.begin() as connection:
            connection.execute(
                text("select id from app_users where id=:u for update"),
                {"u": deleted},
            )
            future = pool.submit(
                lambda: operate(
                    db, lambda factory: bootstrap(factory, deleted, apply=True)
                )
            )
            with pytest.raises(FutureTimeout):
                future.result(timeout=0.2)
            connection.execute(text("set local role app_worker"))
            connection.execute(
                text("select maintenance_delete_account(:u)"), {"u": deleted}
            )
        with pytest.raises(ProjectionError, match="OWNER_MISSING"):
            future.result(timeout=10)
    with db.engine.connect() as connection:
        assert (
            connection.scalar(
                text("select count(*) from projection_source_heads where user_id=:u"),
                {"u": deleted},
            )
            == 0
        )
        assert (
            connection.scalar(
                text("select count(*) from app_users where id=:u"), {"u": survivor}
            )
            == 1
        )


def test_deletion_waiting_for_bootstrap_removes_committed_baseline(
    isolated_migration_database,
    monkeypatch,
):
    import app.learning.projection_operator as operator

    db = isolated_migration_database
    owner = old_user(db)
    locked, release = Event(), Event()
    original = operator._ledger_import

    async def pause_after_head(session, user_id, cutoff):
        locked.set()
        assert await asyncio.to_thread(release.wait, 10)
        return await original(session, user_id, cutoff)

    monkeypatch.setattr(operator, "_ledger_import", pause_after_head)

    def delete():
        with db.engine.begin() as connection:
            connection.execute(text("set local role app_worker"))
            connection.execute(
                text("select maintenance_delete_account(:u)"), {"u": owner}
            )

    with ThreadPoolExecutor(max_workers=2) as pool:
        bootstrap_future = pool.submit(
            lambda: operate(
                db, lambda factory: operator.bootstrap(factory, owner, apply=True)
            )
        )
        assert locked.wait(10)
        delete_future = pool.submit(delete)
        with pytest.raises(FutureTimeout):
            delete_future.result(timeout=0.2)
        release.set()
        assert bootstrap_future.result(timeout=10)["status"] == "APPLIED"
        delete_future.result(timeout=10)
    with db.engine.connect() as connection:
        for table in (
            "app_users",
            "projection_source_heads",
            "projection_inputs",
            "learner_projection_checkpoints",
            "jobs",
        ):
            column = "id" if table == "app_users" else "user_id"
            assert (
                connection.scalar(
                    text(f"select count(*) from {table} where {column}=:u"),
                    {"u": owner},
                )
                == 0
            )


@pytest.mark.parametrize("returns", [0, 200])
def test_operator_performance_characterization(
    isolated_migration_database,
    returns,
):
    from app.learning.projection_operator import audit, bootstrap
    from test_projection_publisher import drain

    db = isolated_migration_database
    config = make_alembic_config(db.url)
    command.upgrade(config, "0019_response_lock_security")
    journey = graph(db, recognition=False)
    with db.engine.begin() as connection:
        exploration = connection.scalar(
            text("select id from explorations where user_id=:u"),
            {"u": journey["user_id"]},
        )
        for index in range(returns):
            connection.execute(
                text("""insert into learning_events(user_id,event_type,entity_id,
exploration_id,occurred_at,schema_version,metadata)
values (:u,'USER_RETURNED',:e,:x,now()+(:offset * interval '1 microsecond'),1,'{}'::jsonb)"""),
                {
                    "u": journey["user_id"],
                    "e": journey["entity_id"],
                    "x": exploration,
                    "offset": index,
                },
            )
    command.upgrade(config, "head")
    started = perf_counter()
    preview = operate(db, lambda factory: bootstrap(factory, journey["user_id"]))
    dry_seconds = perf_counter() - started
    started = perf_counter()
    applied = operate(
        db, lambda factory: bootstrap(factory, journey["user_id"], apply=True)
    )
    apply_seconds = perf_counter() - started
    assert preview["baseline_through_sequence"] == applied["baseline_through_sequence"]
    assert applied["ledger_imported"] == returns + 1
    assert drain(db) == 1
    started = perf_counter()
    report = operate(db, lambda factory: audit(factory, journey["user_id"]))
    audit_seconds = perf_counter() - started
    assert report["status"] == "PASS"
    with db.engine.connect() as connection:
        groups = connection.scalar(
            text(
                "select count(distinct source_group) from projection_inputs where user_id=:u"
            ),
            {"u": journey["user_id"]},
        )
    print(
        "M6_OPERATOR_PERFORMANCE "
        + json.dumps(
            {
                "receipts": applied["baseline_through_sequence"],
                "groups": groups,
                "bootstrap_dry_seconds": round(dry_seconds, 6),
                "bootstrap_apply_seconds": round(apply_seconds, 6),
                "audit_seconds": round(audit_seconds, 6),
            },
            sort_keys=True,
        )
    )
