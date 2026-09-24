"""M4's targeted persisted entity recommendation to Exploration flow.

Uses the existing disposable pgvector/PostgreSQL migration fixture. It is kept
small so the database boundary can be run independently of the full DB suite.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.api.idempotency import (
    IdempotencyConflict, reserve_idempotent_command, store_idempotent_result,
)
from app.db.session import set_current_user
from app.recommendation.persistence import (
    load_recommendation, persist_decision, persist_selected_recommendation,
)
from app.recommendation.service import generate_recommendation
from app.recommendation.snapshot import assemble_production_snapshot


@pytest.mark.asyncio
async def test_onboarded_interest_to_recommendation_accept_exploration(migrated_engine):
    with migrated_engine.begin() as connection:
        user_id = connection.execute(text("""
            insert into public.app_users (auth_provider, auth_subject)
            values ('test', :subject) returning id
        """), {"subject": str(uuid4())}).scalar_one()
        entity_id = connection.execute(text("""
            insert into public.learning_entities (canonical_key, entity_type, status)
            values (:key, 'TOPIC', 'REVIEWED') returning id
        """), {"key": f"m4-flow-{uuid4()}"}).scalar_one()
        connection.execute(text("""
            insert into public.learning_entity_versions
              (entity_id, version, title, summary, knowledge_types, scope,
               difficulty_prior, estimated_effort_minutes)
            values (:entity_id, 1, 'Curiosity topic', 'A reviewed topic summary',
                    array['CONCEPTUAL'], 'NORMAL', 0.5, 15)
        """), {"entity_id": entity_id})
        connection.execute(text("""
            update public.learning_entities set current_version = 1 where id = :entity_id
        """), {"entity_id": entity_id})
        connection.execute(text("""
            insert into public.explicit_interest_preferences
              (user_id, entity_id, preference)
            values (:user_id, :entity_id, 'MORE')
        """), {"user_id": user_id, "entity_id": entity_id})

    async_engine = create_async_engine(str(migrated_engine.url), poolclass=NullPool)
    factory = async_sessionmaker(async_engine, expire_on_commit=False)
    try:
        snapshot = await assemble_production_snapshot(factory, user_id)
        assert snapshot.anchor_entities == ({"entity_id": str(entity_id), "entity_version": 1},)
        ranking, band = await generate_recommendation(
            snapshot, mode="EXPLORE", embedder=None,
        )
        assert ranking.selected is not None
        assert ranking.selected["target_entity_id"] == str(entity_id)
        assert band == "COMFORT"
        empty, empty_band = await generate_recommendation(
            snapshot, mode="CREATE", embedder=None,
        )
        assert empty.selected is None and empty_band is None

        async with factory() as session, session.begin():
            await set_current_user(session, user_id)
            generation = await reserve_idempotent_command(
                session, user_id=user_id, idempotency_key=f"generation-{uuid4()}",
                command_name="recommendations.next", fingerprint="generation-fingerprint",
            )
            recommendation_id = await persist_selected_recommendation(
                session, user_id=user_id, selected=ranking.selected,
                mode="EXPLORE", distance_band=band,
                ranking_model_version=ranking.profile_version,
            )
            await store_idempotent_result(
                session, user_id=user_id, record_id=generation.record_id,
                result_type="RECOMMENDATION", result_id=recommendation_id,
                response_status=200, response_body={"id": str(recommendation_id)},
            )

        async with factory() as session, session.begin():
            await set_current_user(session, user_id)
            command_key = f"decision-{uuid4()}"
            decision_command = await reserve_idempotent_command(
                session, user_id=user_id, idempotency_key=command_key,
                command_name="recommendations.decision", fingerprint="accept-fingerprint",
            )
            recommendation = await load_recommendation(
                session, user_id=user_id, recommendation_id=recommendation_id,
                for_update=True,
            )
            assert recommendation is not None
            assert await load_recommendation(
                session, user_id=uuid4(), recommendation_id=recommendation_id,
            ) is None
            outcome = await persist_decision(
                session, user_id=user_id, recommendation=recommendation,
                decision="ACCEPT", command_id=decision_command.record_id,
            )
            assert outcome.exploration_id is not None
            await store_idempotent_result(
                session, user_id=user_id, record_id=decision_command.record_id,
                result_type="EXPLORATION", result_id=outcome.exploration_id,
                response_status=200, response_body={"id": str(outcome.exploration_id)},
            )

        async with factory() as session, session.begin():
            await set_current_user(session, user_id)
            replay = await reserve_idempotent_command(
                session, user_id=user_id, idempotency_key=command_key,
                command_name="recommendations.decision", fingerprint="accept-fingerprint",
            )
            assert replay.replay and replay.response_body == {"id": str(outcome.exploration_id)}
            exploration = (await session.execute(text("""
                select recommendation_id, learning_intent, status
                  from public.explorations
                 where id = :id and user_id = :user_id
            """), {"id": outcome.exploration_id, "user_id": user_id})).one()
            assert exploration == (recommendation_id, "DIRECT_INTEREST", "ACTIVE")
            events = (await session.execute(text("""
                select event_ordinal, event_type from public.learning_events
                 where command_id = :command_id order by event_ordinal
            """), {"command_id": decision_command.record_id})).all()
            assert events == [(0, "RECOMMENDATION_ACCEPTED"), (1, "EXPLORATION_STARTED")]
            recommendation_count = await session.scalar(text("""
                select count(*) from public.recommendations where user_id = :user_id
            """), {"user_id": user_id})
            assert recommendation_count == 1

        async with factory() as session, session.begin():
            await set_current_user(session, user_id)
            with pytest.raises(IdempotencyConflict):
                await reserve_idempotent_command(
                    session, user_id=user_id, idempotency_key=command_key,
                    command_name="recommendations.decision", fingerprint="different",
                )
    finally:
        await async_engine.dispose()
        with migrated_engine.begin() as connection:
            connection.execute(text("delete from public.app_users where id = :id"), {"id": user_id})
            connection.execute(text("""
                update public.learning_entities set current_version = null where id = :id
            """), {"id": entity_id})
            connection.execute(text("delete from public.learning_entities where id = :id"), {"id": entity_id})
