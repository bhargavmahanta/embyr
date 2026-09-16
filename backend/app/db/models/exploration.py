from __future__ import annotations

from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Exploration(Base):
    __tablename__ = "explorations"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_explorations_entity_version",
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_explorations_user_id_id"),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "entity_id",
            name="uq_explorations_user_id_id_entity_id",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "entity_version",
            name="uq_explorations_user_id_id_entity_version",
        ),
        sa.ForeignKeyConstraint(
            ["practical_challenge_id", "practical_challenge_version_id"],
            [
                "practical_challenge_versions.challenge_id",
                "practical_challenge_versions.id",
            ],
            name="fk_explorations_practical_challenge_version",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "practical_challenge_id",
            "practical_challenge_version_id",
            name="uq_explorations_owner_challenge_version",
        ),
        sa.CheckConstraint(
            "(practical_challenge_id is null and "
            "practical_challenge_version_id is null) or "
            "(practical_challenge_id is not null and "
            "practical_challenge_version_id is not null)",
            name="explorations_practical_challenge_pair",
        ),
        sa.CheckConstraint(
            "learning_intent in ('DIRECT_INTEREST', 'PREREQUISITE_SUPPORT', "
            "'RELATED_EXPLORATION', 'RETENTION_REVISIT', 'PRACTICAL_SUPPORT', "
            "'SERENDIPITY')",
            name="explorations_learning_intent",
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'PAUSED', 'COMPLETED')",
            name="explorations_status",
        ),
        sa.CheckConstraint(
            "(status = 'ACTIVE' and completed_at is null) or "
            "(status = 'PAUSED' and paused_at is not null and completed_at is null) or "
            "(status = 'COMPLETED' and completed_at is not null)",
            name="explorations_status_timestamps",
        ),
        sa.CheckConstraint(
            "(returned_at is null or returned_at >= started_at) and "
            "(paused_at is null or paused_at >= started_at) and "
            "(completed_at is null or completed_at >= started_at) and "
            "(paused_at is null or completed_at is null or paused_at <= completed_at)",
            name="explorations_timestamp_order",
        ),
        sa.CheckConstraint("version > 0", name="explorations_version"),
        sa.Index(
            "ix_explorations_user_status_started",
            "user_id",
            "status",
            sa.desc("started_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), sa.ForeignKey("app_users.id", ondelete="CASCADE")
    )
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int] = mapped_column(sa.Integer)
    recommendation_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    practical_challenge_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    practical_challenge_version_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True)
    )
    learning_intent: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    returned_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    paused_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    version: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("1"))


class Reflection(Base):
    __tablename__ = "reflections"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "entity_id"],
            ["explorations.user_id", "explorations.id", "explorations.entity_id"],
            ondelete="CASCADE",
            name="fk_reflections_exploration_owner_entity",
        ),
        sa.UniqueConstraint("user_id", "id", name="uq_reflections_user_id_id"),
        sa.UniqueConstraint(
            "user_id",
            "exploration_id",
            "id",
            name="uq_reflections_owner_exploration_id",
        ),
        sa.CheckConstraint("version > 0", name="reflections_version"),
        sa.Index("ix_reflections_user_exploration", "user_id", "exploration_id"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    exploration_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    text: Mapped[str] = mapped_column(sa.Text)
    version: Mapped[int] = mapped_column(sa.Integer, server_default=sa.text("1"))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
