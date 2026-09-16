from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError


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


def _insert_command(connection, *, user_id, key=None):
    return connection.execute(
        text(
            """
            insert into idempotency_records
              (user_id, idempotency_key, command_name, request_fingerprint,
               expires_at)
            values
              (:user_id, :key, 'submit_reflection', :fingerprint,
               now() + interval '1 day')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "key": key or str(uuid4()),
            "fingerprint": f"sha256:{uuid4().hex}",
        },
    ).scalar_one()


def _event_statement():
    return text(
        """
        insert into learning_events
          (user_id, command_id, event_ordinal, event_type, learning_intent,
           occurred_at, received_at, schema_version, metadata)
        values
          (:user_id, :command_id, :event_ordinal, :event_type,
           :learning_intent, :occurred_at, :received_at, :schema_version,
           cast(:metadata as jsonb))
        returning id
        """
    )


def _event_parameters(
    *,
    user_id,
    command_id=None,
    event_ordinal=None,
    event_type="REFLECTION_SUBMITTED",
    learning_intent=None,
    occurred_at=None,
    received_at=None,
    schema_version=1,
    metadata="{}",
):
    now = datetime.now(UTC)
    return {
        "user_id": user_id,
        "command_id": command_id,
        "event_ordinal": event_ordinal,
        "event_type": event_type,
        "learning_intent": learning_intent,
        "occurred_at": occurred_at or now,
        "received_at": received_at or now,
        "schema_version": schema_version,
        "metadata": metadata,
    }


def test_standalone_event_has_no_command_ordinal(migrated_connection):
    user_id = _insert_user(migrated_connection)

    event_id = migrated_connection.execute(
        _event_statement(), _event_parameters(user_id=user_id)
    ).scalar_one()

    stored = migrated_connection.execute(
        text(
            """
            select command_id, event_ordinal, metadata
              from learning_events
             where id = :event_id
            """
        ),
        {"event_id": event_id},
    ).one()
    assert stored.command_id is None
    assert stored.event_ordinal is None
    assert stored.metadata == {}


def test_one_command_emits_several_ordered_events(migrated_connection):
    user_id = _insert_user(migrated_connection)
    command_id = _insert_command(migrated_connection, user_id=user_id)

    first_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            command_id=command_id,
            event_ordinal=0,
            event_type="REFLECTION_SUBMITTED",
        ),
    ).scalar_one()
    second_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            command_id=command_id,
            event_ordinal=1,
            event_type="EXPLORATION_STARTED",
        ),
    ).scalar_one()

    assert first_id != second_id
    assert migrated_connection.execute(
        text(
            """
            select event_ordinal, event_type
              from learning_events
             where command_id = :command_id
             order by event_ordinal
            """
        ),
        {"command_id": command_id},
    ).all() == [(0, "REFLECTION_SUBMITTED"), (1, "EXPLORATION_STARTED")]


def test_duplicate_command_ordinal_is_rejected(migrated_connection):
    user_id = _insert_user(migrated_connection)
    command_id = _insert_command(migrated_connection, user_id=user_id)
    parameters = _event_parameters(
        user_id=user_id, command_id=command_id, event_ordinal=0
    )
    migrated_connection.execute(_event_statement(), parameters)

    _assert_constraint(
        migrated_connection,
        "uq_learning_events_command_ordinal",
        _event_statement(),
        parameters,
    )


def test_same_ordinal_is_valid_for_different_commands(migrated_connection):
    user_id = _insert_user(migrated_connection)
    first_command = _insert_command(migrated_connection, user_id=user_id)
    second_command = _insert_command(migrated_connection, user_id=user_id)

    migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id, command_id=first_command, event_ordinal=0
        ),
    )
    migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id, command_id=second_command, event_ordinal=0
        ),
    )


@pytest.mark.parametrize(
    ("with_command", "event_ordinal"),
    [(True, None), (False, 0)],
)
def test_command_and_ordinal_must_be_jointly_present(
    migrated_connection, with_command, event_ordinal
):
    user_id = _insert_user(migrated_connection)
    command_id = (
        _insert_command(migrated_connection, user_id=user_id)
        if with_command
        else None
    )

    _assert_constraint(
        migrated_connection,
        "ck_learning_events_command_ordinal_pair",
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            command_id=command_id,
            event_ordinal=event_ordinal,
        ),
    )


def test_event_ordinal_is_nonnegative_but_not_contiguous(migrated_connection):
    user_id = _insert_user(migrated_connection)
    command_id = _insert_command(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_learning_events_event_ordinal",
        _event_statement(),
        _event_parameters(
            user_id=user_id, command_id=command_id, event_ordinal=-1
        ),
    )
    for ordinal in (0, 2):
        migrated_connection.execute(
            _event_statement(),
            _event_parameters(
                user_id=user_id, command_id=command_id, event_ordinal=ordinal
            ),
        )


def test_command_must_belong_to_event_owner(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    command_id = _insert_command(migrated_connection, user_id=other_user_id)

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            _event_statement(),
            _event_parameters(
                user_id=owner_id, command_id=command_id, event_ordinal=0
            ),
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_learning_events_command_owner"
    )


def test_offline_occurrence_and_ingestion_times_remain_distinct(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    occurred_at = datetime.now(UTC) - timedelta(hours=2)
    received_at = datetime.now(UTC)

    event_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            occurred_at=occurred_at,
            received_at=received_at,
        ),
    ).scalar_one()
    stored = migrated_connection.execute(
        text(
            """
            select occurred_at, received_at
              from learning_events
             where id = :event_id
            """
        ),
        {"event_id": event_id},
    ).one()
    assert stored.occurred_at == occurred_at
    assert stored.received_at == received_at
    assert stored.occurred_at < stored.received_at


def test_history_and_ingestion_can_have_different_order(migrated_connection):
    user_id = _insert_user(migrated_connection)
    now = datetime.now(UTC)
    first_received_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            event_type="USER_RETURNED",
            occurred_at=now,
            received_at=now,
        ),
    ).scalar_one()
    later_received_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            event_type="EXPLORATION_STARTED",
            occurred_at=now - timedelta(hours=3),
            received_at=now + timedelta(minutes=1),
        ),
    ).scalar_one()

    by_occurrence = migrated_connection.execute(
        text(
            """
            select id from learning_events
             where user_id = :user_id order by occurred_at
            """
        ),
        {"user_id": user_id},
    ).scalars().all()
    by_ingestion = migrated_connection.execute(
        text(
            """
            select id from learning_events
             where user_id = :user_id order by received_at
            """
        ),
        {"user_id": user_id},
    ).scalars().all()
    assert by_occurrence == [later_received_id, first_received_id]
    assert by_ingestion == [first_received_id, later_received_id]


@pytest.mark.parametrize(
    "learning_intent",
    [
        "DIRECT_INTEREST",
        "PREREQUISITE_SUPPORT",
        "RELATED_EXPLORATION",
        "RETENTION_REVISIT",
        "PRACTICAL_SUPPORT",
        "SERENDIPITY",
        None,
    ],
)
def test_frozen_learning_intents_are_accepted(
    migrated_connection, learning_intent
):
    user_id = _insert_user(migrated_connection)
    migrated_connection.execute(
        _event_statement(),
        _event_parameters(user_id=user_id, learning_intent=learning_intent),
    )


def test_unknown_learning_intent_is_rejected(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _assert_constraint(
        migrated_connection,
        "ck_learning_events_learning_intent",
        _event_statement(),
        _event_parameters(user_id=user_id, learning_intent="MASTERY"),
    )


@pytest.mark.parametrize("schema_version", [0, -1])
def test_schema_version_must_be_positive(migrated_connection, schema_version):
    user_id = _insert_user(migrated_connection)
    _assert_constraint(
        migrated_connection,
        "ck_learning_events_schema_version",
        _event_statement(),
        _event_parameters(user_id=user_id, schema_version=schema_version),
    )


def test_factual_metadata_and_extensible_event_type_persist(migrated_connection):
    user_id = _insert_user(migrated_connection)
    reflection_id = uuid4()
    event_id = migrated_connection.execute(
        _event_statement(),
        _event_parameters(
            user_id=user_id,
            event_type="SUPPORT_CONTENT_DELIVERED",
            metadata=f'{{"reflection_id":"{reflection_id}","delivery":"inline"}}',
        ),
    ).scalar_one()

    stored = migrated_connection.execute(
        text(
            "select event_type, metadata from learning_events where id = :id"
        ),
        {"id": event_id},
    ).one()
    assert stored.event_type == "SUPPORT_CONTENT_DELIVERED"
    assert stored.metadata == {
        "reflection_id": str(reflection_id),
        "delivery": "inline",
    }
