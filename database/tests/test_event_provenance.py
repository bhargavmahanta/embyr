from __future__ import annotations

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
            values ('test', :subject) returning id
            """
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_entity(connection):
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED') returning id
            """
        ),
        {"key": f"event-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Event topic', 'Summary',
               array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    return entity_id


def _insert_device(connection, *, user_id):
    device_id = uuid4()
    connection.execute(
        text(
            """
            insert into user_devices (id, user_id, platform)
            values (:id, :user_id, 'ANDROID')
            """
        ),
        {"id": device_id, "user_id": user_id},
    )
    return device_id


def _insert_exploration(connection, *, user_id, entity_id):
    return connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, learning_intent, status,
               started_at)
            values
              (:user_id, :entity_id, 1, 'DIRECT_INTEREST', 'ACTIVE', now())
            returning id
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    ).scalar_one()


def _insert_assessment_session(connection, *, user_id, exploration_id):
    return connection.execute(
        text(
            """
            insert into assessment_sessions
              (user_id, exploration_id, entity_version, strategy_version,
               confidence_before, status, started_at)
            values
              (:user_id, :exploration_id, 1, 'strategy-v1', 'MAIN_IDEA',
               'ACTIVE', now())
            returning id
            """
        ),
        {"user_id": user_id, "exploration_id": exploration_id},
    ).scalar_one()


def _insert_artifact_graph(connection, *, user_id):
    entity_id = _insert_entity(connection)
    challenge_id = connection.execute(
        text(
            "insert into practical_challenges (entity_id) values (:entity_id) returning id"
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    challenge_version_id = connection.execute(
        text(
            """
            insert into practical_challenge_versions
              (challenge_id, entity_id, entity_version, version, prompt,
               target_techniques, estimated_effort_minutes, materials,
               environment_constraints, physical_requirements,
               evidence_requirements, status)
            values
              (:challenge_id, :entity_id, 1, 1, 'Make a study', '[]'::jsonb,
               15, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb,
               'REVIEWED')
            returning id
            """
        ),
        {"challenge_id": challenge_id, "entity_id": entity_id},
    ).scalar_one()
    exploration_id = connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, practical_challenge_id,
               practical_challenge_version_id, learning_intent, status,
               started_at)
            values
              (:user_id, :entity_id, 1, :challenge_id,
               :challenge_version_id, 'PRACTICAL_SUPPORT', 'ACTIVE', now())
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "challenge_id": challenge_id,
            "challenge_version_id": challenge_version_id,
        },
    ).scalar_one()
    reflection_id = connection.execute(
        text(
            """
            insert into reflections (user_id, exploration_id, entity_id, text)
            values (:user_id, :exploration_id, :entity_id, 'Reflection')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "exploration_id": exploration_id,
            "entity_id": entity_id,
        },
    ).scalar_one()
    object_key = f"users/{user_id}/artifacts/{uuid4()}"
    upload_id = connection.execute(
        text(
            """
            insert into upload_sessions
              (user_id, purpose, declared_content_type, declared_size_bytes,
               object_key, status, completed_at, validated_at)
            values
              (:user_id, 'ARTIFACT', 'image/jpeg', 100, :object_key,
               'VALIDATED', now(), now())
            returning id
            """
        ),
        {"user_id": user_id, "object_key": object_key},
    ).scalar_one()
    media_id = connection.execute(
        text(
            """
            insert into media_objects
              (user_id, upload_id, object_key, validated_content_type,
               validated_size_bytes, sha256, metadata_stripped)
            values
              (:user_id, :upload_id, :object_key, 'image/jpeg', 100,
               'sha256', true)
            returning id
            """
        ),
        {"user_id": user_id, "upload_id": upload_id, "object_key": object_key},
    ).scalar_one()
    artifact_id = connection.execute(
        text(
            """
            insert into artifacts
              (user_id, practical_challenge_id,
               practical_challenge_version_id, exploration_id,
               media_object_id, reflection_id)
            values
              (:user_id, :challenge_id, :challenge_version_id,
               :exploration_id, :media_id, :reflection_id)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "challenge_id": challenge_id,
            "challenge_version_id": challenge_version_id,
            "exploration_id": exploration_id,
            "media_id": media_id,
            "reflection_id": reflection_id,
        },
    ).scalar_one()
    return entity_id, exploration_id, artifact_id


def _insert_event(
    connection,
    *,
    user_id,
    device_id=None,
    entity_id=None,
    exploration_id=None,
    assessment_session_id=None,
    artifact_id=None,
):
    return connection.execute(
        text(
            """
            insert into learning_events
              (user_id, device_id, event_type, entity_id, exploration_id,
               assessment_session_id, artifact_id, occurred_at,
               schema_version)
            values
              (:user_id, :device_id, 'EXPLORATION_STARTED', :entity_id,
               :exploration_id, :assessment_session_id, :artifact_id, now(), 1)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "device_id": device_id,
            "entity_id": entity_id,
            "exploration_id": exploration_id,
            "assessment_session_id": assessment_session_id,
            "artifact_id": artifact_id,
        },
    ).scalar_one()


def test_same_user_provenance_references_can_coexist(migrated_connection):
    user_id = _insert_user(migrated_connection)
    device_id = _insert_device(migrated_connection, user_id=user_id)
    entity_id, exploration_id, artifact_id = _insert_artifact_graph(
        migrated_connection, user_id=user_id
    )
    assessment_id = _insert_assessment_session(
        migrated_connection,
        user_id=user_id,
        exploration_id=exploration_id,
    )

    event_id = _insert_event(
        migrated_connection,
        user_id=user_id,
        device_id=device_id,
        entity_id=entity_id,
        exploration_id=exploration_id,
        assessment_session_id=assessment_id,
        artifact_id=artifact_id,
    )
    assert event_id is not None


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        ("device_id", "fk_learning_events_device_owner"),
        ("exploration_id", "fk_learning_events_exploration_owner"),
        (
            "assessment_session_id",
            "fk_learning_events_assessment_session_owner",
        ),
        ("artifact_id", "fk_learning_events_artifact_owner"),
    ],
)
def test_cross_user_provenance_is_rejected(
    migrated_connection, reference, expected
):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    device_id = _insert_device(migrated_connection, user_id=other_user_id)
    entity_id, exploration_id, artifact_id = _insert_artifact_graph(
        migrated_connection, user_id=other_user_id
    )
    assessment_id = _insert_assessment_session(
        migrated_connection,
        user_id=other_user_id,
        exploration_id=exploration_id,
    )
    values = {
        "user_id": owner_id,
        "device_id": None,
        "entity_id": None,
        "exploration_id": None,
        "assessment_session_id": None,
        "artifact_id": None,
    }
    values[reference] = {
        "device_id": device_id,
        "exploration_id": exploration_id,
        "assessment_session_id": assessment_id,
        "artifact_id": artifact_id,
    }[reference]
    statement = text(
        """
        insert into learning_events
          (user_id, device_id, event_type, entity_id, exploration_id,
           assessment_session_id, artifact_id, occurred_at, schema_version)
        values
          (:user_id, :device_id, 'EXPLORATION_STARTED', :entity_id,
           :exploration_id, :assessment_session_id, :artifact_id, now(), 1)
        """
    )
    _assert_constraint(migrated_connection, expected, statement, values)


def test_optional_provenance_references_are_independent(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    event_id = _insert_event(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )

    assert event_id is not None


def test_event_update_and_delete_are_rejected(migrated_connection):
    user_id = _insert_user(migrated_connection)
    event_id = _insert_event(migrated_connection, user_id=user_id)

    for statement, parameters in (
        (
            text(
                "update learning_events set metadata = cast(:metadata as jsonb) "
                "where id = :id"
            ),
            {"id": event_id, "metadata": '{"changed":true}'},
        ),
        (text("delete from learning_events where id = :id"), {"id": event_id}),
    ):
        with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
            migrated_connection.execute(statement, parameters)
        assert error.value.orig.diag.constraint_name == (
            "ck_learning_events_immutable"
        )

    assert migrated_connection.execute(
        text("select count(*) from learning_events where id = :id"),
        {"id": event_id},
    ).scalar_one() == 1


def test_referenced_device_cannot_be_detached_from_history(migrated_connection):
    user_id = _insert_user(migrated_connection)
    device_id = _insert_device(migrated_connection, user_id=user_id)
    _insert_event(migrated_connection, user_id=user_id, device_id=device_id)

    _assert_constraint(
        migrated_connection,
        "fk_learning_events_device_owner",
        text("delete from user_devices where id = :id"),
        {"id": device_id},
    )


def test_ledger_schema_does_not_duplicate_sensitive_content(migrated_connection):
    columns = {
        row[0]
        for row in migrated_connection.execute(
            text(
                """
                select column_name
                  from information_schema.columns
                 where table_schema = 'public'
                   and table_name = 'learning_events'
                """
            )
        )
    }
    assert {
        "reflection_text",
        "response_content",
        "artifact_media",
        "object_key",
        "feedback",
        "learner_state",
    }.isdisjoint(columns)
