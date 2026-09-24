"""Ownership-scoped recommendation presentation and outcome persistence."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from research.recommendation.simulator.explain import EXPLANATION_CODES

COPY_PATH = Path(__file__).with_name("profiles") / "recommendation-copy-v1.json"
RANKING_MODEL_VERSION = "recommendation-profile/v1"
INTENT_BY_MODE = {
    "CONTINUE": "RELATED_EXPLORATION",
    "REVISIT": "RETENTION_REVISIT",
    "EXPLORE": "DIRECT_INTEREST",
    "SURPRISE": "SERENDIPITY",
    "CREATE": "PRACTICAL_SUPPORT",
}


@dataclass(frozen=True)
class SelectedProvenance:
    reason_code: str | None
    presentation_version: str
    presentation: dict[str, Any]
    score_components: dict[str, Any]


def selected_provenance(selected: dict) -> SelectedProvenance:
    """Keep only bounded selected-result evidence and reviewed static copy."""
    copy = json.loads(COPY_PATH.read_text(encoding="utf-8"))
    if copy["copy_version"] != "recommendation-copy/v1":
        raise ValueError("unsupported recommendation copy version")
    supplied = selected["explanation_codes"]
    if len(supplied) != len(set(supplied)) or set(supplied) - set(EXPLANATION_CODES):
        raise ValueError("invalid M3 explanation codes")
    codes = [code for code in EXPLANATION_CODES if code in supplied]
    primary = codes[0] if codes else None
    template = copy["templates"][primary] if primary else {"hook": None, "reason": None}
    return SelectedProvenance(
        reason_code=primary,
        presentation_version=copy["copy_version"],
        presentation={
            "hook": template["hook"], "reason": template["reason"],
            "explanation_codes": codes,
            "candidate_sources": list(selected["candidate_sources"]),
            "ranked_final_rank": selected["final_rank"],
            "shown_position": 1,
        },
        score_components={
            "component_scores": dict(selected["score_trace"]["component_scores"]),
            "pre_rerank_score": selected["score_trace"]["pre_rerank_score"],
            "diversity_adjustment": selected["rerank_trace"]["diversity_adjustment"],
            "ordering_score": selected["ordering_score"],
        },
    )


_INSERT_SQL = text("""
    insert into public.recommendations
      (id, user_id, entity_id, entity_version, mode, distance_band,
       ranking_model_version, score_components, reason_code,
       presentation_version, presentation, presented_at)
    values
      (:id, :user_id, :entity_id, :entity_version, :mode, :distance_band,
       :ranking_model_version, cast(:score_components as jsonb), :reason_code,
       :presentation_version, cast(:presentation as jsonb), :presented_at)
""")
_LOAD_SQL = text("""
    select id, user_id, entity_id, entity_version, challenge_id,
           mode, distance_band, ranking_model_version, score_components,
           reason_code, presentation_version, presentation, presented_at,
           decision, decided_at
      from public.recommendations
     where id = :id and user_id = :user_id
""")
_LOCK_SQL = text(str(_LOAD_SQL) + " for update")
_DECIDE_SQL = text("""
    update public.recommendations
       set decision = :decision, decided_at = :decided_at
     where id = :id and user_id = :user_id and decision is null
    returning id
""")
_EXPLORATION_SQL = text("""
    insert into public.explorations
      (id, user_id, entity_id, entity_version, recommendation_id,
       learning_intent, status, started_at)
    values
      (:id, :user_id, :entity_id, :entity_version, :recommendation_id,
       :learning_intent, 'ACTIVE', :started_at)
""")
_EVENT_SQL = text("""
    insert into public.learning_events
      (user_id, command_id, event_ordinal, event_type, entity_id,
       exploration_id, learning_intent, occurred_at, schema_version, metadata)
    values
      (:user_id, :command_id, :event_ordinal, :event_type, :entity_id,
       :exploration_id, :learning_intent, :occurred_at, 1, cast(:metadata as jsonb))
""")


async def persist_selected_recommendation(
    session: AsyncSession, *, user_id: UUID, selected: dict,
    mode: str, distance_band: str, ranking_model_version: str,
    presented_at: datetime | None = None,
) -> UUID:
    if ranking_model_version != RANKING_MODEL_VERSION:
        raise ValueError("unsupported recommendation ranking profile")
    if mode not in INTENT_BY_MODE:
        raise ValueError("unsupported recommendation mode")
    if distance_band not in {"COMFORT", "ADJACENT", "FRONTIER", "WILD"}:
        raise ValueError("unsupported distance band")
    provenance = selected_provenance(selected)
    recommendation_id = uuid4()
    await session.execute(_INSERT_SQL, {
        "id": recommendation_id, "user_id": user_id,
        "entity_id": UUID(selected["target_entity_id"]),
        "entity_version": selected["target_entity_version"],
        "mode": mode, "distance_band": distance_band,
        "ranking_model_version": ranking_model_version,
        "score_components": json.dumps(provenance.score_components),
        "reason_code": provenance.reason_code,
        "presentation_version": provenance.presentation_version,
        "presentation": json.dumps(provenance.presentation),
        "presented_at": presented_at or datetime.now(timezone.utc),
    })
    return recommendation_id


async def load_recommendation(
    session: AsyncSession, *, user_id: UUID, recommendation_id: UUID,
    for_update: bool = False,
) -> dict | None:
    statement = _LOCK_SQL if for_update else _LOAD_SQL
    row = (await session.execute(statement, {
        "id": recommendation_id, "user_id": user_id,
    })).mappings().first()
    return dict(row) if row is not None else None


@dataclass(frozen=True)
class DecisionOutcome:
    recommendation_id: UUID
    decision: str
    exploration_id: UUID | None
    decided_at: datetime


async def persist_decision(
    session: AsyncSession, *, user_id: UUID, recommendation: dict,
    decision: str, command_id: UUID, reason: str | None = None,
) -> DecisionOutcome:
    """Write decision, new Exploration, and ledger events in caller transaction."""
    if decision not in {"ACCEPT", "SKIP"}:
        raise ValueError("unsupported recommendation decision")
    if recommendation["user_id"] != user_id or recommendation["challenge_id"] is not None:
        raise ValueError("recommendation owner/target mismatch")
    if recommendation["decision"] is not None:
        raise ValueError("recommendation already decided")
    now = datetime.now(timezone.utc)
    changed = (await session.execute(_DECIDE_SQL, {
        "id": recommendation["id"], "user_id": user_id,
        "decision": decision, "decided_at": now,
    })).first()
    if changed is None:
        raise ValueError("recommendation decision conflict")
    exploration_id = uuid4() if decision == "ACCEPT" else None
    intent = INTENT_BY_MODE[recommendation["mode"]]
    if exploration_id is not None:
        await session.execute(_EXPLORATION_SQL, {
            "id": exploration_id, "user_id": user_id,
            "entity_id": recommendation["entity_id"],
            "entity_version": recommendation["entity_version"],
            "recommendation_id": recommendation["id"],
            "learning_intent": intent, "started_at": now,
        })
    events = [
        ("RECOMMENDATION_ACCEPTED" if decision == "ACCEPT" else "RECOMMENDATION_SKIPPED", 0),
    ]
    if exploration_id is not None:
        events.append(("EXPLORATION_STARTED", 1))
    for event_type, ordinal in events:
        await session.execute(_EVENT_SQL, {
            "user_id": user_id, "command_id": command_id,
            "event_ordinal": ordinal, "event_type": event_type,
            "entity_id": recommendation["entity_id"],
            "exploration_id": exploration_id,
            "learning_intent": intent, "occurred_at": now,
            "metadata": json.dumps({
                "recommendation_id": str(recommendation["id"]),
                **({"skip_reason": reason} if decision == "SKIP" and reason else {}),
            }),
        })
    return DecisionOutcome(recommendation["id"], decision, exploration_id, now)
