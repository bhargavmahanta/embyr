from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class CuriosityStory(Base):
    __tablename__ = "curiosity_stories"
    __table_args__ = (
        sa.CheckConstraint("covered_to >= covered_from", name="window"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_curiosity_stories_user_id_app_users",
        ),
        sa.UniqueConstraint(
            "user_id",
            "story_type",
            "covered_from",
            "covered_to",
            "generator_version",
            name="uq_curiosity_stories_generation_window",
        ),
        sa.Index(
            "ix_curiosity_stories_user_type_created",
            "user_id",
            "story_type",
            sa.desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    story_type: Mapped[str] = mapped_column(sa.Text)
    covered_from: Mapped[date] = mapped_column(sa.Date)
    covered_to: Mapped[date] = mapped_column(sa.Date)
    content: Mapped[Any] = mapped_column(JSONB)
    generator_version: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class AccountOperationRequest(Base):
    __tablename__ = "account_operation_requests"
    __table_args__ = (
        sa.CheckConstraint(
            "operation_type in ('EXPORT', 'DELETE')",
            name="operation_type",
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name="status",
        ),
        sa.CheckConstraint(
            "result_object_key is null or "
            "(btrim(result_object_key) <> '' and "
            "position('://' in result_object_key) = 0)",
            name="private_result_object_key",
        ),
        sa.CheckConstraint(
            "error_code is null or btrim(error_code) <> ''",
            name="error_code",
        ),
        sa.CheckConstraint(
            "status not in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED') or "
            "(status = 'PENDING' and started_at is null and "
            "completed_at is null and result_object_key is null and "
            "error_code is null) or "
            "(status = 'RUNNING' and started_at is not null and "
            "completed_at is null and result_object_key is null and "
            "error_code is null) or "
            "(status = 'SUCCEEDED' and started_at is not null and "
            "completed_at is not null and error_code is null) or "
            "(status = 'FAILED' and started_at is not null and "
            "completed_at is not null and error_code is not null and "
            "result_object_key is null)",
            name="lifecycle",
        ),
        sa.CheckConstraint(
            "(started_at is null or started_at >= created_at) and "
            "(completed_at is null or completed_at >= started_at)",
            name="timestamp_order",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_account_operation_requests_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "idempotency_record_id"],
            ["idempotency_records.user_id", "idempotency_records.id"],
            name="fk_account_operation_requests_idempotency_owner",
        ),
        sa.UniqueConstraint(
            "idempotency_record_id",
            name="uq_account_operation_requests_idempotency_record_id",
        ),
        sa.Index(
            "ix_account_operation_requests_user_status_created",
            "user_id",
            "status",
            sa.desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    idempotency_record_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    operation_type: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    result_object_key: Mapped[str | None] = mapped_column(sa.Text)
    error_code: Mapped[str | None] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
