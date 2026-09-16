from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
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


def _assert_db_constraint(connection, expected: str, statement, parameters) -> None:
    with pytest.raises(DBAPIError) as error, connection.begin_nested():
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


def _insert_entity_objective(connection):
    entity_id = connection.execute(
        text(
            """
            insert into learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED')
            returning id
            """
        ),
        {"key": f"evaluation-{uuid4()}"},
    ).scalar_one()
    connection.execute(
        text(
            """
            insert into learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope)
            values
              (:entity_id, 1, 'Evaluation topic', 'Summary',
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
            values (:entity_id, 1, 'EXPLANATION', 'Explain it', 0.8)
            returning id
            """
        ),
        {"entity_id": entity_id},
    ).scalar_one()
    return entity_id, objective_id


def _insert_response(connection, *, user_id, entity_id, objective_id):
    exploration_id = connection.execute(
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
    session_id = connection.execute(
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
    interaction_id = connection.execute(
        text(
            """
            insert into assessment_interactions
              (user_id, assessment_session_id, objective_id, interaction_type,
               prompt_definition, rubric_version, sequence)
            values
              (:user_id, :session_id, :objective_id, 'FREE_RESPONSE',
               '{"prompt":"Explain it"}'::jsonb, 'rubric-v1', 1)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "session_id": session_id,
            "objective_id": objective_id,
        },
    ).scalar_one()
    return connection.execute(
        text(
            """
            insert into assessment_responses
              (user_id, assessment_session_id, interaction_id, response_type,
               response_content)
            values
              (:user_id, :session_id, :interaction_id, 'FREE_TEXT',
               '{"text":"A historical response"}'::jsonb)
            returning id
            """
        ),
        {
            "user_id": user_id,
            "session_id": session_id,
            "interaction_id": interaction_id,
        },
    ).scalar_one()


def _response_graph(connection):
    user_id = _insert_user(connection)
    entity_id, objective_id = _insert_entity_objective(connection)
    response_id = _insert_response(
        connection,
        user_id=user_id,
        entity_id=entity_id,
        objective_id=objective_id,
    )
    return {
        "user_id": user_id,
        "entity_id": entity_id,
        "objective_id": objective_id,
        "response_id": response_id,
    }


EVALUATION_INSERT = text(
    """
    insert into evaluation_runs
      (id, user_id, response_id, evaluator_type, evaluator_version,
       rubric_version, result, confidence, feedback, status, supersedes_id)
    values
      (:id, :user_id, :response_id, 'DETERMINISTIC', 'evaluator-v1',
       'rubric-v1', :result, :confidence, :feedback, :status, :supersedes_id)
    returning id
    """
)


def _insert_evaluation(
    connection,
    *,
    user_id,
    response_id,
    status: str = "SUCCEEDED",
    result: str | None = "SUPPORTED",
    confidence: float | None = 0.9,
    feedback: str | None = "Supported by the response.",
    supersedes_id=None,
    evaluation_id=None,
):
    return connection.execute(
        EVALUATION_INSERT,
        {
            "id": evaluation_id or uuid4(),
            "user_id": user_id,
            "response_id": response_id,
            "result": result,
            "confidence": confidence,
            "feedback": feedback,
            "status": status,
            "supersedes_id": supersedes_id,
        },
    ).scalar_one()


EVIDENCE_INSERT = text(
    """
    insert into learning_evidence
      (user_id, entity_id, objective_id, source_type, source_id,
       evaluation_run_id, evidence_type, evidence_strength, support_level,
       evaluation_confidence, status)
    values
      (:user_id, :entity_id, :objective_id, :source_type, :source_id,
       :evaluation_run_id, :evidence_type, :evidence_strength, :support_level,
       :evaluation_confidence, :status)
    returning id
    """
)


def _evidence_parameters(graph, evaluation_id, **overrides):
    parameters = {
        "user_id": graph["user_id"],
        "entity_id": graph["entity_id"],
        "objective_id": graph["objective_id"],
        "source_type": "ASSESSMENT_RESPONSE",
        "source_id": graph["response_id"],
        "evaluation_run_id": evaluation_id,
        "evidence_type": "EXPLANATION",
        "evidence_strength": "STRONG",
        "support_level": None,
        "evaluation_confidence": 0.9,
        "status": "ACTIVE",
    }
    parameters.update(overrides)
    return parameters


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"status": "ACTIVE"}, "ck_evaluation_runs_status"),
        ({"result": "MASTERED"}, "ck_evaluation_runs_result"),
        (
            {
                "status": "PENDING",
                "result": "SUPPORTED",
                "confidence": 0.9,
                "feedback": "Premature result",
            },
            "ck_evaluation_runs_payload",
        ),
        ({"feedback": None}, "ck_evaluation_runs_payload"),
        ({"confidence": 1.1}, "ck_evaluation_runs_confidence"),
    ],
)
def test_evaluation_status_result_and_confidence_are_coherent(
    migrated_connection, overrides, expected
):
    graph = _response_graph(migrated_connection)
    parameters = {
        "id": uuid4(),
        "user_id": graph["user_id"],
        "response_id": graph["response_id"],
        "result": "SUPPORTED",
        "confidence": 0.9,
        "feedback": "Supported by the response.",
        "status": "SUCCEEDED",
        "supersedes_id": None,
    }
    parameters.update(overrides)

    _assert_constraint(migrated_connection, expected, EVALUATION_INSERT, parameters)


def test_only_one_current_successful_evaluation_exists_per_response(
    migrated_connection,
):
    graph = _response_graph(migrated_connection)
    _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )

    _assert_constraint(
        migrated_connection,
        "uq_evaluation_runs_active_response",
        EVALUATION_INSERT,
        {
            "id": uuid4(),
            "user_id": graph["user_id"],
            "response_id": graph["response_id"],
            "result": "PARTIAL",
            "confidence": 0.6,
            "feedback": "Partially supported.",
            "status": "SUCCEEDED",
            "supersedes_id": None,
        },
    )


def test_evaluation_requires_the_response_owner(migrated_connection):
    graph = _response_graph(migrated_connection)
    other_user_id = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "fk_evaluation_runs_response_owner",
        EVALUATION_INSERT,
        {
            "id": uuid4(),
            "user_id": other_user_id,
            "response_id": graph["response_id"],
            "result": "SUPPORTED",
            "confidence": 0.9,
            "feedback": "Wrong owner",
            "status": "SUCCEEDED",
            "supersedes_id": None,
        },
    )

def test_supersession_rejects_self_cross_user_and_cross_response_links(
    migrated_connection,
):
    first = _response_graph(migrated_connection)
    same_user_entity, same_user_objective = _insert_entity_objective(
        migrated_connection
    )
    second_response = _insert_response(
        migrated_connection,
        user_id=first["user_id"],
        entity_id=same_user_entity,
        objective_id=same_user_objective,
    )
    other = _response_graph(migrated_connection)

    self_id = uuid4()
    _assert_constraint(
        migrated_connection,
        "ck_evaluation_runs_not_self_superseding",
        EVALUATION_INSERT,
        {
            "id": self_id,
            "user_id": first["user_id"],
            "response_id": first["response_id"],
            "result": "SUPPORTED",
            "confidence": 0.9,
            "feedback": "Self link",
            "status": "SUPERSEDED",
            "supersedes_id": self_id,
        },
    )

    other_evaluation = _insert_evaluation(
        migrated_connection,
        user_id=other["user_id"],
        response_id=other["response_id"],
        status="SUPERSEDED",
    )
    _assert_constraint(
        migrated_connection,
        "fk_evaluation_runs_superseded_owner_response",
        EVALUATION_INSERT,
        {
            "id": uuid4(),
            "user_id": first["user_id"],
            "response_id": first["response_id"],
            "result": "SUPPORTED",
            "confidence": 0.9,
            "feedback": "Cross-user link",
            "status": "SUPERSEDED",
            "supersedes_id": other_evaluation,
        },
    )

    second_evaluation = _insert_evaluation(
        migrated_connection,
        user_id=first["user_id"],
        response_id=second_response,
        status="SUPERSEDED",
    )
    _assert_constraint(
        migrated_connection,
        "fk_evaluation_runs_superseded_owner_response",
        EVALUATION_INSERT,
        {
            "id": uuid4(),
            "user_id": first["user_id"],
            "response_id": first["response_id"],
            "result": "SUPPORTED",
            "confidence": 0.9,
            "feedback": "Cross-response link",
            "status": "SUPERSEDED",
            "supersedes_id": second_evaluation,
        },
    )


def test_a_superseded_run_has_at_most_one_replacement(migrated_connection):
    graph = _response_graph(migrated_connection)
    old_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
        status="SUPERSEDED",
    )
    _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
        status="REVOKED",
        supersedes_id=old_id,
    )

    _assert_constraint(
        migrated_connection,
        "uq_evaluation_runs_supersedes_id",
        EVALUATION_INSERT,
        {
            "id": uuid4(),
            "user_id": graph["user_id"],
            "response_id": graph["response_id"],
            "result": "PARTIAL",
            "confidence": 0.6,
            "feedback": "Second replacement",
            "status": "REVOKED",
            "supersedes_id": old_id,
        },
    )


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"evidence_type": "MASTERY"}, "ck_learning_evidence_type"),
        ({"evidence_strength": "CERTAIN"}, "ck_learning_evidence_strength"),
        ({"support_level": "ANSWER"}, "ck_learning_evidence_support_level"),
        ({"evaluation_confidence": -0.1}, "ck_learning_evidence_confidence"),
        ({"status": "DELETED"}, "ck_learning_evidence_status"),
    ],
)
def test_evidence_rejects_unfrozen_or_out_of_range_values(
    migrated_connection, overrides, expected
):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )

    _assert_constraint(
        migrated_connection,
        expected,
        EVIDENCE_INSERT,
        _evidence_parameters(graph, evaluation_id, **overrides),
    )


def test_evidence_requires_matching_entity_objective_and_evaluation_source(
    migrated_connection,
):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    other_entity, other_objective = _insert_entity_objective(migrated_connection)
    other_user = _insert_user(migrated_connection)

    _assert_constraint(
        migrated_connection,
        "fk_learning_evidence_objective_entity",
        EVIDENCE_INSERT,
        _evidence_parameters(
            graph,
            None,
            entity_id=other_entity,
            objective_id=graph["objective_id"],
            source_type="REFLECTION",
            evaluation_confidence=None,
        ),
    )
    _assert_constraint(
        migrated_connection,
        "fk_learning_evidence_evaluation_owner_source",
        EVIDENCE_INSERT,
        _evidence_parameters(graph, evaluation_id, user_id=other_user),
    )
    _assert_constraint(
        migrated_connection,
        "fk_learning_evidence_evaluation_owner_source",
        EVIDENCE_INSERT,
        _evidence_parameters(graph, evaluation_id, source_id=uuid4()),
    )

    migrated_connection.execute(
        EVIDENCE_INSERT,
        _evidence_parameters(
            {
                **graph,
                "entity_id": other_entity,
                "objective_id": other_objective,
            },
            None,
            source_type="REFLECTION",
            source_id=uuid4(),
            evaluation_confidence=None,
        ),
    )


def test_assessment_evidence_requires_an_evaluation_and_matching_objective(
    migrated_connection,
):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    other_entity_id, other_objective_id = _insert_entity_objective(
        migrated_connection
    )

    _assert_constraint(
        migrated_connection,
        "ck_learning_evidence_assessment_source",
        EVIDENCE_INSERT,
        _evidence_parameters(graph, None),
    )
    _assert_constraint(
        migrated_connection,
        "ck_learning_evidence_assessment_source",
        EVIDENCE_INSERT,
        _evidence_parameters(
            graph,
            evaluation_id,
            source_type="REFLECTION",
        ),
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_learning_evidence_evaluation_objective",
        EVIDENCE_INSERT,
        _evidence_parameters(
            graph,
            evaluation_id,
            entity_id=other_entity_id,
            objective_id=other_objective_id,
        ),
    )


@pytest.mark.parametrize(
    ("evaluation_overrides", "expected"),
    [
        (
            {
                "status": "PENDING",
                "result": None,
                "confidence": None,
                "feedback": None,
            },
            "ck_learning_evidence_active_evaluation",
        ),
        (
            {
                "status": "FAILED",
                "result": None,
                "confidence": None,
                "feedback": None,
            },
            "ck_learning_evidence_active_evaluation",
        ),
        (
            {"status": "SUPERSEDED"},
            "ck_learning_evidence_active_evaluation",
        ),
        (
            {"status": "REVOKED"},
            "ck_learning_evidence_active_evaluation",
        ),
        (
            {"result": "UNCERTAIN"},
            "ck_learning_evidence_active_evaluation",
        ),
    ],
)
def test_active_evidence_requires_current_conclusive_evaluation(
    migrated_connection, evaluation_overrides, expected
):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
        **evaluation_overrides,
    )

    _assert_db_constraint(
        migrated_connection,
        expected,
        EVIDENCE_INSERT,
        _evidence_parameters(graph, evaluation_id),
    )


def test_evaluation_and_evidence_payloads_are_historical(migrated_connection):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    evidence_id = migrated_connection.execute(
        EVIDENCE_INSERT, _evidence_parameters(graph, evaluation_id)
    ).scalar_one()

    _assert_db_constraint(
        migrated_connection,
        "ck_evaluation_runs_immutable_payload",
        text("update evaluation_runs set feedback = 'Rewritten' where id = :id"),
        {"id": evaluation_id},
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_learning_evidence_immutable_payload",
        text(
            "update learning_evidence set evidence_strength = 'WEAK' where id = :id"
        ),
        {"id": evidence_id},
    )

    migrated_connection.execute(
        text("update learning_evidence set status = 'SUPERSEDED' where id = :id"),
        {"id": evidence_id},
    )
    migrated_connection.execute(
        text("update evaluation_runs set status = 'SUPERSEDED' where id = :id"),
        {"id": evaluation_id},
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_evaluation_runs_status_transition",
        text("update evaluation_runs set status = 'SUCCEEDED' where id = :id"),
        {"id": evaluation_id},
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_learning_evidence_status_transition",
        text("update learning_evidence set status = 'ACTIVE' where id = :id"),
        {"id": evidence_id},
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_evaluation_runs_maintenance_delete",
        text("delete from evaluation_runs where id = :id"),
        {"id": evaluation_id},
    )
    _assert_db_constraint(
        migrated_connection,
        "ck_learning_evidence_maintenance_delete",
        text("delete from learning_evidence where id = :id"),
        {"id": evidence_id},
    )


def test_evaluation_cannot_leave_active_evidence_when_superseded(
    migrated_connection,
):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    migrated_connection.execute(
        EVIDENCE_INSERT, _evidence_parameters(graph, evaluation_id)
    )

    with pytest.raises(DBAPIError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update evaluation_runs set status = 'SUPERSEDED' where id = :id"),
            {"id": evaluation_id},
        )
        migrated_connection.execute(text("set constraints all immediate"))

    assert (
        error.value.orig.diag.constraint_name
        == "ck_evaluation_runs_active_evidence"
    )


def test_concurrent_evidence_insert_serializes_with_evaluation_supersession(
    migrated_engine,
):
    with migrated_engine.begin() as setup_connection:
        graph = _response_graph(setup_connection)
        evaluation_id = _insert_evaluation(
            setup_connection,
            user_id=graph["user_id"],
            response_id=graph["response_id"],
        )

    worker_pid: Queue[int] = Queue()

    def supersede_evaluation() -> None:
        with migrated_engine.begin() as worker_connection:
            worker_pid.put(
                worker_connection.execute(text("select pg_backend_pid()"))
                .scalar_one()
            )
            worker_connection.execute(
                text(
                    "update evaluation_runs set status = 'SUPERSEDED' "
                    "where id = :id"
                ),
                {"id": evaluation_id},
            )

    evidence_connection = migrated_engine.connect()
    evidence_transaction = evidence_connection.begin()
    try:
        evidence_connection.execute(
            EVIDENCE_INSERT, _evidence_parameters(graph, evaluation_id)
        )
        with ThreadPoolExecutor(max_workers=1) as executor:
            supersession = executor.submit(supersede_evaluation)
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
                    if supersession.done():
                        break
                    sleep(0.01)

            assert blocked, "evaluation transition did not wait for evidence validation"
            evidence_transaction.commit()
            with pytest.raises(IntegrityError) as error:
                supersession.result(timeout=5)
            assert (
                error.value.orig.diag.constraint_name
                == "ck_evaluation_runs_active_evidence"
            )
    finally:
        if evidence_transaction.is_active:
            evidence_transaction.rollback()
        evidence_connection.close()


def test_evidence_status_changes_retain_historical_rows(migrated_connection):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    superseded_id = migrated_connection.execute(
        EVIDENCE_INSERT, _evidence_parameters(graph, evaluation_id)
    ).scalar_one()
    revoked_id = migrated_connection.execute(
        EVIDENCE_INSERT,
        _evidence_parameters(graph, evaluation_id, evidence_type="RECALL"),
    ).scalar_one()

    migrated_connection.execute(
        text("update learning_evidence set status = 'SUPERSEDED' where id = :id"),
        {"id": superseded_id},
    )
    migrated_connection.execute(
        text("update learning_evidence set status = 'REVOKED' where id = :id"),
        {"id": revoked_id},
    )

    assert migrated_connection.execute(
        text(
            """
            select array_agg(status order by status)
            from learning_evidence
            where id in (:superseded_id, :revoked_id)
            """
        ),
        {"superseded_id": superseded_id, "revoked_id": revoked_id},
    ).scalar_one() == ["REVOKED", "SUPERSEDED"]


def test_evaluation_correction_supersedes_history_and_adds_replacement_atomically(
    migrated_connection,
):
    graph = _response_graph(migrated_connection)
    old_evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    old_evidence_id = migrated_connection.execute(
        EVIDENCE_INSERT, _evidence_parameters(graph, old_evaluation_id)
    ).scalar_one()

    migrated_connection.execute(
        text("update evaluation_runs set status = 'SUPERSEDED' where id = :id"),
        {"id": old_evaluation_id},
    )
    migrated_connection.execute(
        text("update learning_evidence set status = 'SUPERSEDED' where id = :id"),
        {"id": old_evidence_id},
    )
    new_evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
        result="PARTIAL",
        confidence=0.7,
        feedback="The corrected result is partial.",
        supersedes_id=old_evaluation_id,
    )
    new_evidence_id = migrated_connection.execute(
        EVIDENCE_INSERT,
        _evidence_parameters(
            graph,
            new_evaluation_id,
            evidence_strength="MODERATE",
            evaluation_confidence=0.7,
        ),
    ).scalar_one()
    migrated_connection.execute(text("set constraints all immediate"))

    evaluation_statuses = dict(migrated_connection.execute(
        text(
            """
            select id, status from evaluation_runs
            where id in (:old_id, :new_id)
            """
        ),
        {"old_id": old_evaluation_id, "new_id": new_evaluation_id},
    ).all())
    evidence_statuses = dict(migrated_connection.execute(
        text(
            """
            select id, status from learning_evidence
            where id in (:old_id, :new_id)
            """
        ),
        {"old_id": old_evidence_id, "new_id": new_evidence_id},
    ).all())

    assert evaluation_statuses == {
        old_evaluation_id: "SUPERSEDED",
        new_evaluation_id: "SUCCEEDED",
    }
    assert evidence_statuses == {
        old_evidence_id: "SUPERSEDED",
        new_evidence_id: "ACTIVE",
    }


def test_failed_correction_rolls_back_old_statuses(migrated_connection):
    graph = _response_graph(migrated_connection)
    old_evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
    )
    old_evidence_id = migrated_connection.execute(
        EVIDENCE_INSERT, _evidence_parameters(graph, old_evaluation_id)
    ).scalar_one()

    with pytest.raises(IntegrityError) as error, migrated_connection.begin_nested():
        migrated_connection.execute(
            text("update evaluation_runs set status = 'SUPERSEDED' where id = :id"),
            {"id": old_evaluation_id},
        )
        migrated_connection.execute(
            text("update learning_evidence set status = 'SUPERSEDED' where id = :id"),
            {"id": old_evidence_id},
        )
        new_evaluation_id = _insert_evaluation(
            migrated_connection,
            user_id=graph["user_id"],
            response_id=graph["response_id"],
            supersedes_id=old_evaluation_id,
        )
        migrated_connection.execute(
            EVIDENCE_INSERT,
            _evidence_parameters(
                graph, new_evaluation_id, evidence_strength="CERTAIN"
            ),
        )

    assert error.value.orig.diag.constraint_name == "ck_learning_evidence_strength"
    assert migrated_connection.execute(
        text("select status from evaluation_runs where id = :id"),
        {"id": old_evaluation_id},
    ).scalar_one() == "SUCCEEDED"
    assert migrated_connection.execute(
        text("select status from learning_evidence where id = :id"),
        {"id": old_evidence_id},
    ).scalar_one() == "ACTIVE"


def test_successful_uncertain_evaluation_requires_no_evidence(migrated_connection):
    graph = _response_graph(migrated_connection)
    evaluation_id = _insert_evaluation(
        migrated_connection,
        user_id=graph["user_id"],
        response_id=graph["response_id"],
        result="UNCERTAIN",
        confidence=0.4,
        feedback="More information is needed.",
    )

    assert migrated_connection.execute(
        text(
            "select count(*) from learning_evidence where evaluation_run_id = :id"
        ),
        {"id": evaluation_id},
    ).scalar_one() == 0
