"""Problem Details error responses for the Embyr API boundary.

Failures are deliberately restrained: they expose a stable category code and
never signature, JWKS, database, role, identity-propagation, or storage
credential internals.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.idempotency import (
    IdempotencyConflict,
    InvalidIdempotencyKey,
    MissingIdempotencyKey,
)
from app.auth.principal import AuthError, AuthFailure

_PROBLEM_TYPE = "about:blank"

_STATUS = 401

_TITLES: dict[AuthFailure, str] = {
    AuthFailure.MISSING_CREDENTIALS: "Authentication required",
    AuthFailure.MALFORMED_CREDENTIALS: "Malformed credentials",
    AuthFailure.INVALID_TOKEN: "Invalid credentials",
    AuthFailure.EXPIRED_TOKEN: "Expired credentials",
    AuthFailure.UNSUPPORTED_TOKEN: "Unsupported credentials",
    AuthFailure.UNMAPPED_IDENTITY: "Unmapped identity",
}


@dataclass
class AppError(Exception):
    """A stable application failure mapped to a Problem Details response."""

    code: str
    status: int
    title: str
    detail: str | None = None
    details: dict | None = field(default=None)


def _body(
    *,
    status: int,
    code: str,
    title: str,
    detail: str | None = None,
    details: dict | None = None,
) -> dict:
    body = {
        "type": _PROBLEM_TYPE,
        "title": title,
        "status": status,
        "code": code,
        "detail": detail or title,
        "request_id": str(uuid4()),
    }
    if details:
        body["details"] = details
    return body


def problem_response(failure: AuthFailure) -> JSONResponse:
    title = _TITLES[failure]
    return JSONResponse(
        status_code=_STATUS,
        content=_body(status=_STATUS, code=failure.value, title=title),
        headers={"WWW-Authenticate": "Bearer"},
    )


def app_problem_response(exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status,
        content=_body(
            status=exc.status,
            code=exc.code,
            title=exc.title,
            detail=exc.detail,
            details=exc.details,
        ),
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return problem_response(exc.failure)

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return app_problem_response(exc)

    @app.exception_handler(MissingIdempotencyKey)
    async def _handle_missing_key(
        request: Request, exc: MissingIdempotencyKey
    ) -> JSONResponse:
        return app_problem_response(
            AppError(
                code="MISSING_IDEMPOTENCY_KEY",
                status=400,
                title="Idempotency key required",
                detail="This command requires an Idempotency-Key header.",
            )
        )

    @app.exception_handler(InvalidIdempotencyKey)
    async def _handle_invalid_key(
        request: Request, exc: InvalidIdempotencyKey
    ) -> JSONResponse:
        return app_problem_response(
            AppError(
                code="INVALID_IDEMPOTENCY_KEY",
                status=400,
                title="Invalid idempotency key",
                detail="Idempotency-Key must be between 1 and 128 characters.",
            )
        )

    @app.exception_handler(IdempotencyConflict)
    async def _handle_conflict(
        request: Request, exc: IdempotencyConflict
    ) -> JSONResponse:
        return app_problem_response(
            AppError(
                code="IDEMPOTENCY_KEY_REUSED",
                status=409,
                title="Idempotency key reused",
                detail="The Idempotency-Key was reused for a different command.",
            )
        )
