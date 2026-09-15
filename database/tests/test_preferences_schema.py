from __future__ import annotations

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


def _insert_entity(connection):
    return connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"entity-{uuid4()}"},
    ).scalar_one()


def test_one_preference_row_per_user_and_positive_version(migrated_connection):
    user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into learner_preferences
          (user_id, adventure_preference, preferred_effort, support_style,
           practical_opt_in, version)
        values
          (:user_id, 'BALANCED', '15_20_MIN', 'SMALL_HINT', true, :version)
        """
    )
    migrated_connection.execute(statement, {"user_id": user_id, "version": 1})

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement, {"user_id": user_id, "version": 2}
        )

    second_user = _insert_user(migrated_connection)
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement, {"user_id": second_user, "version": 0}
        )


def test_explicit_interest_is_unique_and_uses_frozen_values(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    statement = text(
        """
        insert into explicit_interest_preferences
          (user_id, entity_id, preference)
        values (:user_id, :entity_id, :preference)
        """
    )
    migrated_connection.execute(
        statement,
        {"user_id": user_id, "entity_id": entity_id, "preference": "MORE"},
    )

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {"user_id": user_id, "entity_id": entity_id, "preference": "LESS"},
        )

    other_user = _insert_user(migrated_connection)
    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {
                "user_id": other_user,
                "entity_id": entity_id,
                "preference": "INVALID",
            },
        )


def test_optimistic_preference_update_detects_stale_version(migrated_connection):
    user_id = _insert_user(migrated_connection)
    migrated_connection.execute(
        text(
            """
            insert into learner_preferences
              (user_id, adventure_preference, preferred_effort, support_style)
            values (:user_id, 'BALANCED', '15_20_MIN', 'SMALL_HINT')
            """
        ),
        {"user_id": user_id},
    )
    update = text(
        """
        update learner_preferences
        set adventure_preference = :value,
            version = version + 1,
            updated_at = now()
        where user_id = :user_id
          and version = :base_version
        returning version
        """
    )

    new_version = migrated_connection.execute(
        update,
        {"value": "ADVENTUROUS", "user_id": user_id, "base_version": 1},
    ).scalar_one()
    stale_result = migrated_connection.execute(
        update,
        {"value": "FOCUSED", "user_id": user_id, "base_version": 1},
    )

    assert new_version == 2
    assert stale_result.rowcount == 0


def test_motivation_code_is_unique_per_user(migrated_connection):
    user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into user_motivations (user_id, motivation_code, free_text)
        values (:user_id, 'LEARN_DAILY', null)
        """
    )
    migrated_connection.execute(statement, {"user_id": user_id})

    with pytest.raises(IntegrityError), migrated_connection.begin_nested():
        migrated_connection.execute(statement, {"user_id": user_id})
