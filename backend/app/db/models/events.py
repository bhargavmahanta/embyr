from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearningEvent(Base):
    __tablename__ = "learning_events"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name="fk_learning_events_user_id_app_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["user_devices.id", "user_devices.user_id"],
            name="fk_learning_events_device_owner",
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["idempotency_records.id"],
            name="fk_learning_events_command_id_idempotency_records",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_learning_events_entity_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id"],
            ["explorations.user_id", "explorations.id"],
            name="fk_learning_events_exploration_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id"],
            ["assessment_sessions.user_id", "assessment_sessions.id"],
            name="fk_learning_events_assessment_session_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            name="fk_learning_events_artifact_owner",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_learning_events_user_id_id"
        ),
        sa.CheckConstraint(
            "(command_id is null and event_ordinal is null) or "
            "(command_id is not null and event_ordinal is not null)",
            name="learning_events_command_ordinal_pair",
        ),
        sa.CheckConstraint(
            "event_ordinal is null or event_ordinal >= 0",
            name="learning_events_event_ordinal",
        ),
        sa.CheckConstraint(
            "learning_intent is null or learning_intent in "
            "('DIRECT_INTEREST', 'PREREQUISITE_SUPPORT', "
            "'RELATED_EXPLORATION', 'RETENTION_REVISIT', "
            "'PRACTICAL_SUPPORT', 'SERENDIPITY')",
            name="learning_events_learning_intent",
        ),
        sa.CheckConstraint(
            "schema_version > 0", name="learning_events_schema_version"
        ),
        sa.Index(
            "uq_learning_events_command_ordinal",
            "command_id",
            "event_ordinal",
            unique=True,
            postgresql_where=sa.text("command_id is not null"),
        ),
        sa.Index(
            "ix_learning_events_user_occurred",
            "user_id",
            sa.desc("occurred_at"),
        ),
        sa.Index(
            "ix_learning_events_user_type_occurred",
            "user_id",
            "event_type",
            sa.desc("occurred_at"),
        ),
        sa.Index(
            "ix_learning_events_entity_occurred",
            "entity_id",
            sa.desc("occurred_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    device_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    command_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    event_ordinal: Mapped[int | None] = mapped_column(sa.SmallInteger)
    event_type: Mapped[str] = mapped_column(sa.Text)
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    exploration_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    assessment_session_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    learning_intent: Mapped[str | None] = mapped_column(sa.Text)
    occurred_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    schema_version: Mapped[int] = mapped_column(sa.Integer)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=sa.text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
