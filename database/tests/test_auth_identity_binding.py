"""End-to-end identity binding: external Supabase subject -> app_users.id ->
transaction-local ``app.user_id`` -> forced RLS.

These run against real PostgreSQL with the real migration security boundary
(``app_backend`` is ``NOBYPASSRLS``). Nothing about JWT verification, user
resolution, identity propagation, or row isolation is mocked.
"""
from __future__ import annotations

import asyncio
import datetime as dt
import sys
from collections.abc import AsyncIterator, Awaitable, Callable, Coroutine
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID, uuid4

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.auth.principal import ExternalIdentity
from app.auth.users import resolve_or_create_user_id, resolve_user_id
from app.auth.verifier import SupabaseTokenVerifier
from app.config import Settings
from app.db.session import set_current_user
from app.main import create_app

ISS = "https://embyr-dev.supabase.co/auth/v1"
AUD = "authenticated"


def _run_async(coro: Coroutine[Any, Any, None]) -> None:
    if sys.platform == "win32":
        asyncio.run(coro, loop_factory=asyncio.SelectorEventLoop)
    else:
        asyncio.run(coro)


class _Harness:
    def __init__(self, database_url: str) -> None:
        self.engine = create_async_engine(
            database_url, pool_size=1, max_overflow=0
        )
        self.factory = async_sessionmaker(
            self.engine, expire_on_commit=False
        )

    @asynccontextmanager
    async def transaction(
        self, *, role: str | None = None
    ) -> AsyncIterator[AsyncSession]:
        async with self.factory() as session:
            async with session.begin():
                if role is not None:
                    await session.execute(text(f"set local role {role}"))
                yield session

    async def dispose(self) -> None:
        await self.engine.dispose()


def _run_pinned(
    database_url: str, body: Callable[[_Harness], Awaitable[None]]
) -> None:
    async def main() -> None:
        harness = _Harness(database_url)
        try:
            await body(harness)
        finally:
            await harness.dispose()

    _run_async(main())


async def _identity(session: AsyncSession) -> str | None:
    return await session.scalar(text("select current_setting('app.user_id', true)"))


async def _count_preferences(session: AsyncSession, user_id: UUID) -> int:
    return await session.scalar(
        text("select count(*) from learner_preferences where user_id = :user_id"),
        {"user_id": user_id},
    )


async def _insert_preference(session: AsyncSession, user_id: UUID) -> None:
    await session.execute(
        text(
            "insert into learner_preferences "
            "(user_id, adventure_preference, preferred_effort, support_style) "
            "values (:user_id, 'BALANCED', '15_20_MIN', 'SMALL_HINT')"
        ),
        {"user_id": user_id},
    )


def test_resolve_or_create_is_idempotent_and_unique(migrated_engine, database_url):
    del migrated_engine
    identity = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            first = await resolve_or_create_user_id(session, identity)
            second = await resolve_or_create_user_id(session, identity)
            assert first == second

        async with harness.transaction() as session:
            rows = await session.execute(
                text(
                    "select count(*) from app_users "
                    "where auth_provider = :p and auth_subject = :s"
                ),
                {"p": identity.provider, "s": identity.subject},
            )
            assert rows.scalar_one() == 1

    _run_pinned(database_url, body)


def test_unknown_subject_does_not_resolve(migrated_engine, database_url):
    del migrated_engine
    identity = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            assert await resolve_user_id(session, identity) is None

    _run_pinned(database_url, body)


def test_backend_role_can_resolve_and_create_app_users(
    migrated_engine, database_url
):
    """Proves the granted app_backend INSERT path used by bootstrap."""
    del migrated_engine
    identity = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            user_id = await resolve_or_create_user_id(session, identity)
            assert isinstance(user_id, UUID)
            assert str(user_id) != identity.subject

    _run_pinned(database_url, body)


def test_identity_binding_scopes_rls_reads(migrated_engine, database_url):
    del migrated_engine
    identity_a = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")
    identity_b = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            user_a = await resolve_or_create_user_id(session, identity_a)
            user_b = await resolve_or_create_user_id(session, identity_b)

        # Fixture rows are inserted as the administrative superuser, which
        # bypasses RLS; the RLS assertions below run as app_backend.
        async with harness.transaction() as session:
            await _insert_preference(session, user_a)
            await _insert_preference(session, user_b)

        async with harness.transaction(role="app_backend") as session:
            assert await _count_preferences(session, user_a) == 0
            assert await _count_preferences(session, user_b) == 0

            await set_current_user(session, user_a)
            assert await _count_preferences(session, user_a) == 1
            assert await _count_preferences(session, user_b) == 0

            await set_current_user(session, user_b)
            assert await _count_preferences(session, user_a) == 0
            assert await _count_preferences(session, user_b) == 1

    _run_pinned(database_url, body)


def test_cross_user_insert_is_rejected_by_rls(migrated_engine, database_url):
    del migrated_engine
    identity_a = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")
    identity_b = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            user_a = await resolve_or_create_user_id(session, identity_a)
            user_b = await resolve_or_create_user_id(session, identity_b)

        async with harness.transaction(role="app_backend") as session:
            await set_current_user(session, user_a)
            with pytest.raises(Exception) as error:
                await _insert_preference(session, user_b)
            assert getattr(error.value.orig, "sqlstate", None) == "42501" or (
                "row-level security" in str(error.value).lower()
            )

    _run_pinned(database_url, body)


def test_identity_does_not_leak_across_pooled_transactions(
    migrated_engine, database_url
):
    del migrated_engine
    identity = ExternalIdentity("SUPABASE", f"sub-{uuid4()}")

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            user_id = await resolve_or_create_user_id(session, identity)
            await set_current_user(session, user_id)
            await _insert_preference(session, user_id)
            assert await _count_preferences(session, user_id) == 1

        # Same pooled connection, new transaction: identity is gone and RLS
        # fails closed, so the previous user's row is invisible.
        async with harness.transaction(role="app_backend") as session:
            assert (await _identity(session)) in (None, "")
            assert await _count_preferences(session, user_id) == 0

    _run_pinned(database_url, body)


def test_verified_jwt_resolves_to_internal_uuid(migrated_engine, database_url):
    """Vertical slice: verified JWT -> internal id -> transaction identity."""
    del migrated_engine
    signing_key = ec.generate_private_key(ec.SECP256R1())
    subject = f"sub-{uuid4()}"
    now = dt.datetime.now(dt.timezone.utc)
    token = jwt.encode(
        {
            "sub": subject,
            "iss": ISS,
            "aud": AUD,
            "role": "authenticated",
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        signing_key,
        algorithm="ES256",
    )

    class _StaticJwkClient:
        def get_signing_key_from_jwt(self, token: str):
            class _Key:
                key = signing_key.public_key()

            return _Key()

    verifier = SupabaseTokenVerifier(
        issuer=ISS, audience=AUD, jwk_client=_StaticJwkClient()
    )
    identity = verifier.verify(token)

    async def body(harness: _Harness) -> None:
        async with harness.transaction(role="app_backend") as session:
            user_id = await resolve_or_create_user_id(session, identity)
            await set_current_user(session, user_id)
            await _insert_preference(session, user_id)

            assert str(user_id) != identity.subject
            assert await _count_preferences(session, user_id) == 1
            current = await _identity(session)
            assert current is not None
            assert UUID(current) == user_id

    _run_pinned(database_url, body)


def _signed_token(signing_key, subject: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return jwt.encode(
        {
            "sub": subject,
            "iss": ISS,
            "aud": AUD,
            "role": "authenticated",
            "iat": now,
            "exp": now + dt.timedelta(minutes=5),
        },
        signing_key,
        algorithm="ES256",
    )


class _PublicKeyJwkClient:
    def __init__(self, signing_key) -> None:
        self._public_key = signing_key.public_key()

    def get_signing_key_from_jwt(self, token: str):
        public_key = self._public_key

        class _Key:
            key = public_key

        return _Key()


def _http_app(database_url: str, signing_key):
    engine = create_async_engine(database_url, pool_size=1, max_overflow=0)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(
        settings=Settings(
            database_url=database_url,
            supabase_auth_issuer=ISS,
            supabase_jwt_audience=AUD,
        ),
        session_factory=factory,
        verifier=SupabaseTokenVerifier(
            issuer=ISS, audience=AUD, jwk_client=_PublicKeyJwkClient(signing_key)
        ),
    )
    return app, engine


def test_http_bootstrap_then_me_resolves_internal_identity(
    migrated_engine, database_url
):
    """Full vertical: signed JWT -> FastAPI -> internal id -> RLS identity."""
    del migrated_engine
    signing_key = ec.generate_private_key(ec.SECP256R1())
    subject = f"sub-{uuid4()}"
    token = _signed_token(signing_key, subject)

    async def body() -> None:
        app, engine = _http_app(database_url, signing_key)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                headers = {"Authorization": f"Bearer {token}"}
                bootstrap = await client.post(
                    "/api/v1/session/bootstrap", headers=headers
                )
                assert bootstrap.status_code == 200, bootstrap.text
                payload = bootstrap.json()
                assert UUID(payload["id"])
                assert payload["id"] != subject
                assert payload["onboarding_completed_at"] is None
                assert payload["preferences"] is None
                assert payload["world_revision"] is None

                me = await client.get("/api/v1/me", headers=headers)
                assert me.status_code == 200, me.text
                assert me.json()["id"] == payload["id"]
        finally:
            await engine.dispose()

    _run_async(body())


def test_http_unmapped_identity_is_401(migrated_engine, database_url):
    """A valid token with no internal mapping cannot authenticate."""
    del migrated_engine
    signing_key = ec.generate_private_key(ec.SECP256R1())
    token = _signed_token(signing_key, f"sub-{uuid4()}")

    async def body() -> None:
        app, engine = _http_app(database_url, signing_key)
        try:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport, base_url="http://test"
            ) as client:
                response = await client.get(
                    "/api/v1/me",
                    headers={"Authorization": f"Bearer {token}"},
                )
                assert response.status_code == 401
                assert response.json()["code"] == "UNMAPPED_IDENTITY"
                assert response.headers["www-authenticate"] == "Bearer"
        finally:
            await engine.dispose()

    _run_async(body())
