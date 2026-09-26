"""Learning-only database failure boundary; preserve shared principal transaction."""

import logging

from fastapi import Depends
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_session
from app.api.errors import AppError

LOGGER = logging.getLogger(__name__)


async def get_learning_session(session: AsyncSession = Depends(get_session)):
    try:
        yield session
        # Include commit failures in this boundary. The underlying request
        # dependency sees a closed transaction after successful completion.
        if session.in_transaction():
            await session.commit()
    except SQLAlchemyError:
        LOGGER.warning(
            "learning_database_unavailable",
            extra={"failure_category": "DATABASE_UNAVAILABLE"},
        )
        if session.in_transaction():
            try:
                await session.rollback()
            except SQLAlchemyError:
                # A lost connection may also prevent rollback. Preserve the
                # same sanitized failure boundary while the pool discards it.
                pass
        # Never propagate SQLAlchemy's parameter-bearing diagnostic traceback
        # to the ASGI server. This affects only new learning routes.
        raise AppError(
            code="LEARNING_STORAGE_UNAVAILABLE",
            status=503,
            title="Learning storage unavailable",
            detail="Retry the command with the same key.",
        ) from None
