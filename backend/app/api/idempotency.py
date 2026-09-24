"""Minimum reusable command-idempotency boundary.

Implements the frozen ``Idempotency-Key`` semantics on the existing
``idempotency_records`` table: the same key with the same request fingerprint
resolves to the same durable command result, while the same key with a
different fingerprint is a conflict. Reusable secrets (signed URLs and tokens)
are never persisted; callers regenerate them on replay.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Mapping
from uuid import UUID

from fastapi import Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

IDEMPOTENCY_HEADER = "Idempotency-Key"
MAX_IDEMPOTENCY_KEY_LENGTH = 128
IDEMPOTENCY_TTL = timedelta(hours=24)


class MissingIdempotencyKey(Exception):
    """No ``Idempotency-Key`` header was supplied for a required command."""


class InvalidIdempotencyKey(Exception):
    """The supplied ``Idempotency-Key`` violates the frozen length bound."""


class IdempotencyConflict(Exception):
    """The same key was reused for a different command or request body."""


@dataclass(frozen=True)
class IdempotencyReservation:
    record_id: UUID
    replay: bool
    result_type: str | None
    result_id: UUID | None
    response_status: int | None
    response_body: dict[str, Any] | None


_RESERVE_SQL = text(
    """
    insert into public.idempotency_records
      (user_id, idempotency_key, command_name, request_fingerprint, expires_at)
    values
      (:user_id, :idempotency_key, :command_name, :request_fingerprint,
       now() + make_interval(secs => :ttl_seconds))
    on conflict (user_id, idempotency_key) do update
      set command_name = excluded.command_name,
          request_fingerprint = excluded.request_fingerprint,
          result_type = null,
          result_id = null,
          response_status = null,
          response_body = null,
          created_at = now(),
          expires_at = excluded.expires_at
      where idempotency_records.expires_at <= now()
    returning id
    """
)

_SELECT_SQL = text(
    """
    select id, command_name, request_fingerprint, result_type, result_id,
           response_status, response_body
      from public.idempotency_records
     where user_id = :user_id and idempotency_key = :idempotency_key
    """
)

_UPDATE_RESULT_SQL = text(
    """
    update public.idempotency_records
       set result_type = :result_type,
           result_id = :result_id,
           response_status = :response_status,
           response_body = cast(:response_body as jsonb)
     where id = :record_id and user_id = :user_id
    """
)


def require_idempotency_key(request: Request) -> str:
    value = request.headers.get(IDEMPOTENCY_HEADER)
    if value is None or not value.strip():
        raise MissingIdempotencyKey()
    value = value.strip()
    if len(value) > MAX_IDEMPOTENCY_KEY_LENGTH:
        raise InvalidIdempotencyKey()
    return value


def request_fingerprint(command_name: str, payload: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        {"command": command_name, "payload": payload},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _row_to_reservation(row, *, replay: bool) -> IdempotencyReservation:
    return IdempotencyReservation(
        record_id=row.id,
        replay=replay,
        result_type=row.result_type,
        result_id=row.result_id,
        response_status=row.response_status,
        response_body=row.response_body,
    )


async def reserve_idempotent_command(
    session: AsyncSession,
    *,
    user_id: UUID,
    idempotency_key: str,
    command_name: str,
    fingerprint: str,
) -> IdempotencyReservation:
    """Reserve the key or return the stored replay.

    A brand-new (or expired) key reserves a fresh record with ``replay=False``.
    An unexpired existing key with a matching command and fingerprint returns
    ``replay=True`` and the stored result; anything else raises
    ``IdempotencyConflict``.
    """
    params = {
        "user_id": user_id,
        "idempotency_key": idempotency_key,
        "command_name": command_name,
        "request_fingerprint": fingerprint,
        "ttl_seconds": int(IDEMPOTENCY_TTL.total_seconds()),
    }
    inserted = (await session.execute(_RESERVE_SQL, params)).first()
    if inserted is not None:
        return IdempotencyReservation(
            record_id=inserted.id,
            replay=False,
            result_type=None,
            result_id=None,
            response_status=None,
            response_body=None,
        )

    existing = (
        await session.execute(
            _SELECT_SQL,
            {"user_id": user_id, "idempotency_key": idempotency_key},
        )
    ).first()
    if existing is None:
        raise IdempotencyConflict(
            "idempotency key could not be reserved or resolved"
        )
    if (
        existing.command_name != command_name
        or existing.request_fingerprint != fingerprint
    ):
        raise IdempotencyConflict(
            "idempotency key reused for a different command"
        )
    return _row_to_reservation(existing, replay=True)


async def find_idempotent_result(
    session: AsyncSession,
    *,
    user_id: UUID,
    idempotency_key: str,
    command_name: str,
    fingerprint: str,
) -> IdempotencyReservation | None:
    """Read-only replay lookup used to short-circuit a repeated command."""
    existing = (
        await session.execute(
            text(str(_SELECT_SQL) + " and expires_at > now()"),
            {"user_id": user_id, "idempotency_key": idempotency_key},
        )
    ).first()
    if existing is None:
        return None
    if (
        existing.command_name != command_name
        or existing.request_fingerprint != fingerprint
    ):
        raise IdempotencyConflict(
            "idempotency key reused for a different command"
        )
    return _row_to_reservation(existing, replay=True)


async def store_idempotent_result(
    session: AsyncSession,
    *,
    user_id: UUID,
    record_id: UUID,
    result_type: str,
    result_id: UUID,
    response_status: int,
    response_body: Mapping[str, Any],
) -> None:
    await session.execute(
        _UPDATE_RESULT_SQL,
        {
            "user_id": user_id,
            "record_id": record_id,
            "result_type": result_type,
            "result_id": result_id,
            "response_status": response_status,
            "response_body": json.dumps(response_body, default=str),
        },
    )
