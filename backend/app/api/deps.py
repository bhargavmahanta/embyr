"""FastAPI dependency wiring for authentication and the request transaction.

One ``AsyncSession`` is yielded per request. A transaction begins lazily on the
first statement (autobegin), so the internal user resolution, the
transaction-local ``app.user_id`` write, and the route's RLS-protected queries
share one connection and transaction. Routes that must release the database
transaction before a network call may ``await session.commit()`` themselves;
the teardown only commits or rolls back when a transaction is still open.
Identity therefore cannot survive the request, even on a pooled connection.
"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends, Request
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.errors import AppError
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
from app.storage import StorageService


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_verifier(request: Request) -> TokenVerifier:
    return request.app.state.verifier


def get_storage(request: Request) -> StorageService:
    storage = getattr(request.app.state, "storage", None)
    if storage is None:
        raise AppError(
            code="STORAGE_UNAVAILABLE",
            status=503,
            title="Storage unavailable",
            detail="Object storage is not configured for this process.",
        )
    return storage


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    factory = request.app.state.session_factory
    async with factory() as session:
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except BaseException:
            if session.in_transaction():
                await session.rollback()
            raise


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
