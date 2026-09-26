"""Focused 0017 schema and concurrent expired-key generation checks."""
from __future__ import annotations

import asyncio
from uuid import uuid4

import pytest
from alembic import command
from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.idempotency import reserve_idempotent_command
from app.db.session import set_current_user
from conftest import make_alembic_config


def _user(engine):
    with engine.begin() as connection:
        return connection.scalar(text("""
            insert into app_users (auth_provider, auth_subject)
            values ('SUPABASE', :subject) returning id
        """), {"subject": str(uuid4())})


def _expired(engine, user_id, key):
    with engine.begin() as connection:
        return connection.scalar(text("""
            insert into idempotency_records
              (user_id, idempotency_key, command_name, request_fingerprint,
               result_type, result_id, response_status, response_body, expires_at)
            values (:user, :key, 'old.command', 'old-fingerprint', 'OLD',
                    :result_id, 200, '{"old": true}'::jsonb,
                    now() - interval '1 second')
            returning id
        """), {"user": user_id, "key": key, "result_id": uuid4()})


def _cleanup(engine, user_id):
    with engine.begin() as connection:
        connection.execute(text("delete from app_users where id = :id"), {"id": user_id})


def test_expired_key_race_creates_one_new_active_generation(migrated_engine, database_url):
    user_id, key = _user(migrated_engine), f"race-{uuid4()}"
    old_id = _expired(migrated_engine, user_id, key)

    async def run():
        engine = create_async_engine(database_url)

        @event.listens_for(engine.sync_engine, "connect")
        def role(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("set role app_backend")
            cursor.close()
            dbapi_connection.commit()

        factory = async_sessionmaker(engine, expire_on_commit=False)

        async def reserve():
            async with factory() as session, session.begin():
                await set_current_user(session, user_id)
                return await reserve_idempotent_command(
                    session, user_id=user_id, idempotency_key=key,
                    command_name="new.command", fingerprint="new-fingerprint",
                )

        try:
            return await asyncio.gather(reserve(), reserve())
        finally:
            await engine.dispose()

    try:
        first, second = asyncio.run(run())
        assert {first.replay, second.replay} == {False, True}
        assert first.record_id == second.record_id != old_id
        with migrated_engine.connect() as connection:
            rows = connection.execute(text("""
                select id, command_name, request_fingerprint, result_type,
                       response_body, retired_at
                  from idempotency_records
                 where user_id = :user and idempotency_key = :key
            """), {"user": user_id, "key": key}).all()
            assert len(rows) == 2
            assert len([row for row in rows if row.retired_at is None]) == 1
            historical = next(row for row in rows if row.id == old_id)
            assert historical.command_name == "old.command"
            assert historical.request_fingerprint == "old-fingerprint"
            assert historical.result_type == "OLD"
            assert historical.response_body == {"old": True}
    finally:
        _cleanup(migrated_engine, user_id)


def test_0017_guarded_downgrade_preserves_duplicate_history(migrated_engine, database_url):
    user_id, key = _user(migrated_engine), f"downgrade-{uuid4()}"
    _expired(migrated_engine, user_id, key)
    try:
        with migrated_engine.begin() as connection:
            connection.execute(text("""
                update idempotency_records set retired_at = now()
                 where user_id = :user and idempotency_key = :key
            """), {"user": user_id, "key": key})
            connection.execute(text("""
                insert into idempotency_records
                  (user_id, idempotency_key, command_name,
                   request_fingerprint, expires_at)
                values (:user, :key, 'new.command', 'new-fingerprint',
                        now() + interval '1 day')
            """), {"user": user_id, "key": key})
        with pytest.raises(RuntimeError, match="historical generations"):
            command.downgrade(make_alembic_config(database_url),
                              "0016_recommendation_reason")
        # The failed 0017 downgrade rolls back the entire migration transaction,
        # including the preceding 0018 downgrade, so the current head survives.
        with migrated_engine.connect() as connection:
            assert connection.scalar(text("select version_num from alembic_version")) == (
                "0018_exploration_delivery"
            )
            assert connection.scalar(text("""
                select count(*) from idempotency_records
                 where user_id = :user and idempotency_key = :key
            """), {"user": user_id, "key": key}) == 2
            assert connection.scalar(text("""
                select count(*) from pg_indexes
                 where schemaname = 'public'
                   and indexname = 'uq_idempotency_records_active_user_key'
            """)) == 1
    finally:
        _cleanup(migrated_engine, user_id)
