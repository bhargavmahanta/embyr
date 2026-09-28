"""Resolve identity and read projections in one isolated transaction."""

from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.errors import AppError
from app.auth.principal import AuthError, AuthFailure, ExternalIdentity
from app.auth.users import resolve_user_id
from app.db.session import set_current_user


def integrity_error():
    return AppError(
        code="M6_READ_UNAVAILABLE",
        status=503,
        title="Projection read unavailable",
        detail="The projection could not be read.",
    )


@asynccontextmanager
async def read_transaction(factory, identity: ExternalIdentity):
    try:
        async with factory() as session:
            try:
                await session.begin()
                await session.execute(
                    text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                )
                user_id = await resolve_user_id(session, identity)
                if user_id is None:
                    raise AuthError(AuthFailure.UNMAPPED_IDENTITY)
                await set_current_user(session, user_id)
                yield session, user_id
            finally:
                await session.rollback()
    except SQLAlchemyError:
        raise integrity_error() from None
