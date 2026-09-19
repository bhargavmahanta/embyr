"""Session bootstrap and authenticated profile routes.

Only the routes required to prove the authentication pipeline are implemented:
bootstrap (resolve-or-create) and the authenticated profile read that exercises
transaction-local RLS identity.
"""
from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_external_identity, get_principal, get_session
from app.auth.principal import AuthenticatedPrincipal, ExternalIdentity
from app.auth.users import resolve_or_create_user_id
from app.db.session import set_current_user

router = APIRouter(prefix="/api/v1", tags=["session"])

_ONBOARDING_SQL = text(
    "select onboarding_completed_at from public.app_users where id = :user_id"
)
_PREFERENCES_SQL = text(
    "select adventure_preference, preferred_effort, support_style, "
    "practical_opt_in, version from public.learner_preferences "
    "where user_id = :user_id"
)
_WORLD_REVISION_SQL = text(
    "select current_revision from public.learner_worlds where user_id = :user_id"
)


async def _load_profile(session: AsyncSession, user_id: UUID) -> dict:
    onboarding = await session.scalar(_ONBOARDING_SQL, {"user_id": user_id})
    preferences = (
        await session.execute(_PREFERENCES_SQL, {"user_id": user_id})
    ).mappings().first()
    world_revision = await session.scalar(
        _WORLD_REVISION_SQL, {"user_id": user_id}
    )
    return {
        "id": str(user_id),
        "onboarding_completed_at": (
            onboarding.isoformat() if onboarding is not None else None
        ),
        "preferences": dict(preferences) if preferences is not None else None,
        "world_revision": world_revision,
    }


@router.post("/session/bootstrap")
async def bootstrap_session(
    identity: ExternalIdentity = Depends(get_external_identity),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = await resolve_or_create_user_id(session, identity)
    await set_current_user(session, user_id)
    return await _load_profile(session, user_id)


@router.get("/me")
async def get_me(
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    return await _load_profile(session, principal.user_id)
