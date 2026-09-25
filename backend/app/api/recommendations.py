"""Frozen v0.1 recommendation generation and decision commands."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_principal, get_session
from app.api.errors import AppError
from app.api.idempotency import (
    find_idempotent_result, request_fingerprint, require_idempotency_key,
    reserve_idempotent_command, store_idempotent_result,
)
from app.auth.principal import AuthenticatedPrincipal
from app.db.session import set_current_user
from app.integrations.voyage import EmbeddingProviderError, VoyageQueryEmbedder
from app.recommendation.persistence import (
    INTENT_BY_MODE, StaleRecommendationTarget, load_recommendation, persist_decision,
    persist_selected_recommendation, selected_provenance,
)
from app.recommendation.service import generate_recommendation
from app.recommendation.snapshot import assemble_production_snapshot

router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])
_TITLE_SQL = text("""
    select title from public.learning_entity_versions
     where entity_id = :entity_id and version = :entity_version
""")
_CURRENT_TARGET_SQL = text("""
    select 1 from public.learning_entities as entity
    join public.learning_entity_versions as version
      on version.entity_id = entity.id and version.version = :entity_version
    where entity.id = :entity_id
      and entity.status in ('REVIEWED', 'PUBLISHED')
      and entity.current_version = :entity_version
""")


class NextRequest(BaseModel):
    mode: Literal["CONTINUE", "EXPLORE", "CREATE", "SURPRISE", "REVISIT"]
    available_minutes: int | None = Field(default=None, gt=0)
    practical_context: dict[str, Any] | None = None


class DecisionRequest(BaseModel):
    decision: Literal["ACCEPT", "SKIP"]
    reason: str | None = Field(default=None, max_length=64)


def _replayed(reservation) -> dict:
    if reservation.response_status != 200 or reservation.response_body is None:
        raise AppError(
            code="COMMAND_IN_PROGRESS", status=409, title="Command in progress",
            detail="Retry this command with the same Idempotency-Key.",
        )
    return reservation.response_body


def _recommendation_dto(
    *, recommendation_id: UUID, selected: dict, snapshot, mode: str,
    band: str, presented_at: datetime,
) -> dict:
    target = next(
        row for row in snapshot.entities
        if row["entity_id"] == selected["target_entity_id"]
        and row["entity_version"] == selected["target_entity_version"]
    )
    provenance = selected_provenance(selected)
    return {
        "id": str(recommendation_id), "target_type": "LEARNING_ENTITY",
        "entity": {"id": target["entity_id"], "title": target["title"]},
        "practical_challenge": None, "mode": mode, "distance_band": band,
        "hook": provenance.presentation["hook"],
        "reason": provenance.presentation["reason"],
        "presented_at": presented_at.isoformat(),
    }


@router.post("/next")
async def next_recommendation(
    body: NextRequest, request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = principal.user_id
    key = require_idempotency_key(request)
    command = "recommendations.next"
    fingerprint = request_fingerprint(command, body.model_dump(mode="json"))
    previous = await find_idempotent_result(
        session, user_id=user_id, idempotency_key=key,
        command_name=command, fingerprint=fingerprint,
    )
    if previous is not None:
        return _replayed(previous)

    # Release auth's transaction before the detached snapshot and any provider call.
    await session.commit()
    snapshot = await assemble_production_snapshot(request.app.state.session_factory, user_id)
    embedder = getattr(request.app.state, "query_embedder", None)
    if embedder is None and request.app.state.settings.voyage_api_key:
        embedder = VoyageQueryEmbedder(request.app.state.settings.voyage_api_key)
    try:
        ranking, band = await generate_recommendation(snapshot, mode=body.mode, embedder=embedder)
    except (EmbeddingProviderError, RuntimeError) as error:
        raise AppError(
            code="RECOMMENDATION_GENERATION_UNAVAILABLE", status=503,
            title="Recommendation generation unavailable",
        ) from error

    await set_current_user(session, user_id)
    reservation = await reserve_idempotent_command(
        session, user_id=user_id, idempotency_key=key,
        command_name=command, fingerprint=fingerprint,
    )
    if reservation.replay:
        response = _replayed(reservation)
        await session.commit()
        return response
    if ranking.selected is None:
        response = {"recommendation": None}
        result_type, result_id = "EMPTY_RECOMMENDATION", reservation.record_id
    else:
        assert band is not None
        current = await session.scalar(_CURRENT_TARGET_SQL, {
            "entity_id": UUID(ranking.selected["target_entity_id"]),
            "entity_version": ranking.selected["target_entity_version"],
        })
        if current is None:
            raise AppError(
                code="RECOMMENDATION_GENERATION_UNAVAILABLE", status=503,
                title="Recommendation generation unavailable",
            )
        presented_at = datetime.now(timezone.utc)
        try:
            recommendation_id = await persist_selected_recommendation(
                session, user_id=user_id, selected=ranking.selected,
                mode=body.mode, distance_band=band,
                ranking_model_version=ranking.profile_version, presented_at=presented_at,
            )
        except StaleRecommendationTarget as error:
            raise AppError(
                code="RECOMMENDATION_GENERATION_UNAVAILABLE", status=503,
                title="Recommendation generation unavailable",
            ) from error
        response = _recommendation_dto(
            recommendation_id=recommendation_id, selected=ranking.selected,
            snapshot=snapshot, mode=body.mode, band=band, presented_at=presented_at,
        )
        result_type, result_id = "RECOMMENDATION", recommendation_id
    await store_idempotent_result(
        session, user_id=user_id, record_id=reservation.record_id,
        result_type=result_type, result_id=result_id,
        response_status=200, response_body=response,
    )
    await session.commit()
    return response


@router.post("/{recommendation_id}/decision")
async def decide_recommendation(
    recommendation_id: UUID, body: DecisionRequest, request: Request,
    principal: AuthenticatedPrincipal = Depends(get_principal),
    session: AsyncSession = Depends(get_session),
) -> dict:
    user_id = principal.user_id
    key = require_idempotency_key(request)
    command = "recommendations.decision"
    fingerprint = request_fingerprint(
        command, {"recommendation_id": str(recommendation_id), **body.model_dump(mode="json")}
    )
    reservation = await reserve_idempotent_command(
        session, user_id=user_id, idempotency_key=key,
        command_name=command, fingerprint=fingerprint,
    )
    if reservation.replay:
        return _replayed(reservation)
    recommendation = await load_recommendation(
        session, user_id=user_id, recommendation_id=recommendation_id,
        for_update=True,
    )
    if recommendation is None:
        raise AppError(code="RECOMMENDATION_NOT_FOUND", status=404, title="Recommendation not found")
    if recommendation["decision"] is not None:
        raise AppError(code="RECOMMENDATION_ALREADY_DECIDED", status=409, title="Recommendation already decided")
    outcome = await persist_decision(
        session, user_id=user_id, recommendation=recommendation,
        decision=body.decision, command_id=reservation.record_id,
    )
    if outcome.exploration_id is None:
        response = {"recommendation_id": str(recommendation_id), "decision": "SKIP"}
        result_type, result_id = "RECOMMENDATION_DECISION", recommendation_id
    else:
        title = await session.scalar(_TITLE_SQL, {
            "entity_id": recommendation["entity_id"],
            "entity_version": recommendation["entity_version"],
        })
        if title is None:
            raise ValueError("accepted entity version is missing")
        exploration = {
            "id": str(outcome.exploration_id),
            "entity": {"id": str(recommendation["entity_id"]), "title": title},
            "entity_version": recommendation["entity_version"],
            "practical_challenge_id": None,
            "learning_intent": INTENT_BY_MODE[recommendation["mode"]],
            "status": "ACTIVE", "started_at": outcome.decided_at.isoformat(),
            "returned_at": None, "paused_at": None, "completed_at": None,
            "version": 1,
        }
        response = exploration
        result_type, result_id = "EXPLORATION", outcome.exploration_id
    await store_idempotent_result(
        session, user_id=user_id, record_id=reservation.record_id,
        result_type=result_type, result_id=result_id,
        response_status=200, response_body=response,
    )
    await session.commit()
    return response
