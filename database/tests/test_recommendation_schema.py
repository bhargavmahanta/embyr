from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

NOW = datetime.now(timezone.utc)
EARLIER = NOW - timedelta(hours=1)


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


def _insert_entity(connection):
    return connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"recommendation-{uuid4()}"},
    ).scalar_one()


def _insert_entity_version(connection, *, entity_id, version: int = 1):
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, :version, 'Title', 'Summary',
               array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id, "version": version},
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


def _insert_recommendation(
    connection,
    *,
    user_id,
    entity_id=None,
    entity_version=None,
    challenge_id=None,
    mode: str = "EXPLORE",
    distance_band: str = "ADJACENT",
    ranking_model_version: str = "ranker-v1",
    score_components=None,
    reason_code: str = "BUILDS_ON_EXPLORATION",
    presentation_version: str = "presentation-v1",
    presentation=None,
    presented_at=None,
    decided_at=None,
    decision=None,
):
    return connection.execute(
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, challenge_id, mode,
               distance_band, ranking_model_version, score_components,
               reason_code, presentation_version, presentation, presented_at,
               decided_at, decision)
            values
              (:user_id, :entity_id, :entity_version, :challenge_id, :mode,
               :distance_band, :ranking_model_version,
               cast(:score_components as jsonb),
               :reason_code, :presentation_version,
               cast(:presentation as jsonb),
               coalesce(cast(:presented_at as timestamptz), now()),
               :decided_at, :decision)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "entity_version": entity_version,
            "challenge_id": challenge_id,
            "mode": mode,
            "distance_band": distance_band,
            "ranking_model_version": ranking_model_version,
            "score_components": json.dumps(
                score_components or {"interest_fit": 0.5, "novelty": 0.25}
            ),
            "reason_code": reason_code,
            "presentation_version": presentation_version,
            "presentation": json.dumps(
                presentation or {"hook": "A hook", "reason": "A reason"}
            ),
            "presented_at": presented_at,
            "decided_at": decided_at,
            "decision": decision,
        },
    ).scalar_one()


def _insert_exploration(
    connection, *, user_id, entity_id, entity_version: int, recommendation_id=None
):
    return connection.execute(
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, recommendation_id,
               learning_intent, status, started_at)
            values
              (:user_id, :entity_id, :entity_version, :recommendation_id,
               'DIRECT_INTEREST', 'ACTIVE', now())
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "entity_version": entity_version,
            "recommendation_id": recommendation_id,
        },
    ).scalar_one()


def test_recommendation_targets_learning_entity(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
    )

    assert recommendation_id is not None


def test_recommendation_targets_practical_challenge(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)

    recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        challenge_id=challenge_id,
    )

    assert recommendation_id is not None


def test_recommendation_rejects_no_target(migrated_connection):
    user_id = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_target_exclusive",
        text(
            """
            insert into recommendations
              (user_id, mode, distance_band, ranking_model_version,
               score_components, reason_code, presentation_version,
               presentation, presented_at)
            values
              (:user_id, 'EXPLORE', 'ADJACENT', 'ranker-v1', '{}'::jsonb,
               'BUILDS_ON_EXPLORATION', 'presentation-v1', '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id},
    )


def test_recommendation_rejects_two_targets(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_target_exclusive",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, challenge_id, mode,
               distance_band, ranking_model_version, score_components,
               reason_code, presentation_version, presentation, presented_at)
            values
              (:user_id, :entity_id, 1, :challenge_id, 'EXPLORE', 'ADJACENT',
               'ranker-v1', '{}'::jsonb, 'BUILDS_ON_EXPLORATION',
               'presentation-v1', '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id, "challenge_id": challenge_id},
    )


def test_recommendation_requires_entity_version_for_entity_target(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_entity_version_presence",
        text(
            """
            insert into recommendations
              (user_id, entity_id, mode, distance_band, ranking_model_version,
               score_components, reason_code, presentation_version,
               presentation, presented_at)
            values
              (:user_id, :entity_id, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_rejects_version_without_entity(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    challenge_id = _insert_challenge(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_entity_version_presence",
        text(
            """
            insert into recommendations
              (user_id, entity_version, challenge_id, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at)
            values
              (:user_id, 1, :challenge_id, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "challenge_id": challenge_id},
    )


def test_recommendation_rejects_unknown_entity_version(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "fk_recommendations_entity_version",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at)
            values
              (:user_id, :entity_id, 99, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_rejects_unknown_mode(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_mode",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at)
            values
              (:user_id, :entity_id, 1, 'MAYBE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_rejects_unknown_distance_band(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_distance_band",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at)
            values
              (:user_id, :entity_id, 1, 'EXPLORE', 'EXTREME', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_rejects_unknown_decision(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_decision",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at, decision,
               decided_at)
            values
              (:user_id, :entity_id, 1, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now(), 'MAYBE', now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_requires_decided_at_with_decision(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_decision_timestamps",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at, decision)
            values
              (:user_id, :entity_id, 1, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now(), 'ACCEPT')
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_requires_decision_with_decided_at(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_decision_timestamps",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at, decided_at)
            values
              (:user_id, :entity_id, 1, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, now(), now())
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_recommendation_rejects_decision_before_presentation(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    _assert_constraint(
        migrated_connection,
        "ck_recommendations_decision_timestamps",
        text(
            """
            insert into recommendations
              (user_id, entity_id, entity_version, mode, distance_band,
               ranking_model_version, score_components, reason_code,
               presentation_version, presentation, presented_at, decision,
               decided_at)
            values
              (:user_id, :entity_id, 1, 'EXPLORE', 'ADJACENT', 'ranker-v1',
               '{}'::jsonb, 'BUILDS_ON_EXPLORATION', 'presentation-v1',
               '{}'::jsonb, :presented_at, 'ACCEPT', :decided_at)
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "presented_at": NOW,
            "decided_at": EARLIER,
        },
    )


def test_recommendation_accepts_decision_at_or_after_presentation(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
        presented_at=EARLIER,
        decided_at=NOW,
        decision="ACCEPT",
    )

    stored = migrated_connection.execute(
        text("select decision from recommendations where id = :id"),
        {"id": recommendation_id},
    ).scalar_one()
    assert stored == "ACCEPT"


def test_recommendation_persists_score_and_presentation_metadata(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    score_components = {"interest_fit": 0.8, "diversity_penalty": 0.1}
    presentation = {
        "hook": "Before data moves, machines agree.",
        "reason": "Builds on networking.",
        "target": {"title": "Three-way handshake"},
    }
    recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
        score_components=score_components,
        presentation=presentation,
    )

    row = migrated_connection.execute(
        text(
            """
            select score_components, presentation, ranking_model_version,
                   presentation_version
              from recommendations
             where id = :id
            """
        ),
        {"id": recommendation_id},
    ).one()
    assert row[0] == score_components
    assert row[1] == presentation
    assert row[2] == "ranker-v1"
    assert row[3] == "presentation-v1"


def test_same_target_can_be_presented_more_than_once(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)

    first = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
    )
    second = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
    )

    assert first != second
    count = migrated_connection.execute(
        text(
            """
            select count(*) from recommendations
             where user_id = :user_id and entity_id = :entity_id
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    ).scalar_one()
    assert count == 2


def test_recommendation_user_presentation_index_exists(migrated_connection):
    index = migrated_connection.execute(
        text(
            """
            select indexdef from pg_indexes
             where schemaname = 'public'
               and tablename = 'recommendations'
               and indexname = 'ix_recommendations_user_presented'
            """
        )
    ).scalar_one_or_none()

    assert index is not None
    assert "presented_at DESC" in index


def test_deleting_user_removes_owned_recommendations(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)
    _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
    )

    migrated_connection.execute(
        text("delete from app_users where id = :id"), {"id": user_id}
    )

    remaining = migrated_connection.execute(
        text("select count(*) from recommendations where user_id = :id"),
        {"id": user_id},
    ).scalar_one()
    assert remaining == 0


def test_deleting_recommendation_clears_presentation_link(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)
    recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
    )
    exploration_id = _insert_exploration(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        entity_version=1,
        recommendation_id=recommendation_id,
    )

    migrated_connection.execute(
        text("delete from recommendations where id = :id"),
        {"id": recommendation_id},
    )

    row = migrated_connection.execute(
        text("select recommendation_id from explorations where id = :id"),
        {"id": exploration_id},
    ).scalar_one()
    assert row is None


def test_exploration_rejects_cross_user_recommendation(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_entity_version(migrated_connection, entity_id=entity_id)
    owner_recommendation_id = _insert_recommendation(
        migrated_connection,
        user_id=owner_id,
        entity_id=entity_id,
        entity_version=1,
    )

    _assert_constraint(
        migrated_connection,
        "fk_explorations_recommendation_owner",
        text(
            """
            insert into explorations
              (user_id, entity_id, entity_version, recommendation_id,
               learning_intent, status, started_at)
            values
              (:user_id, :entity_id, 1, :recommendation_id,
               'DIRECT_INTEREST', 'ACTIVE', now())
            """
        ),
        {
            "user_id": other_user_id,
            "entity_id": entity_id,
            "recommendation_id": owner_recommendation_id,
        },
    )
