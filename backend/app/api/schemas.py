"""Request and response DTOs for the frozen upload contract."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_validator

ARTIFACT_PURPOSE = "ARTIFACT"


class UploadAuthorizationRequest(BaseModel):
    """``POST /api/v1/uploads`` request body.

    ``extra="forbid"`` makes a client-supplied storage identifier (for example
    ``object_key``) an explicit validation error rather than silently ignored.
    """

    model_config = ConfigDict(extra="forbid")

    purpose: str
    content_type: str
    size_bytes: int

    @field_validator("purpose")
    @classmethod
    def _validate_purpose(cls, value: str) -> str:
        if value != ARTIFACT_PURPOSE:
            raise ValueError("purpose must be ARTIFACT")
        return value

    @field_validator("content_type")
    @classmethod
    def _validate_content_type(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("content_type must be non-empty")
        return value.strip()

    @field_validator("size_bytes")
    @classmethod
    def _validate_size(cls, value: int) -> int:
        if value <= 0:
            raise ValueError("size_bytes must be positive")
        return value


class UploadAuthorizationResponse(BaseModel):
    upload_id: UUID
    object_key: str
    status: str
    content_type: str
    size_bytes: int
    created_at: datetime
    signed_upload_url: str
    signed_upload_token: str
    signed_upload_expires_at: datetime
    expires_in: int


class UploadCompleteResponse(BaseModel):
    upload_id: UUID
    status: str
    completed_at: datetime | None


class UploadStatusResponse(BaseModel):
    upload_id: UUID
    status: str
    content_type: str
    size_bytes: int
    created_at: datetime
    completed_at: datetime | None
    validated_at: datetime | None
    rejected_at: datetime | None
