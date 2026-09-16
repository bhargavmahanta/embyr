from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from time import monotonic, sleep
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


def _insert_entity_and_objective(connection):
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"assessment-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Assessment topic', 'Summary',
               array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": entity_id},
    )
    objective_id = connection.execute(
        text(
            """
            insert into learning_objectives
              (entity_id, entity_version, objective_type, description, importance)
            values (:entity_id, 1, 'EXPLANATION', 'Explain the topic', 0.8)
            returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    return entity_id, objective_id


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


def _insert_session(
    connection,
    *,
    user_id,
    exploration_id,
    entity_version: int = 1,
    confidence_before: str = "MAIN_IDEA",
    status: str = "ACTIVE",
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
):
    return connection.execute(
        text(
            """
            insert into assessment_sessions
              (user_id, exploration_id, entity_version, strategy_version,
               confidence_before, status, started_at, completed_at)
            values
              (:user_id, :exploration_id, :entity_version, 'strategy-v1',
               :confidence_before, :status, :started_at, :completed_at)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "exploration_id": exploration_id,
            "entity_version": entity_version,
            "confidence_before": confidence_before,
            "status": status,
            "started_at": started_at or datetime.now(UTC),
            "completed_at": completed_at,
        },
    ).scalar_one()


def _insert_interaction(
    connection,
    *,
    user_id,
    session_id,
    objective_id,
    sequence: int = 1,
):
    return connection.execute(
        text(
            """
            insert into assessment_interactions
              (user_id, assessment_session_id, objective_id, interaction_type,
               prompt_definition, rubric_version, sequence)
            values
              (:user_id, :session_id, :objective_id, 'FREE_RESPONSE',
               '{"prompt":"Explain it"}'::jsonb, 'rubric-v1', :sequence)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "session_id": session_id,
            "objective_id": objective_id,
            "sequence": sequence,
        },
    ).scalar_one()


def _valid_graph(connection):
    user_id = _insert_user(connection)
    entity_id, objective_id = _insert_entity_and_objective(connection)
    exploration_id = _insert_exploration(
        connection, user_id=user_id, entity_id=entity_id
    )
    session_id = _insert_session(
        connection, user_id=user_id, exploration_id=exploration_id
    )
    interaction_id = _insert_interaction(
        connection,
        user_id=user_id,
        session_id=session_id,
        objective_id=objective_id,
    )
    return {
        "user_id": user_id,
        "entity_id": entity_id,
        "objective_id": objective_id,
        "exploration_id": exploration_id,
        "session_id": session_id,
        "interaction_id": interaction_id,
    }


def test_session_requires_exploration_owner_and_preserved_version(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into assessment_sessions
          (user_id, exploration_id, entity_version, strategy_version,
           confidence_before, status, started_at)
        values
          (:user_id, :exploration_id, :entity_version, 'strategy-v1',
           'MAIN_IDEA', 'ACTIVE', now())
        """
    )

    _assert_constraint(
        migrated_connection,
        "fk_assessment_sessions_exploration_owner_version",
        statement,
        {
            "user_id": other_user_id,
            "exploration_id": graph["exploration_id"],
            "entity_version": 1,
        },
    )
    _assert_constraint(
        migrated_connection,
        "fk_assessment_sessions_exploration_owner_version",
        statement,
        {
            "user_id": graph["user_id"],
            "exploration_id": graph["exploration_id"],
            "entity_version": 2,
        },
    )


@pytest.mark.parametrize(
    ("column", "value", "expected"),
    [
        (
            "confidence_before",
            "EXPERT",
            "ck_assessment_sessions_confidence_before",
        ),
        ("status", "PAUSED", "ck_assessment_sessions_status"),
    ],
)
def test_session_rejects_unfrozen_values(
    migrated_connection, column, value, expected
):
    graph = _valid_graph(migrated_connection)
    statement = text(
        f"""
        insert into assessment_sessions
          (user_id, exploration_id, entity_version, strategy_version,
           confidence_before, status, started_at)
        values
          (:user_id, :exploration_id, 1, 'strategy-v1',
           :confidence_before, :status, now())
        """
    )
    parameters = {
        "user_id": graph["user_id"],
        "exploration_id": graph["exploration_id"],
        "confidence_before": "MAIN_IDEA",
        "status": "ACTIVE",
    }
    parameters[column] = value

    _assert_constraint(migrated_connection, expected, statement, parameters)


@pytest.mark.parametrize(
    ("status", "completed_offset"),
    [
        ("ACTIVE", 1),
        ("WAITING_FOR_EVALUATION", 1),
        ("COMPLETED", None),
        ("ABANDONED", None),
        ("COMPLETED", -1),
    ],
)
def test_session_lifecycle_timestamps_are_coherent(
    migrated_connection, status, completed_offset
):
    graph = _valid_graph(migrated_connection)
    started_at = datetime.now(UTC)
    completed_at = (
        None
        if completed_offset is None
        else started_at + timedelta(seconds=completed_offset)
    )

    with pytest.raises(IntegrityError) as error, migrated_connection.begin_nested():
        _insert_session(
            migrated_connection,
            user_id=graph["user_id"],
            exploration_id=graph["exploration_id"],
            status=status,
            started_at=started_at,
            completed_at=completed_at,
        )

    assert (
        error.value.orig.diag.constraint_name
        == "ck_assessment_sessions_lifecycle"
    )


def test_interaction_requires_owned_session_existing_objective_and_positive_sequence(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    statement = text(
        """
        insert into assessment_interactions
          (user_id, assessment_session_id, objective_id, interaction_type,
           prompt_definition, rubric_version, sequence)
        values
          (:user_id, :session_id, :objective_id, 'FREE_RESPONSE',
           '{"prompt":"Explain it"}'::jsonb, 'rubric-v1', :sequence)
        """
    )

    _assert_constraint(
        migrated_connection,
        "fk_assessment_interactions_session_owner",
        statement,
        {
            "user_id": other_user_id,
            "session_id": graph["session_id"],
            "objective_id": graph["objective_id"],
            "sequence": 2,
        },
    )
    _assert_constraint(
        migrated_connection,
        "fk_assessment_interactions_objective_id_learning_objectives",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "objective_id": uuid4(),
            "sequence": 2,
        },
    )
    _assert_constraint(
        migrated_connection,
        "ck_assessment_interactions_sequence",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "objective_id": graph["objective_id"],
            "sequence": 0,
        },
    )
    _assert_constraint(
        migrated_connection,
        "uq_assessment_interactions_session_sequence",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "objective_id": graph["objective_id"],
            "sequence": 1,
        },
    )


def test_interaction_objective_matches_assessed_entity_and_version(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    _, other_objective_id = _insert_entity_and_objective(migrated_connection)
    migrated_connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 2, 'Second version', 'Summary',
               array['CONCEPTUAL'], 'NORMAL')
            """
        ),
        {"entity_id": graph["entity_id"]},
    )
    version_two_objective_id = migrated_connection.execute(
        text(
            """
            insert into learning_objectives
              (entity_id, entity_version, objective_type, description, importance)
            values
              (:entity_id, 2, 'EXPLANATION', 'Explain version two', 0.8)
            returning id
            """
        ),
        {"entity_id": graph["entity_id"]},
    ).scalar_one()

    statement = text(
        """
        insert into assessment_interactions
          (user_id, assessment_session_id, objective_id, interaction_type,
           prompt_definition, rubric_version, sequence)
        values
          (:user_id, :session_id, :objective_id, 'FREE_RESPONSE',
           '{"prompt":"Explain it"}'::jsonb, 'rubric-v1', :sequence)
        """
    )
    for objective_id, sequence in [
        (other_objective_id, 2),
        (version_two_objective_id, 3),
    ]:
        _assert_constraint(
            migrated_connection,
            "ck_assessment_interactions_objective_version",
            statement,
            {
                "user_id": graph["user_id"],
                "session_id": graph["session_id"],
                "objective_id": objective_id,
                "sequence": sequence,
            },
        )


def test_support_request_enforces_level_and_interaction_ownership(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id, objective_id = _insert_entity_and_objective(migrated_connection)
    other_exploration_id = _insert_exploration(
        migrated_connection, user_id=graph["user_id"], entity_id=entity_id
    )
    other_session_id = _insert_session(
        migrated_connection,
        user_id=graph["user_id"],
        exploration_id=other_exploration_id,
    )
    _insert_interaction(
        migrated_connection,
        user_id=graph["user_id"],
        session_id=other_session_id,
        objective_id=objective_id,
    )
    statement = text(
        """
        insert into assessment_support_requests
          (user_id, assessment_session_id, interaction_id, requested_level,
           delivered_content, support_source)
        values
          (:user_id, :session_id, :interaction_id, :requested_level,
           '{"text":"Consider the definition"}'::jsonb, 'GENERATED')
        """
    )

    _assert_constraint(
        migrated_connection,
        "ck_assessment_support_requests_requested_level",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
            "requested_level": "ANSWER",
        },
    )
    for user_id, session_id in [
        (other_user_id, graph["session_id"]),
        (graph["user_id"], other_session_id),
    ]:
        _assert_constraint(
            migrated_connection,
            "fk_assessment_support_requests_interaction_owner_session",
            statement,
            {
                "user_id": user_id,
                "session_id": session_id,
                "interaction_id": graph["interaction_id"],
                "requested_level": "SMALL_NUDGE",
            },
        )
    _assert_constraint(
        migrated_connection,
        "fk_assessment_support_requests_interaction_owner_session",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": uuid4(),
            "requested_level": "SMALL_NUDGE",
        },
    )


def test_response_enforces_ownership_uniqueness_and_support_level(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    other_user_id = _insert_user(migrated_connection)
    entity_id, objective_id = _insert_entity_and_objective(migrated_connection)
    other_exploration_id = _insert_exploration(
        migrated_connection, user_id=graph["user_id"], entity_id=entity_id
    )
    other_session_id = _insert_session(
        migrated_connection,
        user_id=graph["user_id"],
        exploration_id=other_exploration_id,
    )
    _insert_interaction(
        migrated_connection,
        user_id=graph["user_id"],
        session_id=other_session_id,
        objective_id=objective_id,
    )
    statement = text(
        """
        insert into assessment_responses
          (user_id, assessment_session_id, interaction_id, response_type,
           response_content, support_used)
        values
          (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
           '{"text":"My answer"}'::jsonb, :support_used)
        """
    )

    _assert_constraint(
        migrated_connection,
        "fk_assessment_responses_interaction_owner_session",
        statement,
        {
            "user_id": other_user_id,
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
            "support_used": None,
        },
    )
    _assert_constraint(
        migrated_connection,
        "ck_assessment_responses_support_used",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
            "support_used": "ANSWER",
        },
    )
    for session_id, interaction_id in [
        (other_session_id, graph["interaction_id"]),
        (graph["session_id"], uuid4()),
    ]:
        _assert_constraint(
            migrated_connection,
            "fk_assessment_responses_interaction_owner_session",
            statement,
            {
                "user_id": graph["user_id"],
                "session_id": session_id,
                "interaction_id": interaction_id,
                "support_used": None,
            },
        )
    migrated_connection.execute(
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
            "support_used": "STRONG_HINT",
        },
    )
    _assert_constraint(
        migrated_connection,
        "uq_assessment_responses_interaction_id",
        statement,
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
            "support_used": None,
        },
    )


def test_response_update_and_nonmaintenance_delete_are_rejected_and_retained(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    response_id = migrated_connection.execute(
        text(
            """
            insert into assessment_responses
              (user_id, assessment_session_id, interaction_id, response_type,
               response_content)
            values
              (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
               '{"text":"Historical answer"}'::jsonb)
            returning id
            """
        ),
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
        },
    ).scalar_one()

    with pytest.raises(DBAPIError) as update_error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                update assessment_responses
                set response_content = '{"text":"Rewritten"}'::jsonb
                where id = :id
                """
            ),
            {"id": response_id},
        )
    assert update_error.value.orig.sqlstate == "55000"
    assert "assessment responses are immutable" in str(update_error.value.orig)

    with pytest.raises(DBAPIError) as delete_error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("delete from assessment_responses where id = :id"),
            {"id": response_id},
        )
    assert delete_error.value.orig.sqlstate == "55000"
    assert "app_maintenance" in str(delete_error.value.orig)

    assert migrated_connection.execute(
        text("select response_content ->> 'text' from assessment_responses where id = :id"),
        {"id": response_id},
    ).scalar_one() == "Historical answer"

    with pytest.raises(DBAPIError) as cascade_error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("delete from explorations where id = :id"),
            {"id": graph["exploration_id"]},
        )
    assert cascade_error.value.orig.sqlstate == "55000"
    assert (
        cascade_error.value.orig.diag.constraint_name
        == "ck_assessment_interactions_historical_prompt"
    )


def test_support_request_is_persisted_before_response_support_snapshot(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    support_id = migrated_connection.execute(
        text(
            """
            insert into assessment_support_requests
              (user_id, assessment_session_id, interaction_id, requested_level,
               delivered_content, support_source)
            values
              (:user_id, :session_id, :interaction_id, 'STRONG_HINT',
               '{"text":"Focus on causality"}'::jsonb, 'GENERATED')
            returning id
            """
        ),
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
        },
    ).scalar_one()
    response_id = migrated_connection.execute(
        text(
            """
            insert into assessment_responses
              (user_id, assessment_session_id, interaction_id, response_type,
               response_content, support_used)
            values
              (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
               '{"text":"Supported answer"}'::jsonb, 'STRONG_HINT')
            returning id
            """
        ),
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
        },
    ).scalar_one()

    assert migrated_connection.execute(
        text(
            """
            select r.support_used, s.requested_level
            from assessment_responses r
            join assessment_support_requests s
              on s.id = :support_id
             and s.interaction_id = r.interaction_id
            where r.id = :response_id
            """
        ),
        {"support_id": support_id, "response_id": response_id},
    ).one() == ("STRONG_HINT", "STRONG_HINT")


def test_answered_interaction_and_parent_version_snapshot_cannot_be_rewritten(
    migrated_connection,
):
    graph = _valid_graph(migrated_connection)
    migrated_connection.execute(
        text(
            """
            insert into assessment_responses
              (user_id, assessment_session_id, interaction_id, response_type,
               response_content)
            values
              (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
               '{"text":"Historical answer"}'::jsonb)
            """
        ),
        {
            "user_id": graph["user_id"],
            "session_id": graph["session_id"],
            "interaction_id": graph["interaction_id"],
        },
    )
    other_entity_id, other_objective_id = _insert_entity_and_objective(
        migrated_connection
    )

    for statement, parameters, expected in [
        (
            text(
                "update assessment_interactions set prompt_definition = "
                "'{\"prompt\":\"Rewritten\"}'::jsonb where id = :id"
            ),
            {"id": graph["interaction_id"]},
            "ck_assessment_interactions_historical_prompt",
        ),
        (
            text(
                "update assessment_interactions set objective_id = :objective_id "
                "where id = :id"
            ),
            {
                "id": graph["interaction_id"],
                "objective_id": other_objective_id,
            },
            "ck_assessment_interactions_historical_prompt",
        ),
        (
            text(
                "update learning_objectives set entity_id = :entity_id "
                "where id = :id"
            ),
            {"id": graph["objective_id"], "entity_id": other_entity_id},
            "ck_learning_objectives_assessment_history",
        ),
        (
            text(
                "update explorations set entity_id = :entity_id where id = :id"
            ),
            {"id": graph["exploration_id"], "entity_id": other_entity_id},
            "ck_explorations_assessment_history",
        ),
    ]:
        with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
            migrated_connection.execute(statement, parameters)
        assert error.value.orig.diag.constraint_name == expected


def test_unanswered_interaction_allows_parent_cascade_delete(migrated_connection):
    graph = _valid_graph(migrated_connection)

    result = migrated_connection.execute(
        text("delete from explorations where id = :id"),
        {"id": graph["exploration_id"]},
    )

    assert result.rowcount == 1
    assert migrated_connection.execute(
        text("select count(*) from assessment_interactions where id = :id"),
        {"id": graph["interaction_id"]},
    ).scalar_one() == 0


@pytest.mark.parametrize("mutated_parent", ["objective", "exploration"])
def test_response_revalidates_entity_version_after_pre_response_parent_change(
    migrated_connection, mutated_parent
):
    graph = _valid_graph(migrated_connection)
    other_entity_id, _ = _insert_entity_and_objective(migrated_connection)
    if mutated_parent == "objective":
        migrated_connection.execute(
            text(
                "update learning_objectives set entity_id = :entity_id "
                "where id = :id"
            ),
            {"entity_id": other_entity_id, "id": graph["objective_id"]},
        )
    else:
        migrated_connection.execute(
            text("update explorations set entity_id = :entity_id where id = :id"),
            {"entity_id": other_entity_id, "id": graph["exploration_id"]},
        )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text(
                """
                insert into assessment_responses
                  (user_id, assessment_session_id, interaction_id, response_type,
                   response_content)
                values
                  (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
                   '{"text":"Would freeze inconsistent history"}'::jsonb)
                """
            ),
            {
                "user_id": graph["user_id"],
                "session_id": graph["session_id"],
                "interaction_id": graph["interaction_id"],
            },
        )

    assert (
        error.value.orig.diag.constraint_name
        == "ck_assessment_responses_objective_version"
    )


def test_response_insert_serializes_with_objective_version_change(migrated_engine):
    with migrated_engine.begin() as setup_connection:
        graph = _valid_graph(setup_connection)
        other_entity_id, _ = _insert_entity_and_objective(setup_connection)

    worker_pid: Queue[int] = Queue()

    def insert_response() -> None:
        with migrated_engine.begin() as worker_connection:
            worker_pid.put(
                worker_connection.execute(text("select pg_backend_pid()"))
                .scalar_one()
            )
            worker_connection.execute(
                text(
                    """
                    insert into assessment_responses
                      (user_id, assessment_session_id, interaction_id,
                       response_type, response_content)
                    values
                      (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
                       '{"text":"Concurrent response"}'::jsonb)
                    """
                ),
                {
                    "user_id": graph["user_id"],
                    "session_id": graph["session_id"],
                    "interaction_id": graph["interaction_id"],
                },
            )

    parent_connection = migrated_engine.connect()
    parent_transaction = parent_connection.begin()
    try:
        parent_connection.execute(
            text(
                "update learning_objectives set entity_id = :entity_id "
                "where id = :id"
            ),
            {"entity_id": other_entity_id, "id": graph["objective_id"]},
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            response_insert = executor.submit(insert_response)
            pid = worker_pid.get(timeout=5)
            deadline = monotonic() + 5
            blocked = False
            with migrated_engine.connect() as observer:
                while monotonic() < deadline:
                    blocked = observer.execute(
                        text("select cardinality(pg_blocking_pids(:pid)) > 0"),
                        {"pid": pid},
                    ).scalar_one()
                    if blocked:
                        break
                    if response_insert.done():
                        break
                    sleep(0.01)

            assert blocked, "response insert did not lock the objective snapshot"
            parent_transaction.commit()
            with pytest.raises(DBAPIError) as error:
                response_insert.result(timeout=5)
            assert (
                error.value.orig.diag.constraint_name
                == "ck_assessment_responses_objective_version"
            )
    finally:
        if parent_transaction.is_active:
            parent_transaction.rollback()
        parent_connection.close()
