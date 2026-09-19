"""Embyr FastAPI application factory.

Minimal auth-focused scaffold: settings, database session factory, the Supabase
token verifier, the problem-details error model, and the session routes. The
Supabase verifier is built from configuration only when one is not injected, so
tests can supply deterministic signing material.
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.errors import register_exception_handlers
from app.api.routes import router
from app.auth.verifier import SupabaseTokenVerifier
from app.config import Settings


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        yield
    finally:
        engine = app.state.engine
        if engine is not None:
            await engine.dispose()


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    verifier: SupabaseTokenVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Embyr API", lifespan=_lifespan)

    engine = None
    if session_factory is None:
        engine = create_async_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    if verifier is None:
        verifier = SupabaseTokenVerifier(
            issuer=settings.supabase_auth_issuer,
            audience=settings.supabase_jwt_audience,
            jwks_url=settings.resolved_jwks_url,
        )

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.verifier = verifier
    app.state.engine = engine

    register_exception_handlers(app)
    app.include_router(router)
    return app
