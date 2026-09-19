"""Problem Details error responses for the authentication boundary.

Failures are deliberately restrained: they expose a stable category code and
never signature, JWKS, database, role, or identity-propagation internals.
"""
from __future__ import annotations

from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.auth.principal import AuthError, AuthFailure

_STATUS = 401

_TITLES: dict[AuthFailure, str] = {
    AuthFailure.MISSING_CREDENTIALS: "Authentication required",
    AuthFailure.MALFORMED_CREDENTIALS: "Malformed credentials",
    AuthFailure.INVALID_TOKEN: "Invalid credentials",
    AuthFailure.EXPIRED_TOKEN: "Expired credentials",
    AuthFailure.UNSUPPORTED_TOKEN: "Unsupported credentials",
    AuthFailure.UNMAPPED_IDENTITY: "Unmapped identity",
}


def problem_response(failure: AuthFailure) -> JSONResponse:
    title = _TITLES[failure]
    body = {
        "type": "about:blank",
        "title": title,
        "status": _STATUS,
        "code": failure.value,
        "detail": title,
        "request_id": str(uuid4()),
    }
    return JSONResponse(
        status_code=_STATUS,
        content=body,
        headers={"WWW-Authenticate": "Bearer"},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AuthError)
    async def _handle_auth_error(request: Request, exc: AuthError) -> JSONResponse:
        return problem_response(exc.failure)
