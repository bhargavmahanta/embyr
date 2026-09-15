from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError


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


def _insert_versioned_entity(connection):
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"entity-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Title', 'Summary', array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    return entity_id


def _insert_exploration(
    connection,
    *,
    user_id,
    entity_id,
    entity_version: int = 1,
    learning_intent: str = "DIRECT_INTEREST",
    status: str = "ACTIVE",
    started_at: datetime | None = None,
    paused_at: datetime | None = None,
    completed_at: datetime | None = None,
):
    return connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, learning_intent, status,
               started_at, paused_at, completed_at)
            values
              (:user_id, :entity_id, :entity_version, :learning_intent, :status,
               :started_at, :paused_at, :completed_at)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "entity_version": entity_version,
            "learning_intent": learning_intent,
            "status": status,
            "started_at": started_at or datetime.now(UTC),
            "paused_at": paused_at,
            "completed_at": completed_at,
        },
    ).scalar_one()


def test_exploration_rejects_unfrozen_learning_intent(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_exploration(
            migrated_connection,
            user_id=user_id,
            entity_id=entity_id,
            learning_intent="INFERRED_PREFERENCE",
        )


def test_exploration_preserves_existing_entity_version(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)

    _insert_exploration(
        migrated_connection, user_id=user_id, entity_id=entity_id, entity_version=1
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_exploration(
            migrated_connection,
            user_id=user_id,
            entity_id=entity_id,
            entity_version=2,
        )


@pytest.mark.parametrize(
    ("status", "paused", "completed"),
    [
        ("ACTIVE", False, True),
        ("PAUSED", False, False),
        ("COMPLETED", False, False),
    ],
)
def test_exploration_status_requires_coherent_timestamps(
    migrated_connection, status, paused, completed
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)
    now = datetime.now(UTC)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_exploration(
            migrated_connection,
            user_id=user_id,
            entity_id=entity_id,
            status=status,
            paused_at=now if paused else None,
            completed_at=now if completed else None,
        )


def test_resumed_exploration_can_retain_pause_timestamp(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)
    started_at = datetime.now(UTC) - timedelta(minutes=5)

    _insert_exploration(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        status="ACTIVE",
        started_at=started_at,
        paused_at=started_at + timedelta(minutes=1),
    )


def test_lifecycle_timestamps_cannot_precede_start(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)
    started_at = datetime.now(UTC)

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        _insert_exploration(
            migrated_connection,
            user_id=user_id,
            entity_id=entity_id,
            status="COMPLETED",
            started_at=started_at,
            completed_at=started_at - timedelta(seconds=1),
        )


def test_reflection_requires_same_user_as_exploration(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)
    exploration_id = _insert_exploration(
        migrated_connection, user_id=owner_id, entity_id=entity_id
    )
    statement = text(
        """
        insert into reflections
          (user_id, exploration_id, entity_id, text)
        values (:user_id, :exploration_id, :entity_id, 'A reflection')
        """
    )

    migrated_connection.execute(
        statement,
        {
            "user_id": owner_id,
            "exploration_id": exploration_id,
            "entity_id": entity_id,
        },
    )
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {
                "user_id": other_user_id,
                "exploration_id": exploration_id,
                "entity_id": entity_id,
            },
        )


def test_reflection_optimistic_update_detects_stale_version(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_versioned_entity(migrated_connection)
    exploration_id = _insert_exploration(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )
    reflection_id = migrated_connection.execute(
        text(
            """
            insert into reflections (user_id, exploration_id, entity_id, text)
            values (:user_id, :exploration_id, :entity_id, 'First')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "exploration_id": exploration_id,
            "entity_id": entity_id,
        },
    ).scalar_one()
    update = text(
        """
        update reflections
        set text = :text, version = version + 1, updated_at = now()
        where id = :id and user_id = :user_id and version = :base_version
        returning version
        """
    )

    assert (
        migrated_connection.execute(
            update,
            {
                "text": "Second",
                "id": reflection_id,
                "user_id": user_id,
                "base_version": 1,
            },
        ).scalar_one()
        == 2
    )
    stale = migrated_connection.execute(
        update,
        {
            "text": "Stale",
            "id": reflection_id,
            "user_id": user_id,
            "base_version": 1,
        },
    )
    assert stale.rowcount == 0
