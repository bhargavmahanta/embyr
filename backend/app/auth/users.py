"""Resolve and provision Embyr users from a verified external identity.

``app_users`` is intentionally outside learner RLS: authentication must resolve
the internal UUID from ``(auth_provider, auth_subject)`` before a per-user
context exists. Resolution therefore runs before ``app.user_id`` is set, under
the same least-privileged ``app_backend`` grant that owns request-path writes.
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import ExternalIdentity

_RESOLVE_SQL = text(
    "select id from public.app_users "
    "where auth_provider = :provider and auth_subject = :subject"
)
_INSERT_SQL = text(
    "insert into public.app_users (auth_provider, auth_subject) "
    "values (:provider, :subject) "
    "on conflict (auth_provider, auth_subject) do nothing"
)


async def resolve_user_id(
    session: AsyncSession, identity: ExternalIdentity
) -> UUID | None:
    """Return the internal user id for a verified identity, or ``None``.

    The ``(auth_provider, auth_subject)`` unique constraint guarantees at most
    one row, so a duplicate is an integrity failure of the schema, not a
    decision this function makes.
    """
    return await session.scalar(
        _RESOLVE_SQL,
        {"provider": identity.provider, "subject": identity.subject},
    )


async def resolve_or_create_user_id(
    session: AsyncSession, identity: ExternalIdentity
) -> UUID:
    """Resolve the internal user id, creating the row on first bootstrap.

    Idempotent through the unique auth-subject mapping, so concurrent first
    bootstraps converge on one row.
    """
    await session.execute(
        _INSERT_SQL,
        {"provider": identity.provider, "subject": identity.subject},
    )
    user_id = await resolve_user_id(session, identity)
    if user_id is None:  # pragma: no cover - guarded by the unique constraint
        raise RuntimeError("app_users row missing after upsert")
    return user_id
