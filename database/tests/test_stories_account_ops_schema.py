from __future__ import annotations

import json
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


def _assert_constraint(connection, expected: str, statement, parameters) -> None:
    with pytest.raises(IntegrityError) as error, connection.begin_nested():
        connection.execute(statement, parameters)

    assert error.value.orig.diag.constraint_name == expected


def _insert_user(connection):
    return connection.execute(
        text(
            """
            insert into app_users (auth_provider, auth_subject)
            values ('test', :subject)
            returning id
            """
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_idempotency_record(
    connection,
    *,
    user_id,
    idempotency_key: str | None = None,
    command_name: str = "START_ACCOUNT_OPERATION",
):
    return connection.execute(
        text(
            """
            insert into idempotency_records
              (user_id, idempotency_key, command_name, request_fingerprint,
               expires_at)
            values (:user_id, :idempotency_key, :command_name, :fingerprint,
                    now() + interval '1 day')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "idempotency_key": idempotency_key or uuid4().hex,
            "command_name": command_name,
            "fingerprint": uuid4().hex,
        },
    ).scalar_one()


def _insert_story(
    connection,
    *,
    user_id,
    story_type: str = "WEEKLY",
    covered_from: date = date(2026, 9, 1),
    covered_to: date = date(2026, 9, 7),
    content=None,
    generator_version: str = "v1",
):
    return connection.execute(
        text(
            """
            insert into curiosity_stories
              (user_id, story_type, covered_from, covered_to, content,
               generator_version)
            values (:user_id, :story_type, :covered_from, :covered_to,
                    cast(:content as jsonb), :generator_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "story_type": story_type,
            "covered_from": covered_from,
            "covered_to": covered_to,
            "content": json.dumps(content or {"scenes": []}),
            "generator_version": generator_version,
        },
    ).scalar_one()


def _insert_operation(
    connection,
    *,
    user_id,
    idempotency_record_id,
    operation_type: str = "EXPORT",
    status: str = "PENDING",
    result_object_key=None,
    error_code=None,
    created_at=None,
    started_at=None,
    completed_at=None,
):
    return connection.execute(
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               result_object_key, error_code, created_at, started_at,
               completed_at)
            values
              (:user_id, :idempotency_record_id, :operation_type, :status,
               :result_object_key, :error_code,
               coalesce(cast(:created_at as timestamptz), now()),
               cast(:started_at as timestamptz),
               cast(:completed_at as timestamptz))
            returning id
            """
        ),
        {
            "user_id": user_id,
            "idempotency_record_id": idempotency_record_id,
            "operation_type": operation_type,
            "status": status,
            "result_object_key": result_object_key,
            "error_code": error_code,
            "created_at": created_at,
            "started_at": started_at,
            "completed_at": completed_at,
        },
    ).scalar_one()


def _deletion_in_progress(connection, *, user_id) -> bool:
    return connection.execute(
        text(
            """
            select exists(
                select 1
                  from account_operation_requests
                 where user_id = :user_id
                   and operation_type = 'DELETE'
                   and status in ('PENDING', 'RUNNING')
            )
            """
        ),
        {"user_id": user_id},
    ).scalar_one()


# --------------------------------------------------------------------------
# Curiosity stories
# --------------------------------------------------------------------------


def test_story_can_be_created(migrated_connection):
    user_id = _insert_user(migrated_connection)

    story_id = _insert_story(
        migrated_connection,
        user_id=user_id,
        content={"scenes": [{"kind": "intro", "text": "You kept returning."}]},
    )

    row = migrated_connection.execute(
        text(
            "select story_type, covered_from, covered_to, generator_version, "
            "content from curiosity_stories where id = :id"
        ),
        {"id": story_id},
    ).one()
    assert row.story_type == "WEEKLY"
    assert row.covered_from == date(2026, 9, 1)
    assert row.covered_to == date(2026, 9, 7)
    assert row.generator_version == "v1"
    assert row.content == {"scenes": [{"kind": "intro", "text": "You kept returning."}]}


def test_story_type_vocabulary_is_not_constrained(migrated_connection):
    user_id = _insert_user(migrated_connection)

    story_id = _insert_story(
        migrated_connection, user_id=user_id, story_type="MONTHLY_RETROSPECTIVE"
    )

    stored = migrated_connection.execute(
        text("select story_type from curiosity_stories where id = :id"),
        {"id": story_id},
    ).scalar_one()
    assert stored == "MONTHLY_RETROSPECTIVE"


def test_story_requires_valid_covered_window(migrated_connection):
    user_id = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_curiosity_stories_window",
        text(
            """
            insert into curiosity_stories
              (user_id, story_type, covered_from, covered_to, content,
               generator_version)
            values (:user_id, 'WEEKLY', '2026-09-07', '2026-09-01',
                    '{}'::jsonb, 'v1')
            """
        ),
        {"user_id": user_id},
    )


def test_story_generation_window_is_unique_per_generator(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _insert_story(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "uq_curiosity_stories_generation_window",
        text(
            """
            insert into curiosity_stories
              (user_id, story_type, covered_from, covered_to, content,
               generator_version)
            values (:user_id, 'WEEKLY', '2026-09-01', '2026-09-07',
                    '{"scenes": []}'::jsonb, 'v1')
            """
        ),
        {"user_id": user_id},
    )


def test_story_regeneration_with_new_generator_version_coexists(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _insert_story(migrated_connection, user_id=user_id, generator_version="v1")

    regenerated_id = _insert_story(
        migrated_connection, user_id=user_id, generator_version="v2"
    )

    count = migrated_connection.execute(
        text("select count(*) from curiosity_stories where user_id = :user_id"),
        {"user_id": user_id},
    ).scalar_one()
    assert count == 2
    stored = migrated_connection.execute(
        text("select generator_version from curiosity_stories where id = :id"),
        {"id": regenerated_id},
    ).scalar_one()
    assert stored == "v2"


def test_story_requires_content(migrated_connection):
    user_id = _insert_user(migrated_connection)

    with pytest.raises(IntegrityError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                insert into curiosity_stories
                  (user_id, story_type, covered_from, covered_to, content,
                   generator_version)
                values (:user_id, 'WEEKLY', '2026-09-01', '2026-09-07', null,
                        'v1')
                """
            ),
            {"user_id": user_id},
        )

    assert error.value.orig.sqlstate == "23502"


# --------------------------------------------------------------------------
# Account operation requests
# --------------------------------------------------------------------------


def test_account_operation_can_be_created(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    operation_id = _insert_operation(
        migrated_connection,
        user_id=user_id,
        idempotency_record_id=record_id,
        operation_type="EXPORT",
        status="PENDING",
    )

    row = migrated_connection.execute(
        text(
            "select operation_type, status, started_at, completed_at, "
            "error_code from account_operation_requests where id = :id"
        ),
        {"id": operation_id},
    ).one()
    assert row.operation_type == "EXPORT"
    assert row.status == "PENDING"
    assert row.started_at is None
    assert row.completed_at is None
    assert row.error_code is None


def test_account_operation_type_vocabulary(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_operation_type",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status)
            values (:user_id, :record_id, 'ARCHIVE', 'PENDING')
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_status_vocabulary(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_status",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status)
            values (:user_id, :record_id, 'EXPORT', 'QUEUED')
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_is_unique_per_idempotency_command(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)
    _insert_operation(
        migrated_connection, user_id=user_id, idempotency_record_id=record_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_account_operation_requests_idempotency_record_id",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status)
            values (:user_id, :record_id, 'DELETE', 'PENDING')
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_rejects_cross_user_idempotency_record(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_id = _insert_user(migrated_connection)
    other_record_id = _insert_idempotency_record(
        migrated_connection, user_id=other_id
    )

    _assert_constraint(
        migrated_connection,
        "fk_account_operation_requests_idempotency_owner",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status)
            values (:user_id, :record_id, 'EXPORT', 'PENDING')
            """
        ),
        {"user_id": owner_id, "record_id": other_record_id},
    )


def test_account_operation_rejects_public_result_url(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_private_result_object_key",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               result_object_key, created_at, started_at, completed_at)
            values (:user_id, :record_id, 'EXPORT', 'SUCCEEDED',
                    'https://storage.example.invalid/export.zip?token=abc',
                    now(), now(), now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_accepts_private_result_object_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    operation_id = _insert_operation(
        migrated_connection,
        user_id=user_id,
        idempotency_record_id=record_id,
        operation_type="EXPORT",
        status="SUCCEEDED",
        result_object_key=f"users/{user_id}/exports/archive.zip",
        started_at=datetime.now(timezone.utc),
        completed_at=datetime.now(timezone.utc),
    )

    stored = migrated_connection.execute(
        text(
            "select result_object_key from account_operation_requests "
            "where id = :id"
        ),
        {"id": operation_id},
    ).scalar_one()
    assert stored == f"users/{user_id}/exports/archive.zip"


def test_account_operation_rejects_blank_error_code(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_error_code",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               error_code, created_at, started_at, completed_at)
            values (:user_id, :record_id, 'DELETE', 'FAILED', '   ',
                    now(), now(), now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_lifecycle_rejects_pending_with_started_at(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_lifecycle",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               started_at)
            values (:user_id, :record_id, 'EXPORT', 'PENDING', now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_lifecycle_rejects_running_with_completed_at(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_lifecycle",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               started_at, completed_at)
            values (:user_id, :record_id, 'EXPORT', 'RUNNING', now(), now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_lifecycle_rejects_succeeded_with_error(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_lifecycle",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               error_code, started_at, completed_at)
            values (:user_id, :record_id, 'EXPORT', 'SUCCEEDED', 'E_FAILED',
                    now(), now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_lifecycle_rejects_failed_with_result_key(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_lifecycle",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               result_object_key, error_code, started_at, completed_at)
            values (:user_id, :record_id, 'EXPORT', 'FAILED', 'users/x/out.zip',
                    'E_FAILED', now(), now())
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_account_operation_rejects_completion_before_start(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_account_operation_requests_timestamp_order",
        text(
            """
            insert into account_operation_requests
              (user_id, idempotency_record_id, operation_type, status,
               created_at, started_at, completed_at)
            values (:user_id, :record_id, 'DELETE', 'SUCCEEDED',
                    '2026-09-01T00:00:00Z', '2026-09-02T00:00:00Z',
                    '2026-09-01T12:00:00Z')
            """
        ),
        {"user_id": user_id, "record_id": record_id},
    )


def test_deletion_in_progress_gate_tracks_delete_lifecycle(migrated_connection):
    user_id = _insert_user(migrated_connection)
    export_record = _insert_idempotency_record(
        migrated_connection, user_id=user_id, command_name="START_EXPORT"
    )
    delete_record = _insert_idempotency_record(
        migrated_connection, user_id=user_id, command_name="START_DELETION"
    )
    export_operation_id = _insert_operation(
        migrated_connection,
        user_id=user_id,
        idempotency_record_id=export_record,
        operation_type="EXPORT",
        status="RUNNING",
        started_at=datetime.now(timezone.utc),
    )
    delete_operation_id = _insert_operation(
        migrated_connection,
        user_id=user_id,
        idempotency_record_id=delete_record,
        operation_type="DELETE",
        status="PENDING",
    )

    assert _deletion_in_progress(migrated_connection, user_id=user_id) is True

    migrated_connection.execute(
        text(
            """
            update account_operation_requests
               set status = 'RUNNING', started_at = now()
             where id = :id
            """
        ),
        {"id": delete_operation_id},
    )
    assert _deletion_in_progress(migrated_connection, user_id=user_id) is True

    migrated_connection.execute(
        text(
            """
            update account_operation_requests
               set status = 'SUCCEEDED', completed_at = now()
             where id = :id
            """
        ),
        {"id": delete_operation_id},
    )
    assert _deletion_in_progress(migrated_connection, user_id=user_id) is False

    stored = migrated_connection.execute(
        text("select status from account_operation_requests where id = :id"),
        {"id": export_operation_id},
    ).scalar_one()
    assert stored == "RUNNING"


# --------------------------------------------------------------------------
# Ownership / account-root delete behavior of the 0011 tables only
# --------------------------------------------------------------------------


def test_deleting_user_removes_owned_stories_and_operations(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)
    _insert_story(migrated_connection, user_id=user_id)
    _insert_operation(
        migrated_connection,
        user_id=user_id,
        idempotency_record_id=record_id,
        operation_type="DELETE",
        status="PENDING",
    )

    migrated_connection.execute(
        text("delete from app_users where id = :id"), {"id": user_id}
    )

    for table in ("curiosity_stories", "account_operation_requests"):
        remaining = migrated_connection.execute(
            text(f"select count(*) from {table} where user_id = :id"),
            {"id": user_id},
        ).scalar_one()
        assert remaining == 0


def test_deleting_idempotency_record_removes_its_operation(migrated_connection):
    user_id = _insert_user(migrated_connection)
    record_id = _insert_idempotency_record(migrated_connection, user_id=user_id)
    _insert_operation(
        migrated_connection, user_id=user_id, idempotency_record_id=record_id
    )

    migrated_connection.execute(
        text("delete from idempotency_records where id = :id"), {"id": record_id}
    )

    remaining = migrated_connection.execute(
        text(
            "select count(*) from account_operation_requests "
            "where idempotency_record_id = :id"
        ),
        {"id": record_id},
    ).scalar_one()
    assert remaining == 0


def test_deleting_user_preserves_canonical_ontology(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = migrated_connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED') returning id
            """
        ),
        {"key": f"story-{uuid4()}"},
    ).scalar_one()
    migrated_connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values (:entity_id, 1, 'Canonical', 'Summary',
                    array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    migrated_connection.execute(
        text("update learning_entities set current_version = 1 where id = :id"),
        {"id": entity_id},
    )
    _insert_story(migrated_connection, user_id=user_id)

    migrated_connection.execute(
        text("delete from app_users where id = :id"), {"id": user_id}
    )

    entity_remaining = migrated_connection.execute(
        text("select count(*) from learning_entities where id = :id"),
        {"id": entity_id},
    ).scalar_one()
    version_remaining = migrated_connection.execute(
        text(
            "select count(*) from learning_entity_versions where entity_id = :id"
        ),
        {"id": entity_id},
    ).scalar_one()
    assert entity_remaining == 1
    assert version_remaining == 1
