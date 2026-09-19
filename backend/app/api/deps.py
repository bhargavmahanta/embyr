"""FastAPI dependency wiring for authentication and the request transaction.

One ``AsyncSession`` is yielded per request inside a single transaction, so the
internal user resolution, the transaction-local ``app.user_id`` write, and the
route's RLS-protected queries all share the same connection and transaction.
Identity therefore cannot survive the request, even on a pooled connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import (
    AuthenticatedPrincipal,
    AuthError,
    AuthFailure,
    ExternalIdentity,
)
from app.auth.users import resolve_user_id
from app.auth.verifier import TokenVerifier, parse_bearer
from app.config import Settings
from app.db.session import set_current_user


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_verifier(request: Request) -> TokenVerifier:
    return request.app.state.verifier


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        async with session.begin():
            yield session


async def get_external_identity(
    request: Request,
    verifier: TokenVerifier = Depends(get_verifier),
) -> ExternalIdentity:
    token = parse_bearer(request.headers.get("authorization"))
    return await run_in_threadpool(verifier.verify, token)


async def get_principal(
    identity: ExternalIdentity = Depends(get_external_identity),
    session: AsyncSession = Depends(get_session),
) -> AuthenticatedPrincipal:
    user_id = await resolve_user_id(session, identity)
    if user_id is None:
        raise AuthError(AuthFailure.UNMAPPED_IDENTITY)
    await set_current_user(session, user_id)
    return AuthenticatedPrincipal(user_id=user_id, identity=identity)
