"""Private M6 read routes; auth session is never reused for read isolation."""

import re
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import ValidationError

from app.api.deps import get_principal
from app.api.m6_read_dtos import BIGINT, MemorySummary, WorldDeltaPage, WorldSnapshot
from app.auth.principal import AuthenticatedPrincipal
from app.learning.memory_read import memory_summary
from app.learning.read_transactions import integrity_error, read_transaction
from app.learning.world_read import world_changes, world_snapshot

router = APIRouter(prefix="/api/v1", tags=["Memory and World"])


@router.get("/memory/summary", response_model=MemorySummary)
async def memory(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
):
    try:
        async with read_transaction(
            request.app.state.session_factory, principal.user_id
        ) as session:
            return await memory_summary(session, principal.user_id)
    except ValidationError:
        raise integrity_error() from None


@router.get("/world", response_model=WorldSnapshot)
async def world(
    request: Request,
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
):
    try:
        async with read_transaction(
            request.app.state.session_factory, principal.user_id
        ) as session:
            return await world_snapshot(session, principal.user_id)
    except ValidationError:
        raise integrity_error() from None


def query_integer(value, *, minimum, maximum=None):
    # Compare decimal text before converting, so enormous positive limits
    # still clamp without Python's integer-string length limit or DB overflow.
    if not re.fullmatch(r"[0-9]+", value):
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


@router.get("/world/changes", response_model=WorldDeltaPage)
async def changes(
    request: Request,
    after_revision: Annotated[str, Query()],
    principal: Annotated[AuthenticatedPrincipal, Depends(get_principal)],
    limit: Annotated[str, Query()] = "500",
):
    cursor = query_integer(after_revision, minimum=0, maximum=BIGINT)
    page_size = query_integer(limit, minimum=1)
    try:
        async with read_transaction(
            request.app.state.session_factory, principal.user_id
        ) as session:
            return await world_changes(session, principal.user_id, cursor, page_size)
    except ValidationError:
        raise integrity_error() from None
