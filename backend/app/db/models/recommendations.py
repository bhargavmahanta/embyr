from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Recommendation(Base):
    __tablename__ = "recommendations"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_recommendations_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_recommendations_entity_version",
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["practical_challenges.id"],
            name="fk_recommendations_challenge_id_practical_challenges",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_recommendations_user_id_id"
        ),
        sa.CheckConstraint(
            "((entity_id is not null)::int + (challenge_id is not null)::int) = 1",
            name="target_exclusive",
        ),
        sa.CheckConstraint(
            "(entity_id is not null) = (entity_version is not null)",
            name="entity_version_presence",
        ),
        sa.CheckConstraint(
            "mode in ('CONTINUE', 'EXPLORE', 'CREATE', 'SURPRISE', 'REVISIT')",
            name="mode",
        ),
        sa.CheckConstraint(
            "distance_band in ('COMFORT', 'ADJACENT', 'FRONTIER', 'WILD')",
            name="distance_band",
        ),
        sa.CheckConstraint(
            "decision is null or decision in ('ACCEPT', 'SKIP')",
            name="decision",
        ),
        sa.CheckConstraint(
            "(decision is null) = (decided_at is null) and "
            "(decided_at is null or decided_at >= presented_at)",
            name="decision_timestamps",
        ),
        sa.Index(
            "ix_recommendations_user_presented",
            "user_id",
            sa.desc("presented_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int | None] = mapped_column(sa.Integer)
    challenge_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    mode: Mapped[str] = mapped_column(sa.Text)
    distance_band: Mapped[str] = mapped_column(sa.Text)
    ranking_model_version: Mapped[str] = mapped_column(sa.Text)
    score_components: Mapped[Any] = mapped_column(JSONB)
    reason_code: Mapped[str] = mapped_column(sa.Text)
    presentation_version: Mapped[str] = mapped_column(sa.Text)
    presentation: Mapped[Any] = mapped_column(JSONB)
    presented_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))
    decision: Mapped[str | None] = mapped_column(sa.Text)
