from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError

ALEMBIC_INI = Path(__file__).resolve().parents[2] / "database" / "alembic.ini"

JSONB_COLUMNS = {
    "analysis",
    "content",
    "delivered_content",
    "environment_constraints",
    "evidence_requirements",
    "materials",
    "metadata",
    "physical_requirements",
    "presentation",
    "prompt_definition",
    "provenance",
    "response_content",
    "score_components",
    "source_metadata",
    "target_techniques",
}
TIMESTAMPTZ_COLUMNS = {
    "completed_at",
    "computed_at",
    "created_at",
    "decided_at",
    "expires_at",
    "first_placed_at",
    "last_evidence_at",
    "last_growth_at",
    "last_interaction_at",
    "last_revisit",
    "last_seen_at",
    "last_successful_recall",
    "occurred_at",
    "presented_at",
    "received_at",
    "rejected_at",
    "started_at",
    "submitted_at",
    "updated_at",
    "validated_at",
}

LEARNER_TABLES = (
    "user_devices",
    "idempotency_records",
    "jobs",
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    "explorations",
    "reflections",
    "assessment_sessions",
    "assessment_interactions",
    "assessment_responses",
    "assessment_support_requests",
    "evaluation_runs",
    "learning_evidence",
    "artifacts",
    "media_objects",
    "upload_sessions",
    "artifact_analyses",
    "learning_events",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "recommendations",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    "curiosity_stories",
    "account_operation_requests",
)

CANONICAL_TABLES = (
    "learning_entities",
    "learning_entity_versions",
    "learning_objectives",
    "ontology_edges",
    "entity_domains",
    "practical_challenges",
    "practical_challenge_versions",
)

MAINTENANCE_FUNCTION = "public.maintenance_delete_account(uuid)"
MAINTENANCE_ROLE = "app_maintenance"
WORKER_ROLE = "trusted_worker"
ORDINARY_ROLE = "ordinary_role"


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _insert(connection, table: str, *, returning: bool = True, **values) -> Any:
    columns = sorted(values)
    placeholders = []
    parameters = {}
    for column in columns:
        value = values[column]
        if column in JSONB_COLUMNS:
            parameters[column] = json.dumps(value)
            placeholders.append(f"cast(:{column} as jsonb)")
        elif column == "knowledge_types":
            parameters[column] = value
            placeholders.append(f"cast(:{column} as text[])")
        elif column in TIMESTAMPTZ_COLUMNS:
            parameters[column] = value
            placeholders.append(f"cast(:{column} as timestamptz)")
        else:
            parameters[column] = value
            placeholders.append(f":{column}")
    statement = (
        f"insert into {table} ({', '.join(columns)}) "
        f"values ({', '.join(placeholders)})"
    )
    if returning:
        statement += " returning id"
    result = connection.execute(text(statement), parameters)
    return result.scalar_one() if returning else None


def _count(connection, table: str, user_id) -> int:
    return connection.execute(
        text(f"select count(*) from {table} where user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()


def _insert_user(connection) -> str:
    return _insert(
        connection, "app_users", auth_provider="test", auth_subject=uuid4().hex
    )


def _alembic_config(url: str) -> Config:
    config = Config(str(ALEMBIC_INI))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def _assert_constraint(connection, expected: str, statement, parameters=None) -> None:
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(text(statement), parameters or {})
    assert error.value.orig.diag.constraint_name == expected


def _as_role(connection, role: str) -> None:
    connection.execute(text(f"set role {role}"))


def _reset_role(connection) -> None:
    connection.execute(text("reset role"))


def _seed_canonical(connection) -> dict:
    domain = _insert(
        connection,
        "learning_entities",
        canonical_key=f"domain.{uuid4().hex}",
        entity_type="DOMAIN",
        status="REVIEWED",
    )
    topic = _insert(
        connection,
        "learning_entities",
        canonical_key=f"topic.{uuid4().hex}",
        entity_type="TOPIC",
        status="REVIEWED",
    )
    _insert(
        connection,
        "learning_entity_versions",
        entity_id=domain,
        version=1,
        title="Mathematics",
        summary="A canonical domain",
        knowledge_types="{FACTUAL}",
        scope="GLOBAL",
    )
    _insert(
        connection,
        "learning_entity_versions",
        entity_id=topic,
        version=1,
        title="Algebra",
        summary="A canonical topic",
        knowledge_types="{CONCEPTUAL}",
        scope="GLOBAL",
    )
    connection.execute(
        text("update learning_entities set current_version = 1 where id in (:a, :b)"),
        {"a": domain, "b": topic},
    )
    objective = _insert(
        connection,
        "learning_objectives",
        entity_id=topic,
        entity_version=1,
        objective_type="CONCEPTUAL",
        description="Explain variables",
        importance=0.5,
    )
    _insert(
        connection,
        "ontology_edges",
        source_entity_id=topic,
        target_entity_id=domain,
        relationship_type="BUILDS_ON",
        confidence=0.5,
        status="REVIEWED",
    )
    _insert(
        connection,
        "entity_domains",
        entity_id=topic,
        domain_id=domain,
        is_primary=True,
        membership_strength=0.8,
        returning=False,
    )
    challenge = _insert(connection, "practical_challenges", entity_id=topic)
    version = _insert(
        connection,
        "practical_challenge_versions",
        challenge_id=challenge,
        entity_id=topic,
        entity_version=1,
        version=1,
        prompt="Solve one linear equation",
        target_techniques=[],
        estimated_effort_minutes=20,
        materials=[],
        environment_constraints=[],
        physical_requirements=[],
        evidence_requirements=[],
        status="PUBLISHED",
    )
    return {
        "domain": domain,
        "topic": topic,
        "objective": objective,
        "challenge": challenge,
        "challenge_version": version,
    }


def _seed_preferences(connection, user_id, *, with_onboarding: bool) -> None:
    _insert(
        connection,
        "learner_preferences",
        user_id=user_id,
        adventure_preference="BALANCED",
        preferred_effort="15_20_MIN",
        support_style="SMALL_HINT",
        practical_opt_in=with_onboarding,
        returning=False,
    )
    if with_onboarding:
        _insert(
            connection,
            "user_motivations",
            user_id=user_id,
            motivation_code="LEARN_DAILY",
            returning=False,
        )


def _seed_learner(connection, canonical: dict) -> str:
    user_id = _insert_user(connection)
    _seed_preferences(connection, user_id, with_onboarding=True)
    _insert(
        connection,
        "explicit_interest_preferences",
        user_id=user_id,
        entity_id=canonical["domain"],
        preference="MORE",
        returning=False,
    )
    device = _insert(
        connection,
        "user_devices",
        id=str(uuid4()),
        user_id=user_id,
        platform="ANDROID",
    )
    command = _insert(
        connection,
        "idempotency_records",
        user_id=user_id,
        idempotency_key=uuid4().hex,
        command_name="START_EXPLORATION",
        request_fingerprint=uuid4().hex,
        expires_at="2026-10-01T00:00:00+00:00",
    )
    _insert(connection, "jobs", user_id=user_id, job_type="DELETION", status="PENDING")
    recommendation = _insert(
        connection,
        "recommendations",
        user_id=user_id,
        entity_id=canonical["topic"],
        entity_version=1,
        mode="CONTINUE",
        distance_band="COMFORT",
        ranking_model_version="v1",
        score_components={},
        reason_code="NEXT_STEP",
        presentation_version="v1",
        presentation={},
        presented_at="2026-09-01T00:00:00+00:00",
    )
    exploration = _insert(
        connection,
        "explorations",
        user_id=user_id,
        entity_id=canonical["topic"],
        entity_version=1,
        recommendation_id=recommendation,
        practical_challenge_id=canonical["challenge"],
        practical_challenge_version_id=canonical["challenge_version"],
        learning_intent="DIRECT_INTEREST",
        status="ACTIVE",
        started_at="2026-09-01T00:00:00+00:00",
    )
    reflection = _insert(
        connection,
        "reflections",
        user_id=user_id,
        exploration_id=exploration,
        entity_id=canonical["topic"],
        text="I learned variables",
    )
    session = _insert(
        connection,
        "assessment_sessions",
        user_id=user_id,
        exploration_id=exploration,
        entity_version=1,
        strategy_version="v1",
        confidence_before="FUZZY",
        status="ACTIVE",
        started_at="2026-09-01T00:01:00+00:00",
    )
    interaction = _insert(
        connection,
        "assessment_interactions",
        user_id=user_id,
        assessment_session_id=session,
        objective_id=canonical["objective"],
        interaction_type="OPEN_RESPONSE",
        prompt_definition={},
        rubric_version="v1",
        sequence=1,
    )
    response = _insert(
        connection,
        "assessment_responses",
        user_id=user_id,
        assessment_session_id=session,
        interaction_id=interaction,
        response_type="TEXT",
        response_content={"text": "x = value"},
    )
    _insert(
        connection,
        "assessment_support_requests",
        user_id=user_id,
        assessment_session_id=session,
        interaction_id=interaction,
        requested_level="SMALL_NUDGE",
        delivered_content={},
        support_source="SYSTEM",
    )
    evaluation = _insert(
        connection,
        "evaluation_runs",
        user_id=user_id,
        response_id=response,
        evaluator_type="RUBRIC",
        evaluator_version="v1",
        rubric_version="v1",
        status="SUCCEEDED",
        result="SUPPORTED",
        confidence=0.8,
        feedback="ok",
    )
    evidence = _insert(
        connection,
        "learning_evidence",
        user_id=user_id,
        entity_id=canonical["topic"],
        objective_id=canonical["objective"],
        source_type="ASSESSMENT_RESPONSE",
        source_id=response,
        evaluation_run_id=evaluation,
        evidence_type="RECALL",
        evidence_strength="MODERATE",
        status="ACTIVE",
        evaluation_confidence=0.8,
    )
    object_key = f"private/{uuid4().hex}"
    upload = _insert(
        connection,
        "upload_sessions",
        user_id=user_id,
        purpose="ARTIFACT",
        declared_content_type="image/png",
        declared_size_bytes=100,
        object_key=object_key,
        status="VALIDATED",
        created_at="2026-09-01T00:00:00+00:00",
        completed_at="2026-09-01T00:01:00+00:00",
        validated_at="2026-09-01T00:02:00+00:00",
    )
    media = _insert(
        connection,
        "media_objects",
        user_id=user_id,
        upload_id=upload,
        object_key=object_key,
        validated_content_type="image/png",
        validated_size_bytes=100,
        sha256="a" * 64,
        metadata_stripped=True,
    )
    artifact = _insert(
        connection,
        "artifacts",
        user_id=user_id,
        practical_challenge_id=canonical["challenge"],
        practical_challenge_version_id=canonical["challenge_version"],
        exploration_id=exploration,
        media_object_id=media,
        reflection_id=reflection,
    )
    _insert(
        connection,
        "artifact_analyses",
        user_id=user_id,
        artifact_id=artifact,
        analyzer_version="v1",
        status="SUCCEEDED",
        analysis={},
    )
    event = _insert(
        connection,
        "learning_events",
        user_id=user_id,
        device_id=device,
        command_id=command,
        event_ordinal=0,
        event_type="EXPLORATION_STARTED",
        entity_id=canonical["topic"],
        exploration_id=exploration,
        assessment_session_id=session,
        artifact_id=artifact,
        learning_intent="DIRECT_INTEREST",
        occurred_at="2026-09-01T00:03:00+00:00",
        schema_version=1,
    )
    _insert(
        connection,
        "learner_interest_state",
        user_id=user_id,
        entity_id=canonical["topic"],
        recent_affinity=0.5,
        long_term_affinity=0.5,
        user_initiated_strength=0.5,
        algorithm_exposure_strength=0.5,
        model_version="v1",
    )
    _insert(
        connection,
        "learner_confidence_state",
        user_id=user_id,
        entity_id=canonical["topic"],
        model_version="v1",
    )
    _insert(
        connection,
        "learner_retention_state",
        user_id=user_id,
        entity_id=canonical["topic"],
        retention_estimate=0.5,
        model_version="v1",
    )
    _insert(
        connection,
        "learner_objective_state",
        user_id=user_id,
        objective_id=canonical["objective"],
        understanding_estimate=0.5,
        model_version="v1",
    )
    _insert(
        connection,
        "learner_challenge_state",
        user_id=user_id,
        area_id=canonical["domain"],
        ability_estimate=0.5,
        model_version="v1",
    )
    _insert(
        connection,
        "state_evidence_links",
        user_id=user_id,
        state_dimension="UNDERSTANDING",
        target_id=canonical["objective"],
        learning_evidence_id=evidence,
    )
    _insert(
        connection,
        "state_evidence_links",
        user_id=user_id,
        state_dimension="ENGAGEMENT",
        target_id=canonical["topic"],
        learning_event_id=event,
    )
    _insert(
        connection,
        "curiosity_stories",
        user_id=user_id,
        story_type="WEEKLY",
        covered_from=date(2026, 9, 1),
        covered_to=date(2026, 9, 7),
        content={},
        generator_version="v1",
    )
    world = _insert(
        connection,
        "learner_worlds",
        user_id=user_id,
        generation_seed="seed",
        layout_version=1,
    )
    region = _insert(
        connection,
        "world_regions",
        user_id=user_id,
        world_id=world,
        region_key="region-1",
        primary_domain_id=canonical["domain"],
        logical_x=0.0,
        logical_y=0.0,
        logical_width=10.0,
        logical_height=10.0,
        visual_archetype="GROVE",
    )
    node_a = _insert(
        connection,
        "world_nodes",
        user_id=user_id,
        world_id=world,
        entity_id=canonical["topic"],
        region_id=region,
        logical_x=1.0,
        logical_y=1.0,
        depth=0,
        visual_archetype="NODE",
        visual_seed="seed-a",
        growth_state="SEED",
        revision=1,
    )
    node_b = _insert(
        connection,
        "world_nodes",
        user_id=user_id,
        world_id=world,
        entity_id=canonical["domain"],
        region_id=region,
        logical_x=2.0,
        logical_y=2.0,
        depth=0,
        visual_archetype="NODE",
        visual_seed="seed-b",
        growth_state="SEED",
        revision=1,
    )
    _insert(
        connection,
        "world_connections",
        user_id=user_id,
        world_id=world,
        source_world_node_id=node_a,
        target_world_node_id=node_b,
        connection_type="RELATED",
        importance=0.5,
        is_visible=True,
        revision=1,
    )
    _insert(
        connection,
        "world_artifacts",
        user_id=user_id,
        world_id=world,
        artifact_id=artifact,
        region_id=region,
        logical_x=3.0,
        logical_y=3.0,
        depth=0,
        visual_archetype="ARTIFACT",
        visual_seed="seed-c",
        revision=1,
    )
    _insert(
        connection,
        "world_changes",
        user_id=user_id,
        world_id=world,
        revision=1,
        change_type="ADD_NODE",
        object_type="NODE",
        object_id=node_a,
    )
    _insert(
        connection,
        "account_operation_requests",
        user_id=user_id,
        idempotency_record_id=command,
        operation_type="DELETE",
        status="PENDING",
    )
    return user_id


def _seed_other_user(connection, canonical: dict) -> str:
    user_id = _insert_user(connection)
    _seed_preferences(connection, user_id, with_onboarding=False)
    _insert(
        connection,
        "explorations",
        user_id=user_id,
        entity_id=canonical["topic"],
        entity_version=1,
        learning_intent="DIRECT_INTEREST",
        status="ACTIVE",
        started_at="2026-09-02T00:00:00+00:00",
    )
    return user_id


def _seed_learner_with_other(connection):
    canonical = _seed_canonical(connection)
    user_a = _seed_learner(connection, canonical)
    user_b = _seed_other_user(connection, canonical)
    return canonical, user_a, user_b


def _ensure_role(connection, role: str, *, bypassrls: bool = False) -> None:
    exists = connection.execute(
        text("select 1 from pg_roles where rolname = :role"), {"role": role}
    ).scalar_one_or_none()
    if exists is not None:
        return
    attributes = "nologin bypassrls" if bypassrls else "nologin"
    connection.execute(text(f"create role {role} {attributes}"))


def _setup_maintenance_roles(connection) -> None:
    # app_maintenance is externally provisioned (NOLOGIN + BYPASSRLS) by the
    # test harness before migration 0012 runs; the other roles stay scoped to
    # this test transaction.
    _ensure_role(connection, MAINTENANCE_ROLE, bypassrls=True)
    _ensure_role(connection, WORKER_ROLE)
    _ensure_role(connection, ORDINARY_ROLE)
    connection.execute(
        text(
            f"grant usage on schema public to "
            f"{MAINTENANCE_ROLE}, {WORKER_ROLE}, {ORDINARY_ROLE}"
        )
    )
    connection.execute(
        text(
            f"grant select, insert, update, delete on all tables in schema public "
            f"to {MAINTENANCE_ROLE}"
        )
    )
    connection.execute(
        text(
            f"alter function {MAINTENANCE_FUNCTION} owner to {MAINTENANCE_ROLE};"
            f"grant execute on function {MAINTENANCE_FUNCTION} to {WORKER_ROLE}"
        )
    )


def _call_maintenance(connection, user_id) -> None:
    connection.execute(
        text("select public.maintenance_delete_account(:user_id)"),
        {"user_id": user_id},
    )


def _function_row(connection):
    return connection.execute(
        text(
            """
            select pg_get_userbyid(p.proowner) as owner,
                   p.prosecdef as security_definer,
                   l.lanname as language,
                   p.proconfig as config,
                   exists (
                       select 1
                       from aclexplode(
                           coalesce(p.proacl, acldefault('f', p.proowner))
                       ) as acl
                       where acl.grantee = 0
                         and acl.privilege_type = 'EXECUTE'
                   ) as public_can_execute
            from pg_proc p
            join pg_namespace n on n.oid = p.pronamespace
            join pg_language l on l.oid = p.prolang
            where n.nspname = 'public'
              and p.proname = 'maintenance_delete_account'
            """
        )
    ).one_or_none()


# ---------------------------------------------------------------------------
# migration security properties
# ---------------------------------------------------------------------------


def test_maintenance_function_exists_and_is_hardened(migrated_connection):
    row = _function_row(migrated_connection)

    assert row is not None, "maintenance_delete_account must exist after 0011a"
    assert row.security_definer is True
    assert row.language == "plpgsql"
    assert any(str(item).startswith("search_path=") for item in (row.config or []))
    assert row.owner == MAINTENANCE_ROLE, "0012 transfers ownership to app_maintenance"
    assert row.public_can_execute is False, "PUBLIC must not hold EXECUTE"


def test_runtime_roles_are_externally_provisioned(migrated_connection):
    rows = dict(
        migrated_connection.execute(
            text(
                "select rolname, rolbypassrls from pg_roles where rolname in "
                "('app_maintenance', 'app_worker', 'app_backend')"
            )
        ).all()
    )

    assert rows == {
        "app_backend": False,
        "app_worker": True,
        "app_maintenance": True,
    }, "0012 verifies externally provisioned runtime roles; it does not create them"


def test_ordinary_role_cannot_execute_maintenance_function(migrated_connection):
    _setup_maintenance_roles(migrated_connection)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        _as_role(migrated_connection, ORDINARY_ROLE)
        _call_maintenance(migrated_connection, uuid4())

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


# ---------------------------------------------------------------------------
# immutability guards
# ---------------------------------------------------------------------------


def test_maintenance_delete_of_learning_events_is_allowed(migrated_connection):
    canonical, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, MAINTENANCE_ROLE)
    # state_evidence_links holds a NO ACTION reference to learning_events,
    # so it must be removed first; the guard exception under test is the
    # learning_events DELETE itself.
    migrated_connection.execute(
        text("delete from state_evidence_links where user_id = :user_id"),
        {"user_id": user_a},
    )
    deleted = migrated_connection.execute(
        text("delete from learning_events where user_id = :user_id"),
        {"user_id": user_a},
    ).rowcount
    _reset_role(migrated_connection)

    assert deleted == 1


def test_maintenance_update_of_learning_events_is_rejected(migrated_connection):
    _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        _as_role(migrated_connection, MAINTENANCE_ROLE)
        migrated_connection.execute(
            text("update learning_events set schema_version = 2")
        )

    assert error.value.orig.sqlstate == "55000"
    assert (
        error.value.orig.diag.constraint_name == "ck_learning_events_immutable"
    )
    _reset_role(migrated_connection)


def test_ordinary_role_cannot_delete_immutable_history(migrated_connection):
    _, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)
    migrated_connection.execute(
        text(
            f"grant select, delete on learning_events, learning_evidence, "
            f"evaluation_runs, assessment_responses, artifacts to {ORDINARY_ROLE}"
        )
    )

    # After 0012 the ordinary role has neither a policy nor a bypass, so RLS
    # hides every row before the immutability trigger can fire. The invariant
    # holds through row-level security; the trigger layer is covered by the
    # grantee-with-bypass case in test_rls.py.
    for table in (
        "learning_events",
        "learning_evidence",
        "evaluation_runs",
        "assessment_responses",
        "artifacts",
    ):
        _as_role(migrated_connection, ORDINARY_ROLE)
        deleted = migrated_connection.execute(
            text(f"delete from {table} where user_id = :user_id"),
            {"user_id": user_a},
        ).rowcount
        _reset_role(migrated_connection)
        assert deleted == 0, table
        assert _count(migrated_connection, table, user_a) == 1, table


def test_trusted_worker_has_no_direct_delete_privileges(migrated_connection):
    _, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        _as_role(migrated_connection, WORKER_ROLE)
        migrated_connection.execute(
            text("delete from learning_events where user_id = :user_id"),
            {"user_id": user_a},
        )

    assert error.value.orig.sqlstate == "42501"
    _reset_role(migrated_connection)


# ---------------------------------------------------------------------------
# whole-account deletion
# ---------------------------------------------------------------------------


def test_trusted_maintenance_deletes_entire_account(migrated_connection):
    canonical, user_a, user_b = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, WORKER_ROLE)
    _call_maintenance(migrated_connection, user_a)
    _reset_role(migrated_connection)

    remaining_users = migrated_connection.execute(
        text("select count(*) from app_users where id = :user_id"),
        {"user_id": user_a},
    ).scalar_one()
    assert remaining_users == 0

    for table in LEARNER_TABLES:
        assert _count(migrated_connection, table, user_a) == 0, table

    assert (
        migrated_connection.execute(
            text("select count(*) from app_users where id = :user_id"),
            {"user_id": user_b},
        ).scalar_one()
        == 1
    )
    assert _count(migrated_connection, "learner_preferences", user_b) == 1
    assert _count(migrated_connection, "explorations", user_b) == 1

    for table in CANONICAL_TABLES:
        assert (
            migrated_connection.execute(
                text(f"select count(*) from {table}")
            ).scalar_one()
            > 0
        ), table
    canonical_queries = {
        "domain": ("learning_entities", canonical["domain"]),
        "topic": ("learning_entities", canonical["topic"]),
        "objective": ("learning_objectives", canonical["objective"]),
        "challenge": ("practical_challenges", canonical["challenge"]),
        "challenge_version": (
            "practical_challenge_versions",
            canonical["challenge_version"],
        ),
    }
    for key, (table, identifier) in canonical_queries.items():
        exists = migrated_connection.execute(
            text(f"select 1 from {table} where id = :id"),
            {"id": identifier},
        ).first()
        assert exists is not None, key


def test_unknown_user_is_noop_and_null_raises(migrated_connection):
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, WORKER_ROLE)
    _call_maintenance(migrated_connection, uuid4())
    _reset_role(migrated_connection)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        _as_role(migrated_connection, WORKER_ROLE)
        _call_maintenance(migrated_connection, None)

    assert error.value.orig.sqlstate == "22004"
    _reset_role(migrated_connection)


def test_deletion_is_idempotent(migrated_connection):
    _, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, WORKER_ROLE)
    _call_maintenance(migrated_connection, user_a)
    _call_maintenance(migrated_connection, user_a)
    _reset_role(migrated_connection)


def test_deletion_is_target_isolated(migrated_connection):
    _, user_a, user_b = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, WORKER_ROLE)
    _call_maintenance(migrated_connection, user_b)
    _reset_role(migrated_connection)

    assert _count(migrated_connection, "learner_preferences", user_a) == 1
    assert (
        migrated_connection.execute(
            text("select count(*) from app_users where id = :user_id"),
            {"user_id": user_a},
        ).scalar_one()
        == 1
    )
    assert (
        migrated_connection.execute(
            text("select count(*) from app_users where id = :user_id"),
            {"user_id": user_b},
        ).scalar_one()
        == 0
    )


def test_operation_and_idempotency_rows_are_removed(migrated_connection):
    _, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)

    _as_role(migrated_connection, WORKER_ROLE)
    _call_maintenance(migrated_connection, user_a)
    _reset_role(migrated_connection)

    assert _count(migrated_connection, "account_operation_requests", user_a) == 0
    assert _count(migrated_connection, "idempotency_records", user_a) == 0


def test_late_failure_rolls_back_the_whole_deletion(migrated_connection):
    _, user_a, _ = _seed_learner_with_other(migrated_connection)
    _setup_maintenance_roles(migrated_connection)
    migrated_connection.execute(
        text(
            """
            create table _test_delete_blocker (
                id uuid primary key default gen_random_uuid(),
                user_id uuid not null references app_users(id)
            )
            """
        )
    )
    migrated_connection.execute(
        text("insert into _test_delete_blocker (user_id) values (:user_id)"),
        {"user_id": user_a},
    )

    with pytest.raises(IntegrityError) as error, migrated_connection.begin_nested():
        _as_role(migrated_connection, WORKER_ROLE)
        _call_maintenance(migrated_connection, user_a)

    assert error.value.orig.sqlstate == "23503"
    _reset_role(migrated_connection)

    assert (
        migrated_connection.execute(
            text("select count(*) from app_users where id = :user_id"),
            {"user_id": user_a},
        ).scalar_one()
        == 1
    )
    for table in (
        "learning_events",
        "learning_evidence",
        "artifacts",
        "assessment_responses",
        "explorations",
    ):
        assert _count(migrated_connection, table, user_a) == 1, table


# ---------------------------------------------------------------------------
# downgrade / re-upgrade
# ---------------------------------------------------------------------------


def test_downgrade_restores_previous_trigger_and_removes_function(database_url):
    config = _alembic_config(database_url)
    engine = create_engine(database_url)
    try:
        command.upgrade(config, "head")
        command.downgrade(config, "0011_stories_and_exports")
        with engine.connect() as connection:
            assert _function_row(connection) is None
            assert connection.execute(
                text("select version_num from alembic_version")
            ).scalar_one() == "0011_stories_and_exports"

            canonical = _seed_canonical(connection)
            user = _insert_user(connection)
            _insert(
                connection,
                "learning_events",
                user_id=user,
                event_type="EXPLORATION_STARTED",
                occurred_at="2026-09-01T00:00:00+00:00",
                schema_version=1,
            )
            _ensure_role(connection, MAINTENANCE_ROLE, bypassrls=True)
            connection.execute(
                text(
                    f"grant select, delete on learning_events to {MAINTENANCE_ROLE}"
                )
            )
            with pytest.raises(DBAPIError) as error, connection.begin_nested():
                connection.execute(text(f"set role {MAINTENANCE_ROLE}"))
                connection.execute(
                    text("delete from learning_events where user_id = :user_id"),
                    {"user_id": user},
                )
            assert error.value.orig.sqlstate == "55000"
            assert (
                error.value.orig.diag.constraint_name
                == "ck_learning_events_immutable"
            )
            connection.execute(text("reset role"))
            connection.rollback()
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    with create_engine(database_url).connect() as connection:
        assert _function_row(connection) is not None
        assert connection.execute(
            text("select version_num from alembic_version")
        ).scalar_one() == "0015_recommendation_retrieval"
