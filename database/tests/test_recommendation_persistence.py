"""Actual app_backend/RLS and transaction behavior for M4-5 persistence."""
from __future__ import annotations

import asyncio
import json
import sys
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import set_current_user
from app.recommendation.persistence import (
    load_recommendation,
    persist_decision,
    persist_selected_recommendation,
)


def _run(coroutine):
    if sys.platform == "win32":
        return asyncio.run(coroutine, loop_factory=asyncio.SelectorEventLoop)
    return asyncio.run(coroutine)


def _seed(connection):
    users = [connection.execute(text("""
        insert into app_users (auth_provider, auth_subject)
        values ('test', :subject) returning id
    """), {"subject": str(uuid4())}).scalar_one() for _ in range(2)]
    entity_id = connection.execute(text("""
        insert into learning_entities (canonical_key, entity_type, status)
        values (:key, 'TOPIC', 'REVIEWED') returning id
    """), {"key": f"m4-persistence-{uuid4()}"}).scalar_one()
    connection.execute(text("""
        insert into learning_entity_versions
          (entity_id, version, title, summary, knowledge_types, scope)
        values (:entity_id, 2, 'Title', 'Summary', array['CONCEPTUAL'], 'NORMAL')
    """), {"entity_id": entity_id})
    connection.execute(text("""
        update learning_entities set current_version = 2 where id = :entity_id
    """), {"entity_id": entity_id})
    return users[0], users[1], entity_id


def _selected(entity_id: UUID, *, explanation_codes=None):
    if explanation_codes is None:
        explanation_codes = ["GOOD_DIFFICULTY_FIT", "EXPLICIT_INTEREST_MATCH"]
    return {
        "target_entity_id": str(entity_id), "target_entity_version": 2,
        "explanation_codes": explanation_codes,
        "candidate_sources": ["GRAPH", "SEMANTIC"],
        "final_rank": 3, "ordering_score": 0.42,
        "source_paths": [{"private": "must not persist"}],
        "learner_state_snapshot": {"private": "must not persist"},
        "vectors": [0.1, 0.2], "excluded_candidates": ["private"],
        "ranked_population": ["private"],
        "score_trace": {
            "component_scores": {"explicit_interest": 0.22},
            "pre_rerank_score": 0.40,
            "feature_values": {"private": "must not persist"},
            "configured_weights": {"private": "must not persist"},
        },
        "rerank_trace": {
            "diversity_adjustment": 0.02,
            "diversity_dimensions": {"private": "must not persist"},
        },
    }


async def _identity(session, user_id):
    await session.execute(text("set local role app_backend"))
    await set_current_user(session, user_id)
    assert await session.scalar(text("select current_user")) == "app_backend"


async def _command(session, user_id):
    return (await session.execute(text("""
        insert into idempotency_records
          (user_id, idempotency_key, command_name, request_fingerprint, expires_at)
        values (:user_id, :key, 'recommendation.decision', 'test-fingerprint', :expires_at)
        returning id
    """), {
        "user_id": user_id, "key": str(uuid4()),
        "expires_at": datetime.now(timezone.utc) + timedelta(days=1),
    })).scalar_one()


def test_real_recommendation_persistence_rls_and_outcomes(migrated_engine, database_url):
    with migrated_engine.begin() as connection:
        user_a, user_b, entity_id = _seed(connection)

    async def exercise():
        engine = create_async_engine(database_url)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        try:
            async with factory() as session, session.begin():
                await _identity(session, user_a)
                accepted_id = await persist_selected_recommendation(
                    session, user_id=user_a, selected=_selected(entity_id),
                    mode="EXPLORE", distance_band="ADJACENT",
                    ranking_model_version="recommendation-profile/v1",
                )
                skipped_id = await persist_selected_recommendation(
                    session, user_id=user_a,
                    selected=_selected(entity_id, explanation_codes=[]),
                    mode="REVISIT", distance_band="COMFORT",
                    ranking_model_version="recommendation-profile/v1",
                )
                rollback_id = await persist_selected_recommendation(
                    session, user_id=user_a, selected=_selected(entity_id),
                    mode="CONTINUE", distance_band="COMFORT",
                    ranking_model_version="recommendation-profile/v1",
                )
                accept_command = await _command(session, user_a)
                skip_command = await _command(session, user_a)
                rollback_command = await _command(session, user_a)

            async with factory() as session, session.begin():
                await _identity(session, user_a)
                row = await load_recommendation(
                    session, user_id=user_a, recommendation_id=accepted_id,
                )
                assert row["entity_id"] == entity_id
                assert row["entity_version"] == 2
                assert row["challenge_id"] is None
                assert row["mode"] == "EXPLORE"
                assert row["distance_band"] == "ADJACENT"
                assert row["ranking_model_version"] == "recommendation-profile/v1"
                assert row["reason_code"] == "EXPLICIT_INTEREST_MATCH"
                assert row["presentation_version"] == "recommendation-copy/v1"
                assert row["presented_at"] is not None
                assert row["presentation"] == {
                    "hook": "Something you asked to explore",
                    "reason": "You said you wanted to explore more around this.",
                    "explanation_codes": ["EXPLICIT_INTEREST_MATCH", "GOOD_DIFFICULTY_FIT"],
                    "candidate_sources": ["GRAPH", "SEMANTIC"],
                    "ranked_final_rank": 3, "shown_position": 1,
                }
                assert row["score_components"] == {
                    "component_scores": {"explicit_interest": 0.22},
                    "pre_rerank_score": 0.40,
                    "diversity_adjustment": 0.02,
                    "ordering_score": 0.42,
                }
                retained = json.dumps([row["presentation"], row["score_components"]])
                for forbidden in (
                    "feature_values", "configured_weights", "diversity_dimensions",
                    "source_paths", "learner_state_snapshot", "vectors",
                    "excluded_candidates", "ranked_population", "must not persist",
                ):
                    assert forbidden not in retained
                zero = await load_recommendation(
                    session, user_id=user_a, recommendation_id=skipped_id,
                )
                assert zero["reason_code"] is None
                assert zero["presentation"]["hook"] is None
                assert zero["presentation"]["reason"] is None

            async with factory() as session, session.begin():
                await _identity(session, user_b)
                assert await load_recommendation(
                    session, user_id=user_b, recommendation_id=accepted_id,
                ) is None
                assert await load_recommendation(
                    session, user_id=user_a, recommendation_id=accepted_id,
                ) is None  # Even a mismatched caller predicate cannot bypass RLS.
                assert (await session.execute(text("""
                    update recommendations set decision = 'SKIP', decided_at = now()
                    where id = :id returning id
                """), {"id": accepted_id})).first() is None

            async with factory() as session, session.begin():
                await _identity(session, user_a)
                accepted = await load_recommendation(
                    session, user_id=user_a, recommendation_id=accepted_id,
                    for_update=True,
                )
                outcome = await persist_decision(
                    session, user_id=user_a, recommendation=accepted,
                    decision="ACCEPT", command_id=accept_command,
                )
                assert outcome.exploration_id is not None
                skipped = await load_recommendation(
                    session, user_id=user_a, recommendation_id=skipped_id,
                    for_update=True,
                )
                skip_outcome = await persist_decision(
                    session, user_id=user_a, recommendation=skipped,
                    decision="SKIP", command_id=skip_command,
                )
                assert skip_outcome.exploration_id is None

            async with factory() as session, session.begin():
                await _identity(session, user_a)
                accepted_row = await load_recommendation(
                    session, user_id=user_a, recommendation_id=accepted_id,
                )
                skipped_row = await load_recommendation(
                    session, user_id=user_a, recommendation_id=skipped_id,
                )
                assert accepted_row["decision"] == "ACCEPT"
                assert accepted_row["decided_at"] >= accepted_row["presented_at"]
                assert skipped_row["decision"] == "SKIP"
                assert skipped_row["decided_at"] >= skipped_row["presented_at"]
                explorations = (await session.execute(text("""
                    select id, user_id, entity_id, entity_version,
                           recommendation_id, status, learning_intent
                    from explorations where recommendation_id in (:accepted, :skipped)
                """), {"accepted": accepted_id, "skipped": skipped_id})).mappings().all()
                assert len(explorations) == 1
                assert dict(explorations[0]) == {
                    "id": outcome.exploration_id, "user_id": user_a,
                    "entity_id": entity_id, "entity_version": 2,
                    "recommendation_id": accepted_id, "status": "ACTIVE",
                    "learning_intent": "DIRECT_INTEREST",
                }
                events = (await session.execute(text("""
                    select command_id, event_ordinal, event_type, entity_id,
                           exploration_id, metadata
                    from learning_events where command_id in (:accepted, :skipped)
                    order by command_id, event_ordinal
                """), {"accepted": accept_command, "skipped": skip_command})).mappings().all()
                by_command = {command_id: [dict(row) for row in events if row["command_id"] == command_id]
                              for command_id in (accept_command, skip_command)}
                assert [(event["event_ordinal"], event["event_type"])
                        for event in by_command[accept_command]] == [
                    (0, "RECOMMENDATION_ACCEPTED"), (1, "EXPLORATION_STARTED"),
                ]
                assert [(event["event_ordinal"], event["event_type"])
                        for event in by_command[skip_command]] == [(0, "RECOMMENDATION_SKIPPED")]
                for command_id, recommendation_id in (
                    (accept_command, accepted_id), (skip_command, skipped_id),
                ):
                    for event in by_command[command_id]:
                        assert event["command_id"] == command_id
                        assert event["entity_id"] == entity_id
                        assert event["metadata"] == {"recommendation_id": str(recommendation_id)}
                assert all(event["exploration_id"] == outcome.exploration_id
                           for event in by_command[accept_command])
                assert by_command[skip_command][0]["exploration_id"] is None

                # A stale pre-decision mapping bypasses the in-memory precheck;
                # the conditional UPDATE must still reject the second decision.
                with pytest.raises(ValueError, match="decision conflict"):
                    await persist_decision(
                        session, user_id=user_a, recommendation=accepted,
                        decision="SKIP", command_id=uuid4(),
                    )
                assert (await load_recommendation(
                    session, user_id=user_a, recommendation_id=accepted_id,
                ))["decision"] == "ACCEPT"

            with pytest.raises(RuntimeError, match="forced rollback"):
                async with factory() as session, session.begin():
                    await _identity(session, user_a)
                    to_rollback = await load_recommendation(
                        session, user_id=user_a, recommendation_id=rollback_id,
                        for_update=True,
                    )
                    await persist_decision(
                        session, user_id=user_a, recommendation=to_rollback,
                        decision="ACCEPT", command_id=rollback_command,
                    )
                    assert (await load_recommendation(
                        session, user_id=user_a, recommendation_id=rollback_id,
                    ))["decision"] == "ACCEPT"
                    assert (await session.scalar(text("""
                        select count(*) from explorations where recommendation_id = :id
                    """), {"id": rollback_id})) == 1
                    assert (await session.scalar(text("""
                        select count(*) from learning_events where command_id = :id
                    """), {"id": rollback_command})) == 2
                    raise RuntimeError("forced rollback")

            async with factory() as session, session.begin():
                await _identity(session, user_a)
                assert (await load_recommendation(
                    session, user_id=user_a, recommendation_id=rollback_id,
                ))["decision"] is None
                assert await session.scalar(text("""
                    select count(*) from explorations where recommendation_id = :id
                """), {"id": rollback_id}) == 0
                assert await session.scalar(text("""
                    select count(*) from learning_events where command_id = :id
                """), {"id": rollback_command}) == 0
        finally:
            await engine.dispose()

    _run(exercise())
    # The shared migrated_engine fixture downgrades to base at teardown.
    # Restore only this test's zero-code row to a non-NULL reason after the
    # durable NULL assertions, so the intentionally guarded 0016 downgrade runs.
    with migrated_engine.begin() as connection:
        connection.execute(text("""
            update recommendations set reason_code = 'GOOD_DIFFICULTY_FIT'
            where user_id = :user_id and entity_id = :entity_id
              and reason_code is null
        """), {"user_id": user_a, "entity_id": entity_id})
