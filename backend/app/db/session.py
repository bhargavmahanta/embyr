from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# TLS is mandatory for the application database connection. libpq defaults to
# ``sslmode=prefer``, which can silently fall back to plaintext, so the URL must
# select an SSL mode that actually requires encryption. This is the single TLS
# policy shared by every application engine (session factory and FastAPI app).
TLS_REQUIRED_SSLMODES = frozenset({"require", "verify-ca", "verify-full"})


def require_database_tls(url: str) -> None:
    sslmode = (make_url(url).query.get("sslmode") or "").lower()
    if sslmode not in TLS_REQUIRED_SSLMODES:
        raise RuntimeError(
            "EMBYR_DATABASE_URL must require TLS: set sslmode=require, or "
            "sslmode=verify-full with sslrootcert. Omitted or disabled SSL "
            "modes are not permitted."
        )


def create_async_database_engine(database_url: str):
    """Create the runtime engine, enforcing the mandatory TLS policy."""
    require_database_tls(database_url)
    return create_async_engine(database_url)


def async_session_factory(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    url = database_url or os.getenv("EMBYR_DATABASE_URL")
    if not url:
        raise RuntimeError("EMBYR_DATABASE_URL is required")
    engine = create_async_database_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def set_current_user(session: AsyncSession, user_id: UUID | str) -> None:
    await session.execute(
        text("select set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
