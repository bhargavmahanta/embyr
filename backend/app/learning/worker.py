"""PostgreSQL evaluation worker with bounded retries and lease fencing.

Run with a separately provisioned app_worker credential. Claims commit before
computation; finalization commits evaluation, evidence, session, job and ledger
in one transaction. Logs contain categories/references, never authored content.
"""

from __future__ import annotations

import argparse
import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import logging
import os
import signal
import time
from uuid import UUID, uuid4

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.models.identity import Job
from app.db.models.exploration import Exploration
from app.db.models.ontology import LearningObjective
from app.db.models.assessment import (
    AssessmentSession,
    AssessmentInteraction,
    AssessmentResponse,
    EvaluationRun,
    LearningEvidence,
)
from app.db.session import create_async_database_engine
from app.learning.common import emit
from app.learning.telemetry import LearningJSONFormatter
from app.learning.content import validate_definition
from app.learning.evaluation import evaluate, EvaluationResult, PermanentEvaluationError

LOGGER = logging.getLogger(__name__)
JOB_TYPE = "ASSESSMENT_EVALUATION"
WORKER_CONTRACT = "worker-execution/v1"
LEASE_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_DELAYS = (5, 30)


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    user_id: UUID | None
    payload: dict
    token: str
    attempt: int
    exhausted: bool = False


@dataclass(frozen=True)
class Context:
    response_id: UUID
    session_id: UUID
    run_id: UUID
    exploration_id: UUID
    entity_id: UUID
    objective_id: UUID
    prompt: dict
    content: dict
    support_used: str | None


class InvalidJob(Exception):
    """Queue references are malformed or do not identify one owned aggregate."""


async def claim_job(factory) -> Claim | None:
    async with factory() as session, session.begin():
        eligible = or_(
            and_(
                Job.status.in_(["PENDING", "RETRYABLE_FAILURE"]),
                Job.available_at <= func.now(),
            ),
            and_(
                Job.status == "RUNNING",
                Job.locked_at <= func.now() - timedelta(seconds=LEASE_SECONDS),
            ),
        )
        job = await session.scalar(
            select(Job)
            .where(Job.job_type == JOB_TYPE, eligible)
            .order_by(Job.available_at, Job.created_at, Job.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return None
        expired = job.status == "RUNNING"
        exhausted = job.attempt_count >= MAX_ATTEMPTS
        job.status = "RUNNING"
        job.locked_at = await session.scalar(select(func.now()))
        job.locked_by = str(uuid4())
        if not exhausted:
            job.attempt_count += 1
        claim = Claim(
            job.id,
            job.user_id,
            deepcopy(job.payload),
            job.locked_by,
            job.attempt_count,
            exhausted,
        )
        LOGGER.info(
            "evaluation_job_claimed",
            extra={
                "job_id": str(job.id),
                "attempt": job.attempt_count,
                "expired_lease": expired,
                "queue_age_seconds": max(
                    0, (job.locked_at - job.created_at).total_seconds()
                ),
                "worker_contract_version": WORKER_CONTRACT,
            },
        )
        return claim


def _ids(claim):
    try:
        if (
            claim.user_id is None
            or claim.payload["contract_version"] != WORKER_CONTRACT
        ):
            raise ValueError()
        return tuple(
            UUID(claim.payload[key])
            for key in ("assessment_session_id", "response_id", "evaluation_run_id")
        )
    except (ValueError, KeyError, TypeError, AttributeError) as exc:
        raise InvalidJob("Invalid job references") from exc


async def _get(session, model, user_id, resource_id, lock=False):
    query = select(model).where(model.id == resource_id, model.user_id == user_id)
    if lock:
        query = query.with_for_update()
    resource = await session.scalar(query)
    if resource is None:
        raise InvalidJob("Owned resource missing")
    return resource


async def load_context(factory, claim) -> Context:
    assessment_id, response_id, run_id = _ids(claim)
    async with factory() as session, session.begin():
        assessment = await _get(
            session, AssessmentSession, claim.user_id, assessment_id
        )
        response = await _get(session, AssessmentResponse, claim.user_id, response_id)
        run = await _get(session, EvaluationRun, claim.user_id, run_id)
        interaction = await _get(
            session, AssessmentInteraction, claim.user_id, response.interaction_id
        )
        exploration = await _get(
            session, Exploration, claim.user_id, assessment.exploration_id
        )
        objective = await session.get(LearningObjective, interaction.objective_id)
        if (
            response.assessment_session_id != assessment.id
            or run.response_id != response.id
            or interaction.assessment_session_id != assessment.id
            or objective is None
            or objective.entity_id != exploration.entity_id
            or objective.entity_version != assessment.entity_version
            or exploration.entity_version != assessment.entity_version
        ):
            raise InvalidJob("Owned parent or historical objective mismatch")
        if (
            run.evaluator_type != "DETERMINISTIC"
            or run.evaluator_version != "deterministic-evaluation/v1"
            or run.rubric_version != interaction.rubric_version
            or assessment.strategy_version != "assessment-strategy/v1"
            or response.response_type != "SINGLE_CHOICE"
            or exploration.delivery_snapshot is None
            or interaction.prompt_definition
            != exploration.delivery_snapshot.get("assessment")
        ):
            raise PermanentEvaluationError("Pinned content identity mismatch")
        try:
            definition = exploration.delivery_snapshot
            validate_definition(definition)
            prompt = interaction.prompt_definition
            if (
                definition["entity_id"] != str(exploration.entity_id)
                or definition["entity_version"] != exploration.entity_version
                or definition["objective_id"] != str(interaction.objective_id)
                or prompt["objective_id"] != str(interaction.objective_id)
                or str(prompt["rubric_version"]) != interaction.rubric_version
                or prompt["strategy_version"] != assessment.strategy_version
            ):
                raise ValueError("Pinned objective or rubric mismatch")
        except (ValueError, KeyError, TypeError) as exc:
            raise PermanentEvaluationError("Invalid historical delivery pins") from exc
        return Context(
            response.id,
            assessment.id,
            run.id,
            exploration.id,
            exploration.entity_id,
            objective.id,
            deepcopy(interaction.prompt_definition),
            deepcopy(response.response_content),
            response.support_used,
        )


async def fail_invalid_job(factory, claim):
    # Do not touch another aggregate when queue provenance cannot be established.
    async with factory() as session, session.begin():
        job = await session.scalar(
            select(Job)
            .where(Job.id == claim.job_id, Job.user_id == claim.user_id)
            .with_for_update()
        )
        now = await session.scalar(select(func.clock_timestamp()))
        if not valid_claim(job, claim, now):
            return False
        job.status = "FAILED"
        job.completed_at = now
        job.payload = {
            **job.payload,
            "failure_category": "INVALID_JOB",
            "retry_allowed": False,
        }
        job.locked_at = None
        job.locked_by = None
        LOGGER.error(
            "evaluation_job_invalid",
            extra={"job_id": str(claim.job_id), "failure_category": "INVALID_JOB"},
        )
        return True


def valid_claim(job, claim, now):
    return (
        job is not None
        and job.status == "RUNNING"
        and job.locked_by == claim.token
        and job.locked_at is not None
        and job.locked_at + timedelta(seconds=LEASE_SECONDS) > now
    )


async def finalize_claim(
    factory,
    claim,
    *,
    result: EvaluationResult | None = None,
    failure_category: str | None = None,
    retryable: bool = False,
) -> bool:
    assessment_id, response_id, run_id = _ids(claim)
    async with factory() as session, session.begin():
        # Match learner commands' order. Claiming never holds a job lock while
        # obtaining session/run locks, so expired-lease recovery cannot invert it.
        assessment = await _get(
            session, AssessmentSession, claim.user_id, assessment_id, True
        )
        # Immutable answers are SELECT-only for the worker. The session lock
        # serializes retries and finalization without expanding that grant.
        response = await _get(session, AssessmentResponse, claim.user_id, response_id)
        run = await _get(session, EvaluationRun, claim.user_id, run_id, True)
        job = await _get(session, Job, claim.user_id, claim.job_id, True)
        now = await session.scalar(select(func.clock_timestamp()))
        if not valid_claim(job, claim, now):
            return False
        if _ids(
            Claim(job.id, job.user_id, job.payload, claim.token, claim.attempt)
        ) != (assessment_id, response_id, run_id):
            raise InvalidJob("Queue identity changed")
        if (
            response.assessment_session_id != assessment.id
            or run.response_id != response.id
        ):
            raise InvalidJob("Queue parent mismatch")
        if run.status != "PENDING":
            # A previously finalized run is an existing durable result, not a
            # second evaluation or another event/evidence source.
            job.status = "SUCCEEDED" if run.status == "SUCCEEDED" else "FAILED"
            job.completed_at = now
            job.locked_at = None
            job.locked_by = None
            return True
        exploration = await _get(
            session, Exploration, claim.user_id, assessment.exploration_id
        )
        if result is not None:
            if assessment.status != "WAITING_FOR_EVALUATION":
                raise InvalidJob("Submitted assessment status mismatch")
            interaction = await _get(
                session, AssessmentInteraction, claim.user_id, response.interaction_id
            )
            if interaction.assessment_session_id != assessment.id:
                raise InvalidJob("Interaction parent mismatch")
            run.status = "SUCCEEDED"
            run.result = result.result
            run.confidence = result.confidence
            run.feedback = result.feedback
            await session.flush()
            if result.produces_evidence:
                session.add(
                    LearningEvidence(
                        id=uuid4(),
                        user_id=claim.user_id,
                        entity_id=exploration.entity_id,
                        objective_id=interaction.objective_id,
                        source_type="ASSESSMENT_RESPONSE",
                        source_id=response.id,
                        evaluation_run_id=run.id,
                        evidence_type="RECOGNITION",
                        evidence_strength="WEAK",
                        support_level=response.support_used,
                        evaluation_confidence=result.confidence,
                        status="ACTIVE",
                        created_at=now,
                    )
                )
                await session.flush()
            assessment.status = "COMPLETED"
            assessment.completed_at = now
            job.status = "SUCCEEDED"
            job.completed_at = now
            await emit(
                session,
                claim.user_id,
                "ASSESSMENT_EVALUATED",
                exploration=exploration,
                assessment_session_id=assessment.id,
                metadata={
                    "response_id": str(response.id),
                    "evaluation_run_id": str(run.id),
                    "evaluator_version": run.evaluator_version,
                    "rubric_version": run.rubric_version,
                    "evidence_contract_version": "assessment-evidence/v1",
                    "result": result.result,
                },
            )
            await emit(
                session,
                claim.user_id,
                "ASSESSMENT_COMPLETED",
                exploration=exploration,
                assessment_session_id=assessment.id,
                metadata={"evaluation_run_id": str(run.id)},
            )
        elif retryable and claim.attempt < MAX_ATTEMPTS and not claim.exhausted:
            job.status = "RETRYABLE_FAILURE"
            job.available_at = now + timedelta(seconds=RETRY_DELAYS[claim.attempt - 1])
            job.payload = {
                **job.payload,
                "failure_category": failure_category,
                "retry_allowed": True,
            }
        else:
            run.status = "FAILED"
            job.status = "FAILED"
            job.completed_at = now
            job.payload = {
                **job.payload,
                "failure_category": failure_category,
                "retry_allowed": retryable,
            }
            await emit(
                session,
                claim.user_id,
                "ASSESSMENT_EVALUATION_FAILED",
                exploration=exploration,
                assessment_session_id=assessment.id,
                metadata={
                    "response_id": str(response.id),
                    "evaluation_run_id": str(run.id),
                    "failure_category": failure_category,
                    "evaluator_version": run.evaluator_version,
                    "rubric_version": run.rubric_version,
                },
            )
        job.locked_at = None
        job.locked_by = None
        await session.flush()
        LOGGER.info(
            "evaluation_job_finalized",
            extra={
                "job_id": str(claim.job_id),
                "attempt": claim.attempt,
                "job_status": job.status,
                "failure_category": failure_category,
                "evaluator_version": run.evaluator_version,
                "rubric_version": run.rubric_version,
            },
        )
        return True


async def process_claim(factory, claim, evaluator=evaluate) -> bool:
    started = time.monotonic()
    try:
        try:
            context = await load_context(factory, claim)
            if claim.exhausted:
                return await finalize_claim(
                    factory,
                    claim,
                    failure_category="PROCESSING_UNAVAILABLE",
                    retryable=True,
                )
            result = evaluator(context.prompt, context.content, context.support_used)
        except InvalidJob:
            return await fail_invalid_job(factory, claim)
        except PermanentEvaluationError:
            return await finalize_claim(
                factory, claim, failure_category="INVALID_CONTENT", retryable=False
            )
        except Exception:
            return await finalize_claim(
                factory,
                claim,
                failure_category="PROCESSING_UNAVAILABLE",
                retryable=True,
            )
        return await finalize_claim(factory, claim, result=result)
    except InvalidJob:
        return await fail_invalid_job(factory, claim)
    except Exception:
        # If even recording a failure is unavailable, preserve the claim/run.
        # Its expired lease is recoverable. Never log exception bodies.
        LOGGER.error(
            "evaluation_finalization_unavailable",
            extra={
                "job_id": str(claim.job_id),
                "failure_category": "DATABASE_UNAVAILABLE",
            },
        )
        return False
    finally:
        LOGGER.info(
            "evaluation_processing_duration",
            extra={
                "job_id": str(claim.job_id),
                "latency_seconds": time.monotonic() - started,
            },
        )


async def run_once(factory, evaluator=evaluate) -> bool:
    claim = await claim_job(factory)
    if claim is None:
        return False
    await process_claim(factory, claim, evaluator)
    return True


async def serve(database_url, poll_seconds):
    engine = create_async_database_engine(database_url)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    try:
        while not stop.is_set():
            try:
                worked = await run_once(factory)
            except Exception:
                LOGGER.error(
                    "evaluation_claim_unavailable",
                    extra={"failure_category": "DATABASE_UNAVAILABLE"},
                )
                worked = False
            if not worked:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(
        description="Embyr deterministic evaluation worker"
    )
    parser.add_argument("--poll-seconds", type=float, default=1.0)
    args = parser.parse_args()
    if args.poll_seconds <= 0:
        parser.error("--poll-seconds must be positive")
    database_url = os.environ.get("EMBYR_WORKER_DATABASE_URL")
    if not database_url:
        parser.error(
            "EMBYR_WORKER_DATABASE_URL must use the separately provisioned app_worker credential"
        )
    handler = logging.StreamHandler()
    handler.setFormatter(LearningJSONFormatter())
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    asyncio.run(serve(database_url, args.poll_seconds))


if __name__ == "__main__":
    main()
