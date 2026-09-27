"""Authenticated reads use a fresh transaction, independently of auth SQL."""

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.errors import AppError
from app.db.session import set_current_user


def integrity_error():
    return AppError(
        code="M6_READ_UNAVAILABLE",
        status=503,
        title="Projection read unavailable",
        detail="The projection could not be read.",
    )


@asynccontextmanager
async def read_transaction(factory, user_id):
    try:
        async with factory() as session:
            try:
                await session.begin()
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                await set_current_user(session, user_id)
                yield session
            finally:
                await session.rollback()
    except SQLAlchemyError:
        raise integrity_error() from None
