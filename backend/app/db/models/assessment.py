from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


SUPPORT_LEVELS = (
    "SMALL_NUDGE",
    "STRONG_HINT",
    "MISSING_CONCEPT",
    "EXPLANATION",
)
SUPPORT_LEVEL_SQL = ", ".join(f"'{level}'" for level in SUPPORT_LEVELS)


class AssessmentSession(Base):
    __tablename__ = "assessment_sessions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "entity_version"],
            ["explorations.user_id", "explorations.id", "explorations.entity_version"],
            ondelete="CASCADE",
            name="fk_assessment_sessions_exploration_owner_version",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_assessment_sessions_user_id_id"
        ),
        sa.CheckConstraint("entity_version > 0", name="entity_version"),
        sa.CheckConstraint(
            "confidence_before in ('FUZZY', 'MAIN_IDEA', 'COULD_EXPLAIN', "
            "'CHALLENGE_ME')",
            name="confidence_before",
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'WAITING_FOR_EVALUATION', 'COMPLETED', "
            "'ABANDONED')",
            name="status",
        ),
        sa.CheckConstraint(
            "status not in ('ACTIVE', 'WAITING_FOR_EVALUATION', 'COMPLETED', "
            "'ABANDONED') or "
            "(status in ('ACTIVE', 'WAITING_FOR_EVALUATION') and "
            "completed_at is null) or "
            "(status in ('COMPLETED', 'ABANDONED') and completed_at is not null "
            "and completed_at >= started_at)",
            name="lifecycle",
        ),
        sa.Index(
            "ix_assessment_sessions_user_status_started",
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
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    exploration_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_version: Mapped[int] = mapped_column(sa.Integer)
    strategy_version: Mapped[str] = mapped_column(sa.Text)
    confidence_before: Mapped[str] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    started_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True))


class AssessmentInteraction(Base):
    __tablename__ = "assessment_interactions"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id"],
            ["assessment_sessions.user_id", "assessment_sessions.id"],
            ondelete="CASCADE",
            name="fk_assessment_interactions_session_owner",
        ),
        sa.UniqueConstraint(
            "user_id",
            "assessment_session_id",
            "id",
            name="uq_assessment_interactions_owner_session_id",
        ),
        sa.UniqueConstraint(
            "assessment_session_id",
            "sequence",
            name="uq_assessment_interactions_session_sequence",
        ),
        sa.CheckConstraint("sequence > 0", name="sequence"),
        sa.Index(
            "ix_assessment_interactions_session_sequence",
            "assessment_session_id",
            "sequence",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    assessment_session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    objective_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        sa.ForeignKey("learning_objectives.id"),
    )
    interaction_type: Mapped[str] = mapped_column(sa.Text)
    prompt_definition: Mapped[dict[str, Any]] = mapped_column(JSONB)
    rubric_version: Mapped[str] = mapped_column(sa.Text)
    sequence: Mapped[int] = mapped_column(sa.Integer)


class AssessmentSupportRequest(Base):
    __tablename__ = "assessment_support_requests"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id", "interaction_id"],
            [
                "assessment_interactions.user_id",
                "assessment_interactions.assessment_session_id",
                "assessment_interactions.id",
            ],
            ondelete="CASCADE",
            name="fk_assessment_support_requests_interaction_owner_session",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_assessment_support_requests_user_id_id"
        ),
        sa.CheckConstraint(
            f"requested_level in ({SUPPORT_LEVEL_SQL})", name="requested_level"
        ),
        sa.Index(
            "ix_assessment_support_requests_user_session_created",
            "user_id",
            "assessment_session_id",
            "created_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    assessment_session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    interaction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    requested_level: Mapped[str] = mapped_column(sa.Text)
    delivered_content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    support_source: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class AssessmentResponse(Base):
    __tablename__ = "assessment_responses"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id", "interaction_id"],
            [
                "assessment_interactions.user_id",
                "assessment_interactions.assessment_session_id",
                "assessment_interactions.id",
            ],
            ondelete="CASCADE",
            name="fk_assessment_responses_interaction_owner_session",
        ),
        sa.UniqueConstraint(
            "interaction_id", name="uq_assessment_responses_interaction_id"
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_assessment_responses_user_id_id"
        ),
        sa.CheckConstraint(
            f"support_used is null or support_used in ({SUPPORT_LEVEL_SQL})",
            name="support_used",
        ),
        sa.Index(
            "ix_assessment_responses_user_submitted",
            "user_id",
            sa.desc("submitted_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    assessment_session_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    interaction_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    response_type: Mapped[str] = mapped_column(sa.Text)
    response_content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    support_used: Mapped[str | None] = mapped_column(sa.Text)
    submitted_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
