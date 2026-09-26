"""Owned optional recognition checks with immutable answers and recoverable runs."""

from datetime import datetime, timezone, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from sqlalchemy import select, text

from app.api.learning import StrictBody, EmptyBody, Principal, Session
from app.api.learning_dtos import (
    AssessmentSessionDTO,
    SupportDTO,
    AnswerAcknowledgmentDTO,
    AssessmentResponseDTO,
    EvaluationRetryDTO,
)
from app.db.models.assessment import (
    AssessmentSession,
    AssessmentInteraction,
    AssessmentSupportRequest,
    AssessmentResponse,
    EvaluationRun,
    SUPPORT_LEVELS,
)
from app.db.models.exploration import Exploration
from app.db.models.identity import Job
from app.learning.common import owned, reserve, finish, emit, fail
from app.learning.content import validate_assessment

router = APIRouter(prefix="/api/v1", tags=["assessments"])


class StartBody(StrictBody):
    confidence_before: Literal["FUZZY", "MAIN_IDEA", "COULD_EXPLAIN", "CHALLENGE_ME"]


class SupportBody(StrictBody):
    interaction_id: UUID
    level: Literal["SMALL_NUDGE", "STRONG_HINT", "MISSING_CONCEPT", "EXPLANATION"]


class Choice(StrictBody):
    option_id: str


class AnswerBody(StrictBody):
    interaction_id: UUID
    response_type: Literal["SINGLE_CHOICE"]
    content: Choice


def public_interaction(row):
    definition = row.prompt_definition
    return {
        "id": str(row.id),
        "interaction_type": row.interaction_type,
        **{
            key: definition[key]
            for key in (
                "prompt",
                "strategy_version",
                "interaction_contract_version",
                "evaluator_version",
                "evidence_contract_version",
            )
        },
        "options": [
            {"id": o["id"], "label": o["label"]} for o in definition["options"]
        ],
    }


async def locked_session(db, user, sid):
    reference = await owned(db, AssessmentSession, user, sid)
    parent = await owned(db, Exploration, user, reference.exploration_id, lock=True)
    assessment = await owned(db, AssessmentSession, user, sid, lock=True)
    return parent, assessment


async def interaction(db, user, sid, iid):
    row = await owned(db, AssessmentInteraction, user, iid, lock=True)
    if row.assessment_session_id != sid:
        fail("INTERACTION_NOT_FOUND", 404)
    return row


async def session_read(db, user, sid):
    row = (
        (
            await db.execute(
                text("""
      select s.id,s.exploration_id,s.status,s.confidence_before,s.strategy_version,
      (select row_to_json(i) from assessment_interactions i where i.user_id=s.user_id and i.assessment_session_id=s.id order by sequence limit 1) as interaction,
      coalesce((select jsonb_agg(jsonb_build_object('id',h.id,'level',h.requested_level,'content',h.delivered_content) order by h.created_at,h.id) from assessment_support_requests h where h.user_id=s.user_id and h.assessment_session_id=s.id),'[]'::jsonb) as delivered_support,
      (select r.id from assessment_responses r where r.user_id=s.user_id and r.assessment_session_id=s.id limit 1) as response_id,
      (select jsonb_build_object('id',v.id,'status',v.status,'result',v.result,'confidence',v.confidence,'feedback',v.feedback,'failure_category',case when v.status='FAILED' then j.payload->>'failure_category' end,'retry_allowed',v.status='FAILED' and coalesce((j.payload->>'retry_allowed')::boolean,false))
       from assessment_responses r join evaluation_runs v on v.response_id=r.id and v.user_id=r.user_id
       left join jobs j on j.user_id=v.user_id and j.payload->>'evaluation_run_id'=v.id::text and j.job_type='ASSESSMENT_EVALUATION'
       where r.user_id=s.user_id and r.assessment_session_id=s.id order by v.created_at desc,v.id desc limit 1) as evaluation
      from assessment_sessions s join explorations e on e.id=s.exploration_id and e.user_id=s.user_id
      where s.user_id=:u and s.id=:id
    """),
                {"u": user, "id": sid},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        fail("ASSESSMENT_SESSION_NOT_FOUND", 404)
    result = dict(row)
    from types import SimpleNamespace

    result["interaction"] = public_interaction(SimpleNamespace(**result["interaction"]))
    ev = result["evaluation"]
    if ev and ev["status"] not in {"PENDING", "SUCCEEDED", "FAILED"}:
        ev = result["evaluation"] = None
    result.update(
        evaluation_status=ev["status"] if ev else None,
        feedback=ev["feedback"] if ev else None,
        retry_allowed=ev["retry_allowed"] if ev else False,
    )
    return result


@router.get("/assessment-sessions/{sid}", response_model=AssessmentSessionDTO)
async def get_session(sid: UUID, principal: Principal, session: Session):
    return await session_read(session, principal.user_id, sid)


@router.post(
    "/explorations/{eid}/assessment-sessions", response_model=AssessmentSessionDTO
)
async def start(
    eid: UUID, body: StartBody, request: Request, principal: Principal, session: Session
):
    user = principal.user_id
    command = await reserve(session, request, user, body.model_dump(mode="json"))
    if command.replay:
        return command.response_body
    parent = await owned(session, Exploration, user, eid, lock=True)
    existing = await session.scalar(
        select(AssessmentSession)
        .where(
            AssessmentSession.user_id == user, AssessmentSession.exploration_id == eid
        )
        .with_for_update()
    )
    if existing:
        if existing.confidence_before != body.confidence_before:
            fail("ASSESSMENT_START_CONFLICT")
        sid = existing.id
    else:
        if parent.status != "ACTIVE" or parent.delivery_snapshot is None:
            fail("ASSESSMENT_UNAVAILABLE")
        definition = parent.delivery_snapshot["assessment"]
        try:
            validate_assessment(definition)
        except ValueError:
            fail("ASSESSMENT_CONTENT_UNAVAILABLE", 503)
        sid = uuid4()
        session.add(
            AssessmentSession(
                id=sid,
                user_id=user,
                exploration_id=eid,
                entity_version=parent.entity_version,
                strategy_version=definition["strategy_version"],
                confidence_before=body.confidence_before,
                status="ACTIVE",
                started_at=datetime.now(timezone.utc),
            )
        )
        await session.flush()
        session.add(
            AssessmentInteraction(
                id=uuid4(),
                user_id=user,
                assessment_session_id=sid,
                objective_id=UUID(definition["objective_id"]),
                interaction_type="RECOGNITION",
                prompt_definition=definition,
                rubric_version=str(definition["rubric_version"]),
                sequence=1,
            )
        )
        await emit(
            session,
            user,
            "ASSESSMENT_STARTED",
            command=command,
            exploration=parent,
            assessment_session_id=sid,
            metadata={"strategy_version": definition["strategy_version"]},
        )
    return await finish(
        session, user, command, await session_read(session, user, sid), sid
    )


@router.post("/assessment-sessions/{sid}/support-requests", response_model=SupportDTO)
async def support(
    sid: UUID,
    body: SupportBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    user = principal.user_id
    command = await reserve(session, request, user, body.model_dump(mode="json"))
    if command.replay:
        return command.response_body
    parent, assessment = await locked_session(session, user, sid)
    item = await interaction(session, user, sid, body.interaction_id)
    if parent.status != "ACTIVE" or assessment.status != "ACTIVE":
        fail("ASSESSMENT_INACTIVE")
    existing = await session.scalar(
        select(AssessmentSupportRequest).where(
            AssessmentSupportRequest.user_id == user,
            AssessmentSupportRequest.interaction_id == item.id,
            AssessmentSupportRequest.requested_level == body.level,
        )
    )
    if existing is None:
        existing = AssessmentSupportRequest(
            id=uuid4(),
            user_id=user,
            assessment_session_id=sid,
            interaction_id=item.id,
            requested_level=body.level,
            delivered_content={"text": item.prompt_definition["support"][body.level]},
            support_source="REVIEWED_CONTENT",
        )
        session.add(existing)
        await emit(
            session,
            user,
            "HINT_REQUESTED",
            command=command,
            exploration=parent,
            assessment_session_id=sid,
            metadata={"interaction_id": str(item.id), "support_level": body.level},
        )
    return await finish(
        session,
        user,
        command,
        {
            "id": str(existing.id),
            "level": existing.requested_level,
            "content": existing.delivered_content,
        },
        existing.id,
    )


def acknowledgment(response):
    return {
        "response_id": str(response.id),
        "evaluation_status": "PENDING",
        "session_status": "WAITING_FOR_EVALUATION",
        "next_interaction": None,
    }


async def queue(db, user, response, assessment, item, previous=None):
    run = EvaluationRun(
        id=uuid4(),
        user_id=user,
        response_id=response.id,
        evaluator_type="DETERMINISTIC",
        evaluator_version="deterministic-evaluation/v1",
        rubric_version=item.rubric_version,
        status="PENDING",
        created_at=(
            max(
                datetime.now(timezone.utc),
                previous.created_at + timedelta(microseconds=1),
            )
            if previous
            else datetime.now(timezone.utc)
        ),
    )
    db.add(run)
    await db.flush()
    db.add(
        Job(
            id=uuid4(),
            user_id=user,
            job_type="ASSESSMENT_EVALUATION",
            status="PENDING",
            payload={
                "contract_version": "worker-execution/v1",
                "response_id": str(response.id),
                "evaluation_run_id": str(run.id),
                "assessment_session_id": str(assessment.id),
            },
        )
    )
    return run


@router.post(
    "/assessment-sessions/{sid}/responses",
    status_code=202,
    response_model=AnswerAcknowledgmentDTO,
)
async def answer(
    sid: UUID,
    body: AnswerBody,
    request: Request,
    principal: Principal,
    session: Session,
):
    user = principal.user_id
    command = await reserve(session, request, user, body.model_dump(mode="json"))
    if command.replay:
        return command.response_body
    parent, assessment = await locked_session(session, user, sid)
    item = await interaction(session, user, sid, body.interaction_id)
    content = body.content.model_dump()
    response = await session.scalar(
        select(AssessmentResponse).where(
            AssessmentResponse.user_id == user,
            AssessmentResponse.interaction_id == item.id,
        )
    )
    if response:
        if (
            response.response_content != content
            or response.response_type != body.response_type
        ):
            fail("ANSWER_CONFLICT")
    else:
        if content["option_id"] not in {
            o["id"] for o in item.prompt_definition["options"]
        }:
            fail("UNKNOWN_OPTION", 422)
        if parent.status != "ACTIVE" or assessment.status != "ACTIVE":
            fail("ASSESSMENT_INACTIVE")
        levels = (
            await session.scalars(
                select(AssessmentSupportRequest.requested_level).where(
                    AssessmentSupportRequest.user_id == user,
                    AssessmentSupportRequest.interaction_id == item.id,
                )
            )
        ).all()
        strongest = max(levels, key=SUPPORT_LEVELS.index) if levels else None
        response = AssessmentResponse(
            id=uuid4(),
            user_id=user,
            assessment_session_id=sid,
            interaction_id=item.id,
            response_type=body.response_type,
            response_content=content,
            support_used=strongest,
        )
        session.add(response)
        await session.flush()
        assessment.status = "WAITING_FOR_EVALUATION"
        run = await queue(session, user, response, assessment, item)
        await emit(
            session,
            user,
            "ASSESSMENT_RESPONSE_SUBMITTED",
            command=command,
            exploration=parent,
            assessment_session_id=sid,
            metadata={
                "response_id": str(response.id),
                "evaluation_run_id": str(run.id),
                "interaction_id": str(item.id),
            },
        )
    return await finish(
        session, user, command, acknowledgment(response), response.id, status=202
    )


@router.get("/assessment-responses/{rid}", response_model=AssessmentResponseDTO)
async def get_response(rid: UUID, principal: Principal, session: Session):
    row = (
        (
            await session.execute(
                text("""
    select r.id as response_id,r.assessment_session_id,s.status as session_status,r.support_used,
    v.id as evaluation_run_id,v.status as evaluation_status,v.result,v.confidence,v.feedback,
    case when v.status='FAILED' then j.payload->>'failure_category' end as failure_category,
    coalesce(v.status='FAILED' and coalesce((j.payload->>'retry_allowed')::boolean,false),false) as retry_allowed
    from assessment_responses r join assessment_sessions s on s.id=r.assessment_session_id and s.user_id=r.user_id
    join explorations e on e.id=s.exploration_id and e.user_id=s.user_id
    left join lateral (select * from evaluation_runs x where x.user_id=r.user_id and x.response_id=r.id order by x.created_at desc,x.id desc limit 1) v on true
    left join jobs j on j.user_id=r.user_id and j.job_type='ASSESSMENT_EVALUATION' and j.payload->>'evaluation_run_id'=v.id::text
    where r.id=:id and r.user_id=:u
    """),
                {"id": rid, "u": principal.user_id},
            )
        )
        .mappings()
        .first()
    )
    if row is None:
        fail("ASSESSMENT_RESPONSE_NOT_FOUND", 404)
    result = dict(row)
    if result["evaluation_status"] not in {"PENDING", "SUCCEEDED", "FAILED"}:
        for field in (
            "evaluation_run_id",
            "evaluation_status",
            "result",
            "confidence",
            "feedback",
            "failure_category",
        ):
            result[field] = None
        result["retry_allowed"] = False
    return result


@router.post(
    "/assessment-responses/{rid}/evaluation-retries",
    status_code=202,
    response_model=EvaluationRetryDTO,
)
async def retry(
    rid: UUID, body: EmptyBody, request: Request, principal: Principal, session: Session
):
    user = principal.user_id
    command = await reserve(session, request, user, {})
    if command.replay:
        return command.response_body
    ref = await owned(session, AssessmentResponse, user, rid)
    parent, assessment = await locked_session(session, user, ref.assessment_session_id)
    item = await interaction(session, user, assessment.id, ref.interaction_id)
    response = await owned(session, AssessmentResponse, user, rid)
    current = await session.scalar(
        select(EvaluationRun)
        .where(
            EvaluationRun.user_id == user,
            EvaluationRun.response_id == rid,
        )
        .order_by(EvaluationRun.created_at.desc(), EvaluationRun.id.desc())
        .limit(1)
        .with_for_update()
    )
    if current is None:
        fail("EVALUATION_RETRY_UNAVAILABLE")
    run = current
    if current.status != "PENDING":
        read = await get_response(rid, principal, session)
        if current.status != "FAILED" or not read["retry_allowed"]:
            fail("EVALUATION_RETRY_UNAVAILABLE")
        run = await queue(session, user, response, assessment, item, previous=current)
        await emit(
            session,
            user,
            "ASSESSMENT_EVALUATION_RETRY_REQUESTED",
            command=command,
            exploration=parent,
            assessment_session_id=assessment.id,
            metadata={"response_id": str(rid), "evaluation_run_id": str(run.id)},
        )
    return await finish(
        session,
        user,
        command,
        {**acknowledgment(response), "evaluation_run_id": str(run.id)},
        run.id,
        status=202,
    )
