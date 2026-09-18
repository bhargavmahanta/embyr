"""Transaction-local ``app.user_id`` isolation across pooled connections.

These tests run against the disposable database provided by the shared harness.
They prove the M1 identity contract at the connection layer: ``set_current_user``
writes the RLS identity with transaction-local semantics, and no identity
survives commit, rollback, or an application error, even when the same physical
connection is reused.

The engine is pinned to ``pool_size=1, max_overflow=0`` so sequential sessions
deterministically reuse one backend; ``pg_backend_pid()`` is asserted to prove
reuse rather than hoping the pool happens to hand back the same connection.
"""
from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.session import set_current_user


async def _identity(session) -> str | None:
    return await session.scalar(text("select current_setting('app.user_id', true)"))


async def _pid(session) -> int:
    return await session.scalar(text("select pg_backend_pid()"))


class _Pinned:
    """A one-connection async engine plus sessionmaker for reuse proofs."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(
            database_url, pool_size=1, max_overflow=0
        )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def dispose(self) -> None:
        await self.engine.dispose()


@pytest_asyncio.fixture
async def pinned(database_url):
    pinned = _Pinned(database_url)
    try:
        yield pinned
    finally:
        await pinned.dispose()


@pytest.mark.asyncio
async def test_identity_is_transaction_local_across_boundaries(pinned):
    user_a = uuid4()
    user_b = uuid4()

    async with pinned.factory() as session:
        async with session.begin():
            await set_current_user(session, user_a)
            assert await _identity(session) == str(user_a)
            pid_a = await _pid(session)

    # Committed transaction released the same physical connection.
    async with pinned.factory() as session:
        async with session.begin():
            assert await _pid(session) == pid_a
            assert (await _identity(session)) in (None, "")
            assert (await _identity(session)) != str(user_a)
            await set_current_user(session, user_b)
            assert await _identity(session) == str(user_b)

    # Rolled-back transaction must not leak user B.
    async with pinned.factory() as session:
        async with session.begin():
            assert await _pid(session) == pid_a
            assert (await _identity(session)) in (None, "")
            assert (await _identity(session)) != str(user_b)


@pytest.mark.asyncio
async def test_identity_absent_when_request_sets_none(pinned):
    async with pinned.factory() as session:
        async with session.begin():
            assert (await _identity(session)) in (None, "")


@pytest.mark.asyncio
async def test_application_exception_clears_identity_on_reused_connection(pinned):
    user = uuid4()
    pid = None

    with pytest.raises(RuntimeError, match="simulated request failure"):
        async with pinned.factory() as session:
            await set_current_user(session, user)
            assert await _identity(session) == str(user)
            pid = await _pid(session)
            raise RuntimeError("simulated request failure")

    async with pinned.factory() as session:
        async with session.begin():
            assert await _pid(session) == pid
            assert (await _identity(session)) in (None, "")
            assert (await _identity(session)) != str(user)


@pytest.mark.asyncio
async def test_empty_and_absent_identity_are_fail_closed_expressions(pinned):
    async with pinned.factory() as session:
        async with session.begin():
            # Absent: current_setting(..., true) yields NULL.
            absent = await session.scalar(
                text("select current_setting('app.user_id', true)")
            )
            assert absent is None
            unchanged = await session.scalar(
                text(
                    "select (nullif(current_setting('app.user_id', true), '')"
                    "::uuid is null)"
                )
            )
            assert unchanged is True

            # Empty: the frozen NULLIF expression stays NULL, no uuid cast error.
            await session.execute(
                text("select set_config('app.user_id', '', true)")
            )
            empty = await session.scalar(
                text(
                    "select (nullif(current_setting('app.user_id', true), '')"
                    "::uuid is null)"
                )
            )
            assert empty is True


@pytest.mark.asyncio
async def test_malformed_identity_raises_invalid_text_representation(pinned):
    from sqlalchemy.exc import DBAPIError

    async with pinned.factory() as session:
        await session.execute(
            text("select set_config('app.user_id', 'not-a-uuid', true)")
        )
        with pytest.raises(DBAPIError) as error:
            await session.execute(
                text(
                    "select nullif(current_setting('app.user_id', true), '')"
                    "::uuid"
                )
            )
        assert error.value.orig.sqlstate == "22P02"
        await session.rollback()
