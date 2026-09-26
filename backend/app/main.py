"""Embyr FastAPI application factory.

Minimal auth-focused scaffold: settings, database session factory, the Supabase
token verifier, the problem-details error model, and the session routes. The
Supabase verifier and the private Storage client are built from configuration
only when one is not injected, so tests can supply deterministic doubles.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.errors import register_exception_handlers
from app.api.routes import router
from app.api.recommendations import router as recommendations_router
from app.api.uploads import router as uploads_router
from app.api.learning import router as learning_router
from app.api.assessments import router as assessments_router
from app.auth.verifier import SupabaseTokenVerifier
from app.config import Settings
from app.db.session import create_async_database_engine
from app.storage import StorageService, SupabaseStorageService


@asynccontextmanager
async def _lifespan(app: FastAPI):
    try:
        yield
    finally:
        storage = app.state.storage
        if storage is not None and app.state.storage_owned:
            await storage.aclose()
        engine = app.state.engine
        if engine is not None:
            await engine.dispose()


def create_app(
    *,
    settings: Settings | None = None,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    verifier: SupabaseTokenVerifier | None = None,
    storage: StorageService | None = None,
    query_embedder: object | None = None,
) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Embyr API", lifespan=_lifespan)

    engine = None
    if session_factory is None:
        engine = create_async_database_engine(settings.database_url)
        session_factory = async_sessionmaker(engine, expire_on_commit=False)
    if verifier is None:
        verifier = SupabaseTokenVerifier(
            issuer=settings.supabase_auth_issuer,
            audience=settings.supabase_jwt_audience,
            jwks_url=settings.resolved_jwks_url,
        )

    storage_owned = False
    if storage is None and settings.storage_enabled:
        bucket = settings.storage_bucket
        secret_key = settings.storage_secret_key
        assert bucket is not None and secret_key is not None
        storage = SupabaseStorageService(
            storage_url=settings.storage_api_url,
            secret_key=secret_key,
            bucket=bucket,
        )
        storage_owned = True

    app.state.settings = settings
    app.state.session_factory = session_factory
    app.state.verifier = verifier
    app.state.storage = storage
    app.state.query_embedder = query_embedder
    app.state.storage_owned = storage_owned
    app.state.engine = engine

    register_exception_handlers(app)
    app.include_router(router)
    app.include_router(uploads_router)
    app.include_router(recommendations_router)
    app.include_router(learning_router)
    app.include_router(assessments_router)
    return app
