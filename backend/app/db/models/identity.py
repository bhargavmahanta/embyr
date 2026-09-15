from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class AppUser(Base):
    __tablename__ = "app_users"
    __table_args__ = (
        sa.UniqueConstraint(
            "auth_provider",
            "auth_subject",
            name="uq_app_users_auth_provider_auth_subject",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    auth_provider: Mapped[str] = mapped_column(sa.Text)
    auth_subject: Mapped[str] = mapped_column(sa.Text)
    onboarding_completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        sa.UniqueConstraint("user_id", "id", name="uq_user_devices_user_id_id"),
        sa.CheckConstraint(
            "platform in ('ANDROID', 'IOS')",
            name="user_devices_platform",
        ),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("app_users.id", ondelete="CASCADE"),
    )
    platform: Mapped[str] = mapped_column(sa.Text)
    push_token: Mapped[str | None] = mapped_column(sa.Text)
    app_version: Mapped[str | None] = mapped_column(sa.Text)
    last_seen_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_idempotency_records_user_id_key",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_idempotency_records_user_id_id"
        ),
        sa.CheckConstraint(
            "length(idempotency_key) between 1 and 128",
            name="idempotency_records_key_length",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("app_users.id", ondelete="CASCADE"),
    )
    idempotency_key: Mapped[str] = mapped_column(sa.Text)
    command_name: Mapped[str] = mapped_column(sa.Text)
    request_fingerprint: Mapped[str] = mapped_column(sa.Text)
    result_type: Mapped[str | None] = mapped_column(sa.Text)
    result_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    response_status: Mapped[int | None] = mapped_column(sa.Integer)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    expires_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        sa.CheckConstraint(
            "status in ('PENDING', 'RUNNING', 'SUCCEEDED', "
            "'RETRYABLE_FAILURE', 'FAILED')",
            name="jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="jobs_attempt_count"),
        sa.Index(
            "ix_jobs_available_pending",
            "available_at",
            "created_at",
            postgresql_where=sa.text(
                "status in ('PENDING', 'RETRYABLE_FAILURE')"
            ),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("app_users.id", ondelete="CASCADE"),
    )
    job_type: Mapped[str] = mapped_column(sa.Text)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=sa.text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(sa.Text)
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, server_default=sa.text("0")
    )
    available_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    locked_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
