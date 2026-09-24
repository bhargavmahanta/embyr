"""Behavioral upgrade/downgrade proof for nullable recommendation reasons."""
from __future__ import annotations

from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import create_engine, text

from conftest import make_alembic_config, provision_runtime_roles

BEFORE = "0015_recommendation_retrieval"
AFTER = "0016_recommendation_reason"


def _nullable(connection):
    return connection.execute(text("""
        select is_nullable from information_schema.columns
        where table_schema = 'public' and table_name = 'recommendations'
          and column_name = 'reason_code'
    """)).scalar_one()


def _version(connection):
    return connection.execute(text("select version_num from alembic_version")).scalar_one()


def _insert_recommendation(connection, user_id, entity_id, reason_code):
    return connection.execute(text("""
        insert into recommendations
          (user_id, entity_id, entity_version, mode, distance_band,
           ranking_model_version, score_components, reason_code,
           presentation_version, presentation, presented_at)
        values
          (:user_id, :entity_id, 1, 'EXPLORE', 'ADJACENT',
           'recommendation-profile/v1', '{}'::jsonb, :reason_code,
           'recommendation-copy/v1', '{}'::jsonb, now())
        returning id
    """), {
        "user_id": user_id, "entity_id": entity_id, "reason_code": reason_code,
    }).scalar_one()


def test_0016_nullable_upgrade_and_safe_downgrades(database_url):
    config = make_alembic_config(database_url)
    engine = create_engine(database_url)
    provision_runtime_roles(engine)
    try:
        command.upgrade(config, BEFORE)
        with engine.begin() as connection:
            user_id = connection.execute(text("""
                insert into app_users (auth_provider, auth_subject)
                values ('test', :subject) returning id
            """), {"subject": str(uuid4())}).scalar_one()
            entity_id = connection.execute(text("""
                insert into learning_entities (canonical_key, entity_type, status)
                values (:key, 'TOPIC', 'REVIEWED') returning id
            """), {"key": f"reason-migration-{uuid4()}"}).scalar_one()
            connection.execute(text("""
                insert into learning_entity_versions
                  (entity_id, version, title, summary, knowledge_types, scope)
                values (:entity_id, 1, 'Title', 'Summary',
                        array['CONCEPTUAL'], 'NORMAL')
            """), {"entity_id": entity_id})
            connection.execute(text("""
                update learning_entities set current_version = 1 where id = :id
            """), {"id": entity_id})
            _insert_recommendation(connection, user_id, entity_id, "GOOD_DIFFICULTY_FIT")
            assert _nullable(connection) == "NO"

        command.upgrade(config, AFTER)
        with engine.begin() as connection:
            assert _version(connection) == AFTER
            assert _nullable(connection) == "YES"
            first_null_id = _insert_recommendation(connection, user_id, entity_id, None)
            assert connection.execute(text("""
                select reason_code from recommendations where id = :id
            """), {"id": first_null_id}).scalar_one_or_none() is None

        # Clean downgrade: remove only the disposable test's NULL row first.
        with engine.begin() as connection:
            connection.execute(text("""
                delete from recommendations where id = :id
            """), {"id": first_null_id})
        command.downgrade(config, BEFORE)
        with engine.connect() as connection:
            assert _version(connection) == BEFORE
            assert _nullable(connection) == "NO"

        command.upgrade(config, AFTER)
        with engine.begin() as connection:
            guarded_null_id = _insert_recommendation(connection, user_id, entity_id, None)
        with pytest.raises(RuntimeError, match="cannot restore non-null reason_code"):
            command.downgrade(config, BEFORE)
        with engine.connect() as connection:
            assert _version(connection) == AFTER
            assert _nullable(connection) == "YES"
            assert connection.execute(text("""
                select count(*) from recommendations
                where id = :id and reason_code is null
            """), {"id": guarded_null_id}).scalar_one() == 1
    finally:
        with engine.begin() as connection:
            connection.execute(text("""
                delete from recommendations where reason_code is null
            """))
        command.downgrade(config, "base")
        engine.dispose()
