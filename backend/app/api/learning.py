"""Additive M5 entry, Exploration and private reflection commands."""

from __future__ import annotations

import base64
import binascii
import json
from datetime import datetime, timezone
from typing import Annotated, Literal
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Query, Request
from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import and_, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_principal
from app.api.learning_dtos import (
    StarterPageDTO,
    OnboardingDTO,
    InterestDTO,
    ExplorationPageDTO,
    ExplorationDetailDTO,
    DeliveryDTO,
    ExplorationDTO,
    ReflectionDTO,
)
from app.auth.principal import AuthenticatedPrincipal
from app.db.models.identity import (
    AppUser,
    LearnerPreference,
    UserMotivation,
    ExplicitInterestPreference,
)
from app.db.models.ontology import (
    LearningEntity,
    LearningEntityVersion,
    LearningObjective,
)
from app.db.models.exploration import Exploration, Reflection
from app.db.models.assessment import AssessmentSession
from app.learning.common import (
    check_version,
    emit,
    fail,
    finish,
    owned,
    reserve,
    LIFECYCLE_VERSION,
)
from app.learning.lifecycle import transition
from app.learning.transactions import get_learning_session

router = APIRouter(prefix="/api/v1", tags=["learning"])
Session = Annotated[AsyncSession, Depends(get_learning_session)]
Principal = Annotated[AuthenticatedPrincipal, Depends(get_principal)]


class StrictBody(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OnboardingBody(StrictBody):
    motivations: list[Annotated[str, Field(min_length=1, max_length=64)]] = Field(
        max_length=20
    )
    starter_interest_entity_ids: list[UUID] = Field(max_length=20)
    adventure_preference: str = Field(min_length=1, max_length=64)
    preferred_effort: str = Field(min_length=1, max_length=64)
    support_style: str = Field(min_length=1, max_length=64)
    practical_opt_in: bool


class InterestBody(StrictBody):
    base_version: int = Field(ge=0)
    preference: Literal["NEUTRAL", "MORE", "LESS", "PAUSED", "NOT_INTERESTED"]


class ActionBody(StrictBody):
    action: Literal["RETURN", "PAUSE", "RESUME"]
    base_version: int | None = Field(default=None, ge=1)


class CompletionBody(StrictBody):
    base_version: int = Field(ge=1)


class ReflectionBody(StrictBody):
    text: str = Field(min_length=1, max_length=10000)

    @field_validator("text")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("Reflection must contain text")
        return value


class ReflectionEditBody(ReflectionBody):
    base_version: int = Field(ge=1)


class EmptyBody(StrictBody):
    pass


def reflection_dto(row):
    return jsonable_encoder(
        {
            key: getattr(row, key)
            for key in (
                "id",
                "exploration_id",
                "entity_id",
                "text",
                "version",
                "created_at",
                "updated_at",
            )
        }
    )


def exploration_dto(row):
    return jsonable_encoder(
        {
            key: getattr(row, key)
            for key in (
                "id",
                "entity_id",
                "entity_version",
                "recommendation_id",
                "practical_challenge_id",
                "practical_challenge_version_id",
                "learning_intent",
                "status",
                "started_at",
                "returned_at",
                "paused_at",
                "completed_at",
                "version",
            )
        }
    )


def preferences_dto(row):
    return {
        key: getattr(row, key)
        for key in (
            "adventure_preference",
            "preferred_effort",
            "support_style",
            "practical_opt_in",
            "version",
        )
    }


async def starter_rows(session):
    from app.learning.content import starter_entity_ids

    return (
        await session.execute(
            select(LearningEntity, LearningEntityVersion)
            .join(
                LearningEntityVersion,
                and_(
                    LearningEntityVersion.entity_id == LearningEntity.id,
                    LearningEntityVersion.version == LearningEntity.current_version,
                ),
            )
            .where(
                LearningEntity.id.in_(starter_entity_ids()),
                LearningEntity.entity_type.in_(["DOMAIN", "AREA"]),
                LearningEntity.status.in_(["REVIEWED", "PUBLISHED"]),
            )
            .order_by(LearningEntity.canonical_key)
        )
    ).all()


@router.get("/catalog/starter-interests", response_model=StarterPageDTO)
async def starters(principal: Principal, session: Session):
    return {
        "items": [
            {
                "id": str(entity.id),
                "entity_type": entity.entity_type,
                "entity_version": version.version,
                "title": version.title,
                "summary": version.summary,
            }
            for entity, version in await starter_rows(session)
        ]
    }


@router.post("/me/onboarding/complete", response_model=OnboardingDTO)
async def onboarding(
    body: OnboardingBody, request: Request, principal: Principal, session: Session
):
    user_id = principal.user_id
    command = await reserve(session, request, user_id, body.model_dump(mode="json"))
    if command.replay:
        return command.response_body
    user = await session.scalar(
        select(AppUser).where(AppUser.id == user_id).with_for_update()
    )
    if user.onboarding_completed_at is not None:
        fail("ONBOARDING_ALREADY_COMPLETED")
    allowed = {entity.id for entity, _ in await starter_rows(session)}
    selected = set(body.starter_interest_entity_ids)
    if not selected <= allowed:
        fail(
            "INVALID_STARTER_INTEREST",
            422,
            "Choose interests from the current starter catalog.",
        )
    preference = await session.get(LearnerPreference, user_id)
    values = body.model_dump(exclude={"motivations", "starter_interest_entity_ids"})
    if preference is None:
        preference = LearnerPreference(user_id=user_id, version=1, **values)
        session.add(preference)
    else:
        for key, value in values.items():
            setattr(preference, key, value)
        preference.version += 1
        preference.updated_at = datetime.now(timezone.utc)
    for code in sorted(set(body.motivations)):
        if await session.get(UserMotivation, (user_id, code)) is None:
            session.add(UserMotivation(user_id=user_id, motivation_code=code))
    user.onboarding_completed_at = datetime.now(timezone.utc)
    user.updated_at = user.onboarding_completed_at
    await emit(
        session,
        user_id,
        "ONBOARDING_COMPLETED",
        command=command,
        metadata={"preferences_version": preference.version},
    )
    for ordinal, entity_id in enumerate(sorted(selected, key=str), start=1):
        interest = await session.get(ExplicitInterestPreference, (user_id, entity_id))
        if interest is None:
            interest = ExplicitInterestPreference(
                user_id=user_id, entity_id=entity_id, preference="MORE", version=1
            )
            session.add(interest)
        else:
            interest.preference = "MORE"
            interest.version += 1
            interest.updated_at = datetime.now(timezone.utc)
        await emit(
            session,
            user_id,
            "EXPLICIT_INTEREST_CHANGED",
            command=command,
            ordinal=ordinal,
            entity_id=entity_id,
            metadata={"preference": "MORE", "version": interest.version},
        )
    return await finish(
        session,
        user_id,
        command,
        {
            "preferences": preferences_dto(preference),
            "onboarding_completed_at": user.onboarding_completed_at,
        },
        user_id,
    )


@router.put("/memory/interests/{entity_id}", response_model=InterestDTO)
async def interest(
    entity_id: UUID, body: InterestBody, principal: Principal, session: Session
):
    user_id = principal.user_id
    # Serialize create-if-absent with onboarding and other addressed preference writes.
    await session.scalar(
        select(AppUser.id).where(AppUser.id == user_id).with_for_update()
    )
    if await session.get(LearningEntity, entity_id) is None:
        fail("ENTITY_NOT_FOUND", 404, "The canonical entity was not found.")
    row = await session.get(ExplicitInterestPreference, (user_id, entity_id))
    if row is None:
        if body.base_version != 0:
            fail("VERSION_CONFLICT")
        row = ExplicitInterestPreference(
            user_id=user_id, entity_id=entity_id, preference=body.preference, version=1
        )
        session.add(row)
    else:
        check_version(row, body.base_version)
        row.preference = body.preference
        row.version += 1
        row.updated_at = datetime.now(timezone.utc)
    await emit(
        session,
        user_id,
        "EXPLICIT_INTEREST_CHANGED",
        entity_id=entity_id,
        metadata={"preference": row.preference, "version": row.version},
    )
    await session.commit()
    return {
        "entity_id": str(entity_id),
        "preference": row.preference,
        "version": row.version,
    }


@router.get("/explorations", response_model=ExplorationPageDTO)
async def list_explorations(
    principal: Principal,
    session: Session,
    status: Literal["ACTIVE", "PAUSED", "COMPLETED"] | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    cursor: str | None = None,
):
    query = select(Exploration).where(Exploration.user_id == principal.user_id)
    if status is not None:
        query = query.where(Exploration.status == status)
    if cursor:
        try:
            decoded = json.loads(base64.urlsafe_b64decode(cursor.encode()))
            if (
                not isinstance(decoded, list)
                or len(decoded) != 2
                or not all(isinstance(value, str) for value in decoded)
            ):
                raise ValueError()
            timestamp, resource = decoded
            timestamp = datetime.fromisoformat(timestamp)
            resource = UUID(resource)
            if timestamp.tzinfo is None:
                raise ValueError()
        except (binascii.Error, ValueError, TypeError, KeyError, json.JSONDecodeError):
            fail("INVALID_CURSOR", 422, "The pagination cursor is invalid.")
        query = query.where(
            or_(
                Exploration.started_at < timestamp,
                and_(Exploration.started_at == timestamp, Exploration.id < resource),
            )
        )
    rows = list(
        (
            await session.scalars(
                query.order_by(
                    Exploration.started_at.desc(), Exploration.id.desc()
                ).limit(limit + 1)
            )
        ).all()
    )
    more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = (
        base64.urlsafe_b64encode(
            json.dumps([rows[-1].started_at.isoformat(), str(rows[-1].id)]).encode()
        ).decode()
        if more
        else None
    )
    return {"items": [exploration_dto(row) for row in rows], "next_cursor": next_cursor}


@router.get("/explorations/{exploration_id}", response_model=ExplorationDetailDTO)
async def get_exploration(exploration_id: UUID, principal: Principal, session: Session):
    from app.learning.content import public_delivery

    # One statement gives parent, reflection and session the same MVCC snapshot.
    result = (
        (
            await session.execute(
                text("""
        select e.*,
          case when v.entity_id is not null then jsonb_build_object(
            'id',e.entity_id,'title',v.title,'summary',v.summary,
            'entity_version',v.version) end as entity_summary,
          (select jsonb_build_object('id',r.id,'exploration_id',r.exploration_id,
            'entity_id',r.entity_id,'text',r.text,'version',r.version,
            'created_at',r.created_at,'updated_at',r.updated_at)
           from reflections r where r.user_id=e.user_id and r.exploration_id=e.id
           order by r.created_at desc,r.id desc limit 1) as latest_reflection,
          (select jsonb_build_object('id',s.id,'status',s.status)
           from assessment_sessions s where s.user_id=e.user_id and s.exploration_id=e.id
           order by s.started_at desc,s.id desc limit 1) as assessment_reference
        from explorations e
        left join learning_entities le on le.id=e.entity_id
        left join learning_entity_versions v on v.entity_id=le.id and v.version=le.current_version
        where e.user_id=:user_id and e.id=:exploration_id
    """),
                {"user_id": principal.user_id, "exploration_id": exploration_id},
            )
        )
        .mappings()
        .first()
    )
    if result is None:
        fail("EXPLORATION_NOT_FOUND", 404, "The requested resource was not found.")
    row = SimpleNamespace(**result)
    if row.latest_reflection is not None:
        for key in ("created_at", "updated_at"):
            row.latest_reflection[key] = datetime.fromisoformat(
                row.latest_reflection[key]
            ).isoformat()
    return {
        **exploration_dto(row),
        "lifecycle_contract_version": LIFECYCLE_VERSION,
        "entity": row.entity_summary,
        "delivery": (
            public_delivery(row.delivery_snapshot) if row.delivery_snapshot else None
        ),
        "reflection": row.latest_reflection,
        "assessment_session": row.assessment_reference,
    }


@router.post("/explorations/{exploration_id}/delivery", response_model=DeliveryDTO)
async def delivery(
    exploration_id: UUID,
    body: EmptyBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    from app.learning.content import (
        get_definition,
        public_delivery,
        validate_definition,
    )

    command = await reserve(session, request, principal.user_id, {})
    if command.replay:
        return command.response_body
    row = await owned(
        session, Exploration, principal.user_id, exploration_id, lock=True
    )
    if row.delivery_snapshot is None:
        if row.status == "COMPLETED":
            fail("EXPLORATION_ALREADY_COMPLETED")
        try:
            definition = get_definition(row.entity_id, row.entity_version)
            if definition is None:
                fail(
                    "EXPLORATION_CONTENT_UNAVAILABLE",
                    503,
                    "Reviewed content for this historical entity version is unavailable.",
                )
            validate_definition(definition)
        except ValueError:
            fail(
                "EXPLORATION_CONTENT_UNAVAILABLE",
                503,
                "Reviewed content did not pass validation.",
            )
        objective = await session.get(
            LearningObjective, UUID(definition["objective_id"])
        )
        if (
            objective is None
            or objective.entity_id != row.entity_id
            or objective.entity_version != row.entity_version
        ):
            fail(
                "EXPLORATION_CONTENT_UNAVAILABLE",
                503,
                "Reviewed content does not match its pinned objective.",
            )
        row.delivery_snapshot = definition
        row.delivery_contract_version = "exploration-delivery/v1"
        row.version += 1
        await emit(
            session,
            principal.user_id,
            "EXPLORATION_WORK_PREPARED",
            command=command,
            exploration=row,
            metadata={
                "content_id": definition["content_id"],
                "content_version": definition["content_version"],
                "entity_version": row.entity_version,
                "delivery_contract_version": row.delivery_contract_version,
            },
        )
    return await finish(
        session,
        principal.user_id,
        command,
        public_delivery(row.delivery_snapshot),
        row.id,
    )


@router.post("/explorations/{exploration_id}/actions", response_model=ExplorationDTO)
async def actions(
    exploration_id: UUID,
    body: ActionBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    command = await reserve(
        session, request, principal.user_id, body.model_dump(mode="json")
    )
    if command.replay:
        return command.response_body
    row = await owned(
        session, Exploration, principal.user_id, exploration_id, lock=True
    )
    check_version(row, body.base_version)
    row.status = transition(row.status, body.action)
    now = datetime.now(timezone.utc)
    if body.action == "RETURN":
        row.returned_at = now
    elif body.action == "PAUSE":
        row.paused_at = now
    else:
        row.paused_at = None
    row.version += 1
    await emit(
        session,
        principal.user_id,
        {
            "RETURN": "USER_RETURNED",
            "PAUSE": "EXPLORATION_PAUSED",
            "RESUME": "EXPLORATION_RESUMED",
        }[body.action],
        command=command,
        exploration=row,
        metadata={"version": row.version, "status": row.status},
    )
    return await finish(
        session, principal.user_id, command, exploration_dto(row), row.id
    )


@router.post("/explorations/{exploration_id}/completion", response_model=ExplorationDTO)
async def completion(
    exploration_id: UUID,
    body: CompletionBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    command = await reserve(
        session, request, principal.user_id, body.model_dump(mode="json")
    )
    if command.replay:
        return command.response_body
    row = await owned(
        session, Exploration, principal.user_id, exploration_id, lock=True
    )
    if row.status != "COMPLETED":
        check_version(row, body.base_version)
        now = datetime.now(timezone.utc)
        sessions = (
            await session.scalars(
                select(AssessmentSession)
                .where(
                    AssessmentSession.user_id == principal.user_id,
                    AssessmentSession.exploration_id == row.id,
                )
                .order_by(AssessmentSession.id)
                .with_for_update()
            )
        ).all()
        ordinal = 0
        for assessment in sessions:
            if assessment.status == "ACTIVE":
                assessment.status = "ABANDONED"
                assessment.completed_at = now
                await emit(
                    session,
                    principal.user_id,
                    "ASSESSMENT_ABANDONED",
                    command=command,
                    ordinal=ordinal,
                    exploration=row,
                    assessment_session_id=assessment.id,
                )
                ordinal += 1
        row.status = "COMPLETED"
        row.completed_at = now
        row.version += 1
        await emit(
            session,
            principal.user_id,
            "EXPLORATION_COMPLETED",
            command=command,
            ordinal=ordinal,
            exploration=row,
            metadata={
                "version": row.version,
                "lifecycle_contract_version": LIFECYCLE_VERSION,
            },
        )
    return await finish(
        session, principal.user_id, command, exploration_dto(row), row.id
    )


@router.post("/explorations/{exploration_id}/reflections", response_model=ReflectionDTO)
async def submit_reflection(
    exploration_id: UUID,
    body: ReflectionBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    command = await reserve(
        session, request, principal.user_id, body.model_dump(mode="json")
    )
    if command.replay:
        return reflection_dto(
            await owned(session, Reflection, principal.user_id, command.result_id)
        )
    exploration = await owned(
        session, Exploration, principal.user_id, exploration_id, lock=True
    )
    now = datetime.now(timezone.utc)
    row = Reflection(
        id=uuid4(),
        user_id=principal.user_id,
        exploration_id=exploration.id,
        entity_id=exploration.entity_id,
        text=body.text,
        version=1,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await emit(
        session,
        principal.user_id,
        "REFLECTION_SUBMITTED",
        command=command,
        exploration=exploration,
        metadata={"reflection_id": str(row.id), "version": row.version},
    )
    await finish(
        session,
        principal.user_id,
        command,
        {"reflection_id": str(row.id)},
        row.id,
        result_type="REFLECTION_REFERENCE",
    )
    return reflection_dto(row)


@router.patch("/reflections/{reflection_id}", response_model=ReflectionDTO)
async def edit_reflection(
    reflection_id: UUID,
    body: ReflectionEditBody,
    principal: Principal,
    session: Session,
):
    row = await owned(session, Reflection, principal.user_id, reflection_id, lock=True)
    check_version(row, body.base_version)
    row.text = body.text
    row.version += 1
    row.updated_at = datetime.now(timezone.utc)
    exploration = await owned(
        session, Exploration, principal.user_id, row.exploration_id
    )
    await emit(
        session,
        principal.user_id,
        "REFLECTION_UPDATED",
        exploration=exploration,
        metadata={"reflection_id": str(row.id), "version": row.version},
    )
    await session.commit()
    return reflection_dto(row)
