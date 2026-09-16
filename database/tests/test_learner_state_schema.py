from __future__ import annotations

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


def _insert_entity(connection):
    return connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"state-{uuid4()}"},
    ).scalar_one()


def _insert_objective(connection):
    entity_id = _insert_entity(connection)
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
    objective_id = connection.execute(
        text(
            """
            insert into learning_objectives
              (entity_id, entity_version, objective_type, description, importance)
            values
              (:entity_id, 1, 'UNDERSTANDING', 'Understand it', 0.5)
            returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    return entity_id, objective_id


def _insert_evidence(connection, *, user_id, entity_id, objective_id):
    return connection.execute(
        text(
            """
            insert into learning_evidence
              (user_id, entity_id, objective_id, source_type, source_id,
               evidence_type, evidence_strength, status)
            values
              (:user_id, :entity_id, :objective_id, 'REFLECTION', :source_id,
               'REFLECTION', 'WEAK', 'ACTIVE')
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "objective_id": objective_id,
            "source_id": uuid4(),
        },
    ).scalar_one()


def _insert_event(connection, *, user_id):
    return connection.execute(
        text(
            """
            insert into learning_events
              (user_id, event_type, occurred_at, schema_version)
            values (:user_id, 'EXPLORATION_STARTED', now(), 1)
            returning id
            """
        ),
        {"user_id": user_id},
    ).scalar_one()


def _insert_interest_state(
    connection,
    *,
    user_id,
    entity_id,
    model_version: str = "projector-v1",
    user_initiated_strength: float = 0.4,
):
    return connection.execute(
        text(
            """
            insert into learner_interest_state
              (user_id, entity_id, recent_affinity, long_term_affinity,
               user_initiated_strength, algorithm_exposure_strength,
               computed_at, model_version)
            values
              (:user_id, :entity_id, 0.5, 0.5, :user_initiated_strength, 0.5,
               now(), :model_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "user_initiated_strength": user_initiated_strength,
            "model_version": model_version,
        },
    ).scalar_one()


def _insert_objective_state(
    connection,
    *,
    user_id,
    objective_id,
    model_version: str = "projector-v1",
    understanding_estimate: float = 0.5,
):
    return connection.execute(
        text(
            """
            insert into learner_objective_state
              (user_id, objective_id, understanding_estimate, evaluation_confidence,
               computed_at, model_version)
            values
              (:user_id, :objective_id, :understanding_estimate, 0.8,
               now(), :model_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "objective_id": objective_id,
            "understanding_estimate": understanding_estimate,
            "model_version": model_version,
        },
    ).scalar_one()


def _insert_retention_state(
    connection,
    *,
    user_id,
    entity_id,
    model_version: str = "projector-v1",
    with_window: bool = False,
):
    window = (
        "tstzrange(now(), now() + interval '3 days', '[)')"
        if with_window
        else "null"
    )
    return connection.execute(
        text(
            f"""
            insert into learner_retention_state
              (user_id, entity_id, retention_estimate, next_revisit_window,
               computed_at, model_version)
            values
              (:user_id, :entity_id, 0.6, {window}, now(), :model_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "model_version": model_version,
        },
    ).scalar_one()


def _insert_confidence_state(
    connection,
    *,
    user_id,
    entity_id,
    self_reported_confidence: float | None = 0.5,
    model_version: str = "projector-v1",
):
    return connection.execute(
        text(
            """
            insert into learner_confidence_state
              (user_id, entity_id, self_reported_confidence, observed_understanding,
               calibration_state, computed_at, model_version)
            values
              (:user_id, :entity_id, :self_reported_confidence, 0.5,
               'CALIBRATED', now(), :model_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "entity_id": entity_id,
            "self_reported_confidence": self_reported_confidence,
            "model_version": model_version,
        },
    ).scalar_one()


def _insert_challenge_state(
    connection,
    *,
    user_id,
    area_id,
    recent_success_rate: float = 0.5,
    model_version: str = "projector-v1",
):
    return connection.execute(
        text(
            """
            insert into learner_challenge_state
              (user_id, area_id, ability_estimate, estimate_confidence,
               recent_support_rate, recent_success_rate, computed_at,
               model_version)
            values
              (:user_id, :area_id, 1200.0, 0.7, 0.3, :recent_success_rate,
               now(), :model_version)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "area_id": area_id,
            "recent_success_rate": recent_success_rate,
            "model_version": model_version,
        },
    ).scalar_one()


def _insert_state_evidence_link(
    connection,
    *,
    user_id,
    state_dimension: str = "INTEREST",
    target_id=None,
    learning_evidence_id=None,
    learning_event_id=None,
    weight: float | None = None,
):
    return connection.execute(
        text(
            """
            insert into state_evidence_links
              (user_id, state_dimension, target_id, learning_evidence_id,
               learning_event_id, weight)
            values
              (:user_id, :state_dimension, :target_id, :learning_evidence_id,
               :learning_event_id, :weight)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "state_dimension": state_dimension,
            "target_id": target_id or uuid4(),
            "learning_evidence_id": learning_evidence_id,
            "learning_event_id": learning_event_id,
            "weight": weight,
        },
    ).scalar_one()


def test_interest_state_has_one_row_per_logical_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_interest_state(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_learner_interest_state_user_entity",
        text(
            """
            insert into learner_interest_state
              (user_id, entity_id, recent_affinity, long_term_affinity,
               user_initiated_strength, algorithm_exposure_strength,
               computed_at, model_version)
            values
              (:user_id, :entity_id, 0.5, 0.5, 0.5, 0.5, now(),
               'projector-v2')
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_interest_state_allows_same_entity_for_other_users(migrated_connection):
    first_user_id = _insert_user(migrated_connection)
    second_user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    _insert_interest_state(
        migrated_connection, user_id=first_user_id, entity_id=entity_id
    )
    _insert_interest_state(
        migrated_connection, user_id=second_user_id, entity_id=entity_id
    )


def test_interest_state_latent_strengths_are_not_range_constrained(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    _insert_interest_state(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        user_initiated_strength=4.25,
    )


def test_objective_state_has_one_row_per_logical_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _, objective_id = _insert_objective(migrated_connection)
    _insert_objective_state(
        migrated_connection, user_id=user_id, objective_id=objective_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_learner_objective_state_user_objective",
        text(
            """
            insert into learner_objective_state
              (user_id, objective_id, understanding_estimate,
               evaluation_confidence, computed_at, model_version)
            values
              (:user_id, :objective_id, 0.9, 0.9, now(), 'projector-v2')
            """
        ),
        {"user_id": user_id, "objective_id": objective_id},
    )


def test_objective_state_understanding_is_not_range_constrained(
    migrated_connection,
):
    user_id = _insert_user(migrated_connection)
    _, objective_id = _insert_objective(migrated_connection)

    _insert_objective_state(
        migrated_connection,
        user_id=user_id,
        objective_id=objective_id,
        understanding_estimate=12.5,
    )


def test_objective_state_confidence_rejects_out_of_range(migrated_connection):
    user_id = _insert_user(migrated_connection)
    _, objective_id = _insert_objective(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_learner_objective_state_evaluation_confidence",
        text(
            """
            insert into learner_objective_state
              (user_id, objective_id, understanding_estimate,
               evaluation_confidence, computed_at, model_version)
            values
              (:user_id, :objective_id, 0.5, 1.5, now(), 'projector-v1')
            """
        ),
        {"user_id": user_id, "objective_id": objective_id},
    )


def test_retention_state_has_one_row_per_logical_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_retention_state(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_learner_retention_state_user_entity",
        text(
            """
            insert into learner_retention_state
              (user_id, entity_id, retention_estimate, computed_at, model_version)
            values (:user_id, :entity_id, 0.7, now(), 'projector-v2')
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_retention_state_stores_revisit_window(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    _insert_retention_state(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        with_window=True,
    )

    window = migrated_connection.execute(
        text(
            """
            select next_revisit_window
              from learner_retention_state
             where user_id = :user_id and entity_id = :entity_id
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    ).scalar_one()
    assert window.lower is not None
    assert window.upper is not None


def test_confidence_state_has_one_row_per_logical_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_confidence_state(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_learner_confidence_state_user_entity",
        text(
            """
            insert into learner_confidence_state
              (user_id, entity_id, self_reported_confidence,
               observed_understanding, computed_at, model_version)
            values (:user_id, :entity_id, 0.5, 0.5, now(), 'projector-v2')
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_confidence_state_rejects_out_of_range_confidence(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_learner_confidence_state_self_reported",
        text(
            """
            insert into learner_confidence_state
              (user_id, entity_id, self_reported_confidence,
               observed_understanding, computed_at, model_version)
            values (:user_id, :entity_id, -0.1, 0.5, now(), 'projector-v1')
            """
        ),
        {"user_id": user_id, "entity_id": entity_id},
    )


def test_challenge_state_has_one_row_per_logical_key(migrated_connection):
    user_id = _insert_user(migrated_connection)
    area_id = _insert_entity(migrated_connection)
    _insert_challenge_state(
        migrated_connection, user_id=user_id, area_id=area_id
    )

    _assert_constraint(
        migrated_connection,
        "uq_learner_challenge_state_user_area",
        text(
            """
            insert into learner_challenge_state
              (user_id, area_id, ability_estimate, computed_at, model_version)
            values (:user_id, :area_id, 1250.0, now(), 'projector-v2')
            """
        ),
        {"user_id": user_id, "area_id": area_id},
    )


def test_challenge_state_ability_is_not_range_constrained(migrated_connection):
    user_id = _insert_user(migrated_connection)
    area_id = _insert_entity(migrated_connection)

    _insert_challenge_state(
        migrated_connection, user_id=user_id, area_id=area_id
    )


def test_challenge_state_rejects_out_of_range_rate(migrated_connection):
    user_id = _insert_user(migrated_connection)
    area_id = _insert_entity(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_learner_challenge_state_recent_success_rate",
        text(
            """
            insert into learner_challenge_state
              (user_id, area_id, ability_estimate, recent_success_rate,
               computed_at, model_version)
            values (:user_id, :area_id, 1200.0, 1.2, now(), 'projector-v1')
            """
        ),
        {"user_id": user_id, "area_id": area_id},
    )


def test_state_evidence_link_requires_exactly_one_source(migrated_connection):
    user_id = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "ck_state_evidence_links_single_source",
        text(
            """
            insert into state_evidence_links
              (user_id, state_dimension, target_id)
            values (:user_id, 'INTEREST', :target_id)
            """
        ),
        {"user_id": user_id, "target_id": uuid4()},
    )


def test_state_evidence_link_rejects_two_sources(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id, objective_id = _insert_objective(migrated_connection)
    evidence_id = _insert_evidence(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        objective_id=objective_id,
    )
    event_id = _insert_event(migrated_connection, user_id=user_id)

    _assert_constraint(
        migrated_connection,
        "ck_state_evidence_links_single_source",
        text(
            """
            insert into state_evidence_links
              (user_id, state_dimension, target_id, learning_evidence_id,
               learning_event_id)
            values
              (:user_id, 'OBJECTIVE', :target_id, :evidence_id, :event_id)
            """
        ),
        {
            "user_id": user_id,
            "target_id": objective_id,
            "evidence_id": evidence_id,
            "event_id": event_id,
        },
    )


def test_state_evidence_link_accepts_evidence_or_event(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id, objective_id = _insert_objective(migrated_connection)
    evidence_id = _insert_evidence(
        migrated_connection,
        user_id=user_id,
        entity_id=entity_id,
        objective_id=objective_id,
    )
    event_id = _insert_event(migrated_connection, user_id=user_id)

    evidence_link_id = _insert_state_evidence_link(
        migrated_connection,
        user_id=user_id,
        state_dimension="OBJECTIVE",
        target_id=objective_id,
        learning_evidence_id=evidence_id,
        weight=2.5,
    )
    event_link_id = _insert_state_evidence_link(
        migrated_connection,
        user_id=user_id,
        state_dimension="INTEREST",
        target_id=entity_id,
        learning_event_id=event_id,
    )

    assert evidence_link_id is not None
    assert event_link_id is not None


def test_state_evidence_link_rejects_cross_user_evidence(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id, objective_id = _insert_objective(migrated_connection)
    other_evidence_id = _insert_evidence(
        migrated_connection,
        user_id=other_user_id,
        entity_id=entity_id,
        objective_id=objective_id,
    )

    _assert_constraint(
        migrated_connection,
        "fk_state_evidence_links_evidence_owner",
        text(
            """
            insert into state_evidence_links
              (user_id, state_dimension, target_id, learning_evidence_id)
            values
              (:user_id, 'OBJECTIVE', :target_id, :evidence_id)
            """
        ),
        {
            "user_id": owner_id,
            "target_id": objective_id,
            "evidence_id": other_evidence_id,
        },
    )


def test_state_evidence_link_rejects_cross_user_event(migrated_connection):
    owner_id = _insert_user(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    other_event_id = _insert_event(
        migrated_connection, user_id=other_user_id
    )

    _assert_constraint(
        migrated_connection,
        "fk_state_evidence_links_event_owner",
        text(
            """
            insert into state_evidence_links
              (user_id, state_dimension, target_id, learning_event_id)
            values
              (:user_id, 'INTEREST', :target_id, :event_id)
            """
        ),
        {
            "user_id": owner_id,
            "target_id": entity_id,
            "event_id": other_event_id,
        },
    )


def test_deleting_user_removes_owned_state(migrated_connection):
    user_id = _insert_user(migrated_connection)
    entity_id = _insert_entity(migrated_connection)
    _insert_interest_state(
        migrated_connection, user_id=user_id, entity_id=entity_id
    )

    migrated_connection.execute(
        text("delete from app_users where id = :id"), {"id": user_id}
    )

    remaining = migrated_connection.execute(
        text(
            "select count(*) from learner_interest_state where user_id = :id"
        ),
        {"id": user_id},
    ).scalar_one()
    assert remaining == 0
