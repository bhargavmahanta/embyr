"""Private M6 reads resolve verified identity in their isolated transaction."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BeforeValidator, ValidationError, WithJsonSchema

from app.api.deps import get_external_identity
from app.api.m6_read_dtos import (
    BIGINT,
    MemorySummary,
    WorldDeltaPage,
    WorldResyncRequired,
    WorldSnapshot,
)
from app.auth.principal import ExternalIdentity
from app.learning.memory_read import memory_summary
from app.learning.read_transactions import integrity_error, read_transaction
from app.learning.world_read import world_changes, world_snapshot

router = APIRouter(prefix="/api/v1", tags=["Memory and World"])


@router.get("/memory/summary", response_model=MemorySummary)
async def memory(
    request: Request,
    identity: Annotated[ExternalIdentity, Depends(get_external_identity)],
):
    try:
        async with read_transaction(request.app.state.session_factory, identity) as (
            session,
            user_id,
        ):
            return await memory_summary(session, user_id)
    except ValidationError:
        raise integrity_error() from None


@router.get("/world", response_model=WorldSnapshot)
async def world(
    request: Request,
    identity: Annotated[ExternalIdentity, Depends(get_external_identity)],
):
    try:
        async with read_transaction(request.app.state.session_factory, identity) as (
            session,
            user_id,
        ):
            return await world_snapshot(session, user_id)
    except ValidationError:
        raise integrity_error() from None


def query_integer(value, *, minimum, maximum=None):
    # Compare decimal text before converting, so enormous positive limits
    # still clamp without Python's integer-string length limit or DB overflow.
    if type(value) is int:
        value = str(value)
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]+", value):
        raise HTTPException(status_code=422, detail="Invalid integer query parameter")
    digits = value.lstrip("0") or "0"
    if minimum == 1 and digits == "0":
        raise HTTPException(status_code=422, detail="Invalid integer query parameter")
    bound = str(maximum if maximum is not None else 1000)
    if (len(digits), digits) > (len(bound), bound):
        if maximum is not None:
            raise HTTPException(
                status_code=422, detail="Invalid integer query parameter"
            )
        return 1000
    return int(digits)


AfterRevision = Annotated[
    int,
    BeforeValidator(lambda raw: query_integer(raw, minimum=0, maximum=BIGINT)),
    WithJsonSchema({"type": "integer", "minimum": 0}),
    Query(),
]
PageLimit = Annotated[
    int,
    BeforeValidator(lambda raw: query_integer(raw, minimum=1)),
    WithJsonSchema({"type": "integer", "minimum": 1}),
    Query(),
]


@router.get(
    "/world/changes",
    response_model=WorldDeltaPage,
    responses={409: {"model": WorldResyncRequired}},
)
async def changes(
    request: Request,
    after_revision: AfterRevision,
    identity: Annotated[ExternalIdentity, Depends(get_external_identity)],
    limit: PageLimit = 500,
):
    try:
        async with read_transaction(request.app.state.session_factory, identity) as (
            session,
            user_id,
        ):
            return await world_changes(session, user_id, after_revision, limit)
    except ValidationError:
        raise integrity_error() from None
