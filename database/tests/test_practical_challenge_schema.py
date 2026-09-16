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
            values ('test', :subject)
            returning id
            """
        ),
        {"subject": str(uuid4())},
    ).scalar_one()


def _insert_entity(connection, *, version: int = 1):
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TECHNIQUE', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"practical-{uuid4()}"},
    ).scalar_one()
    for entity_version in range(1, version + 1):
        connection.execute(
            text(
                """
                insert into learning_entity_versions
                  (entity_id, version, title, summary, knowledge_types, scope)
                values
                  (:entity_id, :version, :title, 'Summary',
                   array['PROCEDURAL'], 'NORMAL')
                """
            ),
            {
                "entity_id": entity_id,
                "version": entity_version,
                "title": f"Technique v{entity_version}",
            },
        )
    return entity_id


def _insert_challenge(connection, *, entity_id):
    return connection.execute(
        text(
            """
            insert into practical_challenges (entity_id)
            values (:entity_id)
            returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()


def _insert_challenge_version(
    connection,
    *,
    challenge_id,
    entity_id,
    version: int = 1,
    entity_version: int = 1,
):
    return connection.execute(
        text(
            """
            insert into practical_challenge_versions
              (challenge_id, entity_id, entity_version, version, prompt,
               target_techniques, estimated_effort_minutes, materials,
               environment_constraints, physical_requirements,
               evidence_requirements, status)
            values
              (:challenge_id, :entity_id, :entity_version, :version,
               'Make a study', '["composition"]'::jsonb, 30,
               '["paper"]'::jsonb, '[]'::jsonb, '[]'::jsonb,
               '{"media":["image"]}'::jsonb, 'REVIEWED')
            returning id
            """
        ),
        {
            "challenge_id": challenge_id,
            "entity_id": entity_id,
            "entity_version": entity_version,
            "version": version,
        },
    ).scalar_one()


def test_challenge_has_stable_identity_and_distinct_immutable_versions(
    migrated_connection,
):
    entity_id = _insert_entity(migrated_connection, version=2)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)
    first_id = _insert_challenge_version(
        migrated_connection,
        challenge_id=challenge_id,
        entity_id=entity_id,
    )
    second_id = _insert_challenge_version(
        migrated_connection,
        challenge_id=challenge_id,
        entity_id=entity_id,
        version=2,
        entity_version=2,
    )

    assert first_id != second_id
    versions = migrated_connection.execute(
        text(
            """
            select challenge_id, version, entity_version
              from practical_challenge_versions
             where challenge_id = :challenge_id
             order by version
            """
        ),
        {"challenge_id": challenge_id},
    ).all()
    assert versions == [(challenge_id, 1, 1), (challenge_id, 2, 2)]

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                update practical_challenge_versions
                   set prompt = 'Rewritten history'
                 where id = :id
                """
            ),
            {"id": first_id},
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_practical_challenge_versions_immutable"
    )


def test_challenge_version_number_is_unique_within_stable_identity(
    migrated_connection,
):
    entity_id = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)
    _insert_challenge_version(
        migrated_connection,
        challenge_id=challenge_id,
        entity_id=entity_id,
    )

    statement = text(
        """
        insert into practical_challenge_versions
          (challenge_id, entity_id, entity_version, version, prompt,
           target_techniques, estimated_effort_minutes, materials,
           environment_constraints, physical_requirements,
           evidence_requirements, status)
        values
          (:challenge_id, :entity_id, 1, 1, 'Duplicate', '[]'::jsonb, 10,
           '[]'::jsonb, '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 'REVIEWED')
        """
    )
    _assert_constraint(
        migrated_connection,
        "uq_practical_challenge_versions_challenge_version",
        statement,
        {"challenge_id": challenge_id, "entity_id": entity_id},
    )


@pytest.mark.parametrize(
    ("version", "prompt", "target_techniques", "effort", "expected"),
    [
        (0, "Prompt", "[]", 10, "ck_practical_challenge_versions_version"),
        (1, "", "[]", 10, "ck_practical_challenge_versions_prompt"),
        (
            1,
            "Prompt",
            "{}",
            10,
            "ck_practical_challenge_versions_target_techniques",
        ),
        (
            1,
            "Prompt",
            "[]",
            0,
            "ck_practical_challenge_versions_estimated_effort",
        ),
    ],
)
def test_challenge_version_rejects_invalid_published_definition(
    migrated_connection,
    version,
    prompt,
    target_techniques,
    effort,
    expected,
):
    entity_id = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)
    statement = text(
        """
        insert into practical_challenge_versions
          (challenge_id, entity_id, entity_version, version, prompt,
           target_techniques, estimated_effort_minutes, materials,
           environment_constraints, physical_requirements,
           evidence_requirements, status)
        values
          (:challenge_id, :entity_id, 1, :version, :prompt,
           cast(:target_techniques as jsonb), :effort, '[]'::jsonb,
           '[]'::jsonb, '[]'::jsonb, '{}'::jsonb, 'REVIEWED')
        """
    )
    _assert_constraint(
        migrated_connection,
        expected,
        statement,
        {
            "challenge_id": challenge_id,
            "entity_id": entity_id,
            "version": version,
            "prompt": prompt,
            "target_techniques": target_techniques,
            "effort": effort,
        },
    )


def test_challenge_version_preserves_owning_entity_and_canonical_version(
    migrated_connection,
):
    first_entity = _insert_entity(migrated_connection)
    other_entity = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=first_entity)
    statement = text(
        """
        insert into practical_challenge_versions
          (challenge_id, entity_id, entity_version, version, prompt,
           target_techniques, estimated_effort_minutes, materials,
           environment_constraints, physical_requirements,
           evidence_requirements, status)
        values
          (:challenge_id, :entity_id, :entity_version, 1, 'Prompt',
           '[]'::jsonb, 10, '[]'::jsonb, '[]'::jsonb, '[]'::jsonb,
           '{}'::jsonb, 'REVIEWED')
        """
    )

    _assert_constraint(
        migrated_connection,
        "fk_practical_challenge_versions_challenge_entity",
        statement,
        {
            "challenge_id": challenge_id,
            "entity_id": other_entity,
            "entity_version": 1,
        },
    )
    _assert_constraint(
        migrated_connection,
        "fk_practical_challenge_versions_entity_version",
        statement,
        {
            "challenge_id": challenge_id,
            "entity_id": first_entity,
            "entity_version": 2,
        },
    )


def test_exploration_preserves_exact_matching_challenge_version(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection, version=2)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)
    first_version_id = _insert_challenge_version(
        migrated_connection,
        challenge_id=challenge_id,
        entity_id=entity_id,
    )
    second_version_id = _insert_challenge_version(
        migrated_connection,
        challenge_id=challenge_id,
        entity_id=entity_id,
        version=2,
        entity_version=2,
    )
    statement = text(
        """
        insert into explorations
          (user_id, entity_id, entity_version, practical_challenge_id,
           practical_challenge_version_id, learning_intent, status, started_at)
        values
          (:user_id, :entity_id, :entity_version, :challenge_id,
           :challenge_version_id, 'PRACTICAL_SUPPORT', 'ACTIVE', now())
        returning id
        """
    )
    exploration_id = migrated_connection.execute(
        statement,
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "entity_version": 1,
            "challenge_id": challenge_id,
            "challenge_version_id": first_version_id,
        },
    ).scalar_one()
    stored = migrated_connection.execute(
        text(
            """
            select practical_challenge_id, practical_challenge_version_id
              from explorations where id = :id
            """
        ),
        {"id": exploration_id},
    ).one()
    assert stored == (challenge_id, first_version_id)

    with pytest.raises(IntegrityError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            statement,
            {
                "user_id": user_id,
                "entity_id": entity_id,
                "entity_version": 1,
                "challenge_id": challenge_id,
                "challenge_version_id": second_version_id,
            },
        )
    assert error.value.orig.diag.constraint_name == (
        "ck_explorations_practical_challenge_version"
    )


def test_exploration_requires_both_challenge_identity_and_version(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)
    statement = text(
        """
        insert into explorations
          (user_id, entity_id, entity_version, practical_challenge_id,
           learning_intent, status, started_at)
        values
          (:user_id, :entity_id, 1, :challenge_id,
           'PRACTICAL_SUPPORT', 'ACTIVE', now())
        """
    )
    _assert_constraint(
        migrated_connection,
        "ck_explorations_practical_challenge_pair",
        statement,
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "challenge_id": challenge_id,
        },
    )
