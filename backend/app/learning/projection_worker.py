"""Dedicated PostgreSQL projection worker: claim, detached reduction, fenced commit.

Run with the separately provisioned app_worker credential. No import operator,
public routes, migrations or grant changes are part of this worker.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import timedelta
from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.db.session import create_async_database_engine
from app.learning.projection_inputs import (
    CONTRACTS,
    ProjectionError,
    integer,
    require,
    uuid_text,
)
from app.learning.projection_loader import load_prefix
from app.learning.projection_publisher import publish
from app.learning.projection_reducer import reduce_prefix
from app.learning.telemetry import LearningJSONFormatter

LOGGER = logging.getLogger(__name__)
LEASE_SECONDS = 60
MAX_ATTEMPTS = 3
RETRY_DELAYS = (5, 30)
PAYLOAD_KEYS = {
    "contract_version",
    "user_id",
    "source_group",
    "first_source_sequence",
    "last_source_sequence",
}


@dataclass(frozen=True)
class Claim:
    job_id: UUID
    user_id: str
    payload: dict
    token: str
    attempt: int
    generation: int
    horizon: int
    exhausted: bool = False


@dataclass(frozen=True)
class Prepared:
    projection: object | None
    prior: object | None
    pages: int = 0


def _payload(claim):
    p = claim.payload
    require(isinstance(p, dict) and set(p) == PAYLOAD_KEYS, "INVALID_JOB")
    require(
        p["contract_version"] == CONTRACTS["worker"]
        and uuid_text(p["user_id"]) == claim.user_id,
        "INVALID_JOB",
    )
    integer(p["first_source_sequence"])
    integer(p["last_source_sequence"])
    require(p["first_source_sequence"] <= p["last_source_sequence"], "INVALID_JOB")
    import re

    require(
        isinstance(p["source_group"], str)
        and re.fullmatch(r"[0-9]{1,20}", p["source_group"]),
        "INVALID_JOB",
    )
    return p


def _gate(head, checkpoint, p):
    if head is None or checkpoint is None or head["bootstrap_state"] != "READY":
        return False
    first, last = p["first_source_sequence"], p["last_source_sequence"]
    horizon = checkpoint["processed_source_sequence"]
    baseline = head["baseline_through_sequence"]
    if last > head["source_sequence"]:
        return False
    if last <= horizon:
        return True
    if checkpoint["blocking_group"] is not None:
        return False
    if baseline is not None and horizon < baseline:
        return first == 1 and last == baseline
    return first == horizon + 1


async def _metadata(session, user):
    head = (
        (
            await session.execute(
                text("select * from projection_source_heads where user_id=:u"),
                {"u": user},
            )
        )
        .mappings()
        .first()
    )
    cp = (
        (
            await session.execute(
                text("select * from learner_projection_checkpoints where user_id=:u"),
                {"u": user},
            )
        )
        .mappings()
        .first()
    )
    return head, cp


async def claim_job(factory):
    async with factory() as session, session.begin():
        result = await session.execute(
            text("""select j.*,c.generation,c.processed_source_sequence from jobs j
join learner_projection_checkpoints c on c.user_id=j.user_id
join projection_source_heads h on h.user_id=j.user_id
where j.job_type='LEARNER_PROJECTION' and h.bootstrap_state='READY'
and ((j.status in ('PENDING','RETRYABLE_FAILURE') and j.available_at<=clock_timestamp())
or (j.status='RUNNING' and j.locked_at<=clock_timestamp()-interval '60 seconds'))
and ((j.payload->>'last_source_sequence')::bigint<=c.processed_source_sequence
or (c.blocking_group is null and
((h.baseline_through_sequence is not null and c.processed_source_sequence<h.baseline_through_sequence
and (j.payload->>'first_source_sequence')::bigint=1 and (j.payload->>'last_source_sequence')::bigint=h.baseline_through_sequence)
or ((h.baseline_through_sequence is null or c.processed_source_sequence>=h.baseline_through_sequence)
and (j.payload->>'first_source_sequence')::bigint=c.processed_source_sequence+1))))
order by j.available_at,j.created_at,j.id for update of j skip locked limit 1""")
        )
        job = result.mappings().first()
        if job is None:
            return None
        exhausted = job["attempt_count"] >= MAX_ATTEMPTS
        attempt = job["attempt_count"] if exhausted else job["attempt_count"] + 1
        token = str(uuid4())
        await session.execute(
            text(
                "update jobs set status='RUNNING',attempt_count=:attempt,locked_by=:token,locked_at=clock_timestamp(),completed_at=null where user_id=:u and id=:id and job_type='LEARNER_PROJECTION'"
            ),
            {"attempt": attempt, "token": token, "u": job["user_id"], "id": job["id"]},
        )
        claim = Claim(
            job["id"],
            str(job["user_id"]),
            deepcopy(job["payload"]),
            token,
            attempt,
            job["generation"],
            job["processed_source_sequence"],
            exhausted,
        )
        LOGGER.info(
            "projection_claimed",
            extra={
                "job_id": str(claim.job_id),
                "attempt": attempt,
                "worker_contract_version": CONTRACTS["worker"],
            },
        )
        return claim


async def _group(session, claim, head):
    p = _payload(claim)
    u = UUID(claim.user_id)
    row = (
        (
            await session.execute(
                text(
                    "select min(source_sequence) as first,max(source_sequence) as last,count(*) as n from projection_inputs where user_id=:u and source_group=:g"
                ),
                {"u": u, "g": p["source_group"]},
            )
        )
        .mappings()
        .one()
    )
    end = (
        (
            await session.execute(
                text(
                    "select source_kind,source_group,facts,source_time from projection_inputs where user_id=:u and source_sequence=:last"
                ),
                {"u": u, "last": p["last_source_sequence"]},
            )
        )
        .mappings()
        .first()
    )
    require(
        end is not None
        and end["source_group"] == p["source_group"]
        and row["last"] == p["last_source_sequence"]
        and row["n"] == row["last"] - row["first"] + 1,
        "INVALID_GROUP",
    )
    if end["source_kind"] == "BOOTSTRAP":
        from app.learning.projection_inputs import timestamp

        require(
            p["first_source_sequence"] == 1
            and head["baseline_through_sequence"] == p["last_source_sequence"],
            "INVALID_BASELINE",
        )
        require(
            end["facts"]
            == {
                "cutoff_source_sequence": head["cutoff_source_sequence"],
                "cutoff_at": timestamp(head["cutoff_at"]),
            }
            and timestamp(end["source_time"]) == timestamp(head["cutoff_at"]),
            "INVALID_BASELINE",
        )
    else:
        require(row["first"] == p["first_source_sequence"], "INVALID_GROUP")


async def prepare(factory, claim, *, page_size=500):
    p = _payload(claim)
    async with factory() as session, session.begin():
        head, cp = await _metadata(session, UUID(claim.user_id))
        if not _gate(head, cp, p):
            return None
        if (
            cp["generation"] != claim.generation
            or cp["processed_source_sequence"] != claim.horizon
        ):
            return None
        await _group(session, claim, head)
        if p["last_source_sequence"] <= claim.horizon:
            return Prepared(None, None)
        rows, pages = await load_prefix(
            session, claim.user_id, p["last_source_sequence"], page_size=page_size
        )
        projection = reduce_prefix(claim.user_id, rows)
        prior = reduce_prefix(claim.user_id, rows[: claim.horizon])
        if claim.horizon:
            require(
                cp["input_fingerprint"] == prior.input_fingerprint
                and cp["output_fingerprint"] == prior.output_fingerprint,
                "CHECKPOINT_FINGERPRINT",
            )
        else:
            require(
                cp["input_fingerprint"] is None and cp["output_fingerprint"] is None,
                "CHECKPOINT_FINGERPRINT",
            )
        return Prepared(projection, prior, pages)


async def _locks(session, claim):
    u = UUID(claim.user_id)
    # The existing narrow RPC supplies compatible FOR KEY SHARE without new
    # app_worker UPDATE grants on app_users. It also fences trusted deletion.
    if not await session.scalar(text("select m6_lock_source_owner(:u)"), {"u": u}):
        return None
    cp = (
        (
            await session.execute(
                text(
                    "select * from learner_projection_checkpoints where user_id=:u for update"
                ),
                {"u": u},
            )
        )
        .mappings()
        .first()
    )
    world = (
        (
            await session.execute(
                text("select * from learner_worlds where user_id=:u for update"),
                {"u": u},
            )
        )
        .mappings()
        .first()
    )
    job = (
        (
            await session.execute(
                text(
                    "select * from jobs where user_id=:u and id=:j and job_type='LEARNER_PROJECTION' for update"
                ),
                {"u": u, "j": claim.job_id},
            )
        )
        .mappings()
        .first()
    )
    now = await session.scalar(text("select clock_timestamp()"))
    if cp is None or job is None:
        return None
    if not (
        job["status"] == "RUNNING"
        and job["locked_by"] == claim.token
        and job["attempt_count"] == claim.attempt
        and 1 <= claim.attempt <= MAX_ATTEMPTS
        and job["payload"] == claim.payload
        and job["locked_at"] is not None
        and job["locked_at"]
        <= now
        < job["locked_at"] + timedelta(seconds=LEASE_SECONDS)
    ):
        return None
    if (
        cp["generation"] != claim.generation
        or cp["processed_source_sequence"] != claim.horizon
    ):
        return None
    head = (
        (
            await session.execute(
                text("select * from projection_source_heads where user_id=:u"), {"u": u}
            )
        )
        .mappings()
        .first()
    )
    if not _gate(head, cp, _payload(claim)):
        return None
    return cp, world, head, now


async def _success(session, claim, now):
    await session.execute(
        text(
            "update jobs set status='SUCCEEDED',completed_at=:now,locked_at=null,locked_by=null where user_id=:u and id=:j and job_type='LEARNER_PROJECTION'"
        ),
        {"now": now, "u": UUID(claim.user_id), "j": claim.job_id},
    )


async def finalize(factory, claim, prepared):
    if prepared is None:
        return False
    async with factory() as session, session.begin():
        locked = await _locks(session, claim)
        if locked is None:
            return False
        cp, world, head, now = locked
        await _group(session, claim, head)
        p = _payload(claim)
        if p["last_source_sequence"] <= claim.horizon:
            await _success(session, claim, now)
            return True
        out = prepared.projection
        require(
            out is not None
            and out.user_id == claim.user_id
            and out.horizon == p["last_source_sequence"]
            and prepared.prior.horizon == claim.horizon,
            "PREFIX_IDENTITY",
        )
        require(
            cp["input_contract_version"] == CONTRACTS["input"]
            and cp["worker_contract_version"] == CONTRACTS["worker"]
            and cp["learner_contract_version"] == CONTRACTS["learner"]
            and cp["world_contract_version"] == CONTRACTS["world"],
            "CHECKPOINT_VERSION",
        )
        await publish(session, out, prepared.prior, world)
        await session.execute(
            text(
                "update learner_projection_checkpoints set processed_source_sequence=:h,input_fingerprint=:i,output_fingerprint=:o,blocking_group=null,failure_code=null,updated_at=clock_timestamp() where user_id=:u and generation=:g and processed_source_sequence=:prior"
            ),
            {
                "h": out.horizon,
                "i": out.input_fingerprint,
                "o": out.output_fingerprint,
                "u": UUID(claim.user_id),
                "g": claim.generation,
                "prior": claim.horizon,
            },
        )
        await _success(session, claim, now)
        LOGGER.info(
            "projection_published",
            extra={
                "job_id": str(claim.job_id),
                "worker_contract_version": CONTRACTS["worker"],
            },
        )
        return True


async def fail_claim(factory, claim, code, *, permanent=False):
    async with factory() as session, session.begin():
        locked = await _locks(session, claim)
        if locked is None:
            return False
        cp, _, _, now = locked
        terminal = permanent or claim.attempt >= MAX_ATTEMPTS
        status = "FAILED" if terminal else "RETRYABLE_FAILURE"
        available = (
            now
            if terminal
            else now + timedelta(seconds=RETRY_DELAYS[claim.attempt - 1])
        )
        await session.execute(
            text(
                "update jobs set status=:status,available_at=:available,completed_at=:completed,locked_at=null,locked_by=null where user_id=:u and id=:j and job_type='LEARNER_PROJECTION'"
            ),
            {
                "status": status,
                "available": available,
                "completed": now if terminal else None,
                "u": UUID(claim.user_id),
                "j": claim.job_id,
            },
        )
        if (
            terminal
            and _payload(claim)["last_source_sequence"]
            > cp["processed_source_sequence"]
        ):
            await session.execute(
                text(
                    "update learner_projection_checkpoints set blocking_group=:g,failure_code=:code,updated_at=clock_timestamp() where user_id=:u"
                ),
                {
                    "g": _payload(claim)["source_group"],
                    "code": code,
                    "u": UUID(claim.user_id),
                },
            )
        LOGGER.warning(
            "projection_failed",
            extra={
                "job_id": str(claim.job_id),
                "failure_category": code,
                "attempt": claim.attempt,
            },
        )
        return True


async def process_claim(factory, claim, *, page_size=500):
    try:
        if claim.exhausted and _payload(claim)["last_source_sequence"] > claim.horizon:
            return await fail_claim(factory, claim, "RETRY_EXHAUSTED", permanent=True)
        prepared = await prepare(factory, claim, page_size=page_size)
        return await finalize(factory, claim, prepared)
    except ProjectionError as exc:
        return await fail_claim(factory, claim, exc.code, permanent=True)
    except (DBAPIError, RuntimeError) as exc:
        code = getattr(getattr(exc, "orig", None), "sqlstate", None)
        permanent = code in ["23503", "23505", "23514", "42501"]
        category = (
            "WORKER_PRIVILEGE"
            if code == "42501"
            else "PROJECTION_INTEGRITY"
            if permanent
            else "PROCESSING_FAILURE"
        )
        try:
            return await fail_claim(factory, claim, category, permanent=permanent)
        except DBAPIError:
            LOGGER.warning(
                "projection_failure_deferred",
                extra={
                    "job_id": str(claim.job_id),
                    "failure_category": "DATABASE_UNAVAILABLE",
                },
            )
            return False


async def run_once(factory):
    claim = await claim_job(factory)
    return False if claim is None else await process_claim(factory, claim)


async def _run(url, once):
    engine = create_async_database_engine(url)
    try:
        factory = async_sessionmaker(engine, expire_on_commit=False)
        while True:
            progressed = await run_once(factory)
            if once:
                break
            if not progressed:
                await asyncio.sleep(1)
    finally:
        await engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    handler = logging.StreamHandler()
    handler.setFormatter(LearningJSONFormatter())
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    asyncio.run(_run(os.environ["EMBYR_DATABASE_URL"], args.once))


if __name__ == "__main__":
    main()
