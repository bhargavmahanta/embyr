"""Seeded PostgreSQL coverage for the production recommendation input snapshot."""
from __future__ import annotations

from uuid import uuid4

from sqlalchemy import text

from app.recommendation.snapshot import QUERIES, build_production_snapshot


def _user(connection):
    return connection.execute(
        text("""
            insert into app_users (auth_provider, auth_subject)
            values ('test', :subject) returning id
        """),
        {"subject": str(uuid4())},
    ).scalar_one()


def _entity(connection, *, status="REVIEWED", entity_type="TOPIC", versions=(1,)):
    entity_id = connection.execute(
        text("""
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, :entity_type, :status) returning id
        """),
        {"key": f"recommendation-{uuid4()}", "entity_type": entity_type,
         "status": status},
    ).scalar_one()
    for version in versions:
        connection.execute(
            text("""
                insert into learning_entity_versions
                  (entity_id, version, title, summary, knowledge_types, scope)
                values (:entity_id, :version, :title, :summary,
                        array['CONCEPTUAL'], 'NORMAL')
            """),
            {"entity_id": entity_id, "version": version,
             "title": f"Title {version}", "summary": f"Summary {version}"},
        )
    connection.execute(
        text("update learning_entities set current_version = :version where id = :id"),
        {"version": versions[-1], "id": entity_id},
    )
    return entity_id


def _objective(connection, entity_id):
    return connection.execute(
        text("""
            insert into learning_objectives
              (entity_id, entity_version, objective_type, description, importance)
            values (:entity_id, 2, 'UNDERSTANDING', 'Understand this', 0.5)
            returning id
        """),
        {"entity_id": entity_id},
    ).scalar_one()


def _objective_state(connection, user_id, objective_id, state, estimate):
    connection.execute(
        text("""
            insert into learner_objective_state
              (user_id, objective_id, categorical_state, understanding_estimate,
               evaluation_confidence, model_version)
            values (:user_id, :objective_id, :state, :estimate, 0.8,
                    'projector-v1')
        """),
        {"user_id": user_id, "objective_id": objective_id,
         "state": state, "estimate": estimate},
    )


def test_seeded_snapshot_current_versions_unknown_state_and_rls(migrated_connection):
    connection = migrated_connection
    user_a, user_b = _user(connection), _user(connection)
    entity_id = _entity(connection, versions=(1, 2))
    area_id = _entity(connection, entity_type="AREA")
    draft_id = _entity(connection, status="DRAFT")
    understood_id = _objective(connection, entity_id)
    unknown_id = _objective(connection, entity_id)

    for user_id in (user_a, user_b):
        connection.execute(
            text("""
                insert into explicit_interest_preferences
                  (user_id, entity_id, preference)
                values (:user_id, :entity_id, 'MORE')
            """),
            {"user_id": user_id, "entity_id": entity_id},
        )
        connection.execute(
            text("""
                insert into explorations
                  (user_id, entity_id, entity_version, learning_intent,
                   status, started_at)
                values (:user_id, :entity_id, :version, 'DIRECT_INTEREST',
                        'ACTIVE', now())
            """),
            {"user_id": user_id, "entity_id": entity_id,
             "version": 1 if user_id == user_a else 2},
        )
        connection.execute(
            text("""
                insert into learner_interest_state
                  (user_id, entity_id, recent_affinity, long_term_affinity,
                   user_initiated_strength, algorithm_exposure_strength,
                   model_version)
                values (:user_id, :entity_id, 0.4, 0.3, 0.2, 0.1,
                        'projector-v1')
            """),
            {"user_id": user_id, "entity_id": entity_id},
        )
        connection.execute(
            text("""
                insert into learner_challenge_state
                  (user_id, area_id, ability_estimate, model_version)
                values (:user_id, :area_id, 1200.0, 'projector-v1')
            """),
            {"user_id": user_id, "area_id": area_id},
        )
    _objective_state(connection, user_a, understood_id, "UNDERSTOOD", 0.05)
    _objective_state(connection, user_a, unknown_id, None, 1.0)
    _objective_state(connection, user_b, understood_id, "RETAINED", 0.9)

    constraint_names = set(connection.execute(text("""
        select conname from pg_constraint
         where conrelid = 'public.learner_objective_state'::regclass
    """)).scalars())
    assert "ck_learner_objective_state_categorical_state" in constraint_names

    connection.execute(text("set local role app_backend"))
    connection.execute(
        text("select set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_a)},
    )
    owned = ("preferences", "explorations", "objective_states",
             "interest_states", "challenge_states")
    for name in owned:
        # B's rows satisfy the explicit predicate but RLS still hides them.
        assert connection.execute(
            text(QUERIES[name]), {"user_id": user_b}
        ).mappings().all() == []

    rows = {
        name: list(connection.execute(
            text(query), {"user_id": user_a}
        ).mappings().all())
        for name, query in QUERIES.items()
    }
    snapshot = build_production_snapshot(user_a, rows)

    assert [(row["entity_id"], row["entity_version"])
            for row in snapshot.entities if row["entity_id"] == str(entity_id)] == [
        (str(entity_id), 2)
    ]
    assert all(row["entity_id"] != str(draft_id) for row in snapshot.entities)
    assert len(snapshot.explorations) == 1
    assert snapshot.explorations[0]["entity_version"] == 1
    assert snapshot.explicit_preferences[0]["entity_version"] == 2
    assert snapshot.anchor_entities == ({
        "entity_id": str(entity_id), "entity_version": 2,
    },)
    assert {row["objective_id"]: row["categorical_state"]
            for row in rows["objective_states"]} == {
        understood_id: "UNDERSTOOD", unknown_id: None,
    }
    assert snapshot.objective_states == ({
        "objective_id": str(understood_id), "entity_id": str(entity_id),
        "entity_version": 2, "state": "UNDERSTOOD",
    },)
    assert len(snapshot.interest_states) == 1
    assert len(snapshot.challenge_states) == 1
