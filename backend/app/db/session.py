from __future__ import annotations

import os
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def async_session_factory(
    database_url: str | None = None,
) -> async_sessionmaker[AsyncSession]:
    url = database_url or os.getenv("EMBYR_DATABASE_URL")
    if not url:
        raise RuntimeError("EMBYR_DATABASE_URL is required")
    engine = create_async_engine(url)
    return async_sessionmaker(engine, expire_on_commit=False)


async def set_current_user(session: AsyncSession, user_id: UUID | str) -> None:
    await session.execute(
        text("select set_config('app.user_id', :user_id, true)"),
        {"user_id": str(user_id)},
    )
