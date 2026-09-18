"""Transaction-local ``app.user_id`` isolation across pooled connections.

These tests run against the disposable database provided by the shared harness.
They prove the M1 identity contract at the connection layer: ``set_current_user``
writes the RLS identity with transaction-local semantics, and no identity
survives commit, rollback, or an application error, even when the same physical
connection is reused.

The engine is pinned to ``pool_size=1, max_overflow=0`` so sequential sessions
deterministically reuse one backend; ``pg_backend_pid()`` is asserted to prove
reuse rather than hoping the pool happens to hand back the same connection.

The async bodies are driven synchronously through ``asyncio.run`` with an
explicit loop factory on Windows. Psycopg cannot run on Windows' default
ProactorEventLoop, and the event-loop policy API is deprecated and removed in
Python 3.16, so the supported ``loop_factory`` argument (available since
Python 3.12) is used instead of mutating global event-loop policy state.
"""
from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.db.session import set_current_user


async def _identity(session: AsyncSession) -> str | None:
    return await session.scalar(text("select current_setting('app.user_id', true)"))


async def _pid(session: AsyncSession) -> int:
    return await session.scalar(text("select pg_backend_pid()"))


class _Pinned:
    """A one-connection async engine plus sessionmaker for reuse proofs."""

    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(
            database_url, pool_size=1, max_overflow=0
        )
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)

    async def __aenter__(self) -> _Pinned:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.engine.dispose()


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    # Psycopg cannot run on Windows' default ProactorEventLoop. Select the
    # SelectorEventLoop through the supported ``loop_factory`` argument rather
    # than the event-loop policy API, which is removed in Python 3.16.
    if sys.platform == "win32":
        asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(coro)


def _run_pinned(
    database_url: str,
    body: Callable[[_Pinned], Awaitable[None]],
) -> None:
    async def main() -> None:
        async with _Pinned(database_url) as pinned:
            await body(pinned)

    _run_async(main())


def test_identity_is_transaction_local_across_boundaries(database_url):
    user_a = uuid4()
    user_b = uuid4()

    async def body(pinned: _Pinned) -> None:
        async with pinned.factory() as session:
            async with session.begin():
                await set_current_user(session, user_a)
                assert await _identity(session) == str(user_a)
                pid_a = await _pid(session)

        # Commit released the same physical connection and cleared user A.
        async with pinned.factory() as session:
            async with session.begin():
                assert await _pid(session) == pid_a
                assert (await _identity(session)) in (None, "")
                assert (await _identity(session)) != str(user_a)

        # Explicit rollback of user B on the same physical connection. The
        # identity is visible inside the transaction, then the transaction is
        # rolled back without an exception.
        async with pinned.factory() as session:
            await set_current_user(session, user_b)
            assert await _identity(session) == str(user_b)
            assert await _pid(session) == pid_a
            await session.rollback()

        # Neither identity survives its transaction boundary.
        async with pinned.factory() as session:
            async with session.begin():
                assert await _pid(session) == pid_a
                assert (await _identity(session)) in (None, "")
                assert (await _identity(session)) != str(user_a)
                assert (await _identity(session)) != str(user_b)

    _run_pinned(database_url, body)


def test_identity_absent_when_request_sets_none(database_url):
    async def body(pinned: _Pinned) -> None:
        async with pinned.factory() as session:
            async with session.begin():
                assert (await _identity(session)) in (None, "")

    _run_pinned(database_url, body)


def test_application_exception_clears_identity_on_reused_connection(database_url):
    user = uuid4()
    pid: int | None = None

    async def body(pinned: _Pinned) -> None:
        nonlocal pid
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

    _run_pinned(database_url, body)


def test_empty_and_absent_identity_are_fail_closed_expressions(database_url):
    async def body(pinned: _Pinned) -> None:
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

                # Empty: the frozen NULLIF expression stays NULL, no uuid cast.
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

    _run_pinned(database_url, body)


def test_malformed_identity_raises_invalid_text_representation(database_url):
    async def body(pinned: _Pinned) -> None:
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

    _run_pinned(database_url, body)
