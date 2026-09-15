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


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id", "response_id"],
            ["assessment_responses.user_id", "assessment_responses.id"],
            ondelete="CASCADE",
            name="fk_evaluation_runs_response_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "supersedes_id", "response_id"],
            ["evaluation_runs.user_id", "evaluation_runs.id", "evaluation_runs.response_id"],
            name="fk_evaluation_runs_superseded_owner_response",
        ),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "response_id",
            name="uq_evaluation_runs_owner_id_response",
        ),
        sa.UniqueConstraint(
            "supersedes_id", name="uq_evaluation_runs_supersedes_id"
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'SUCCEEDED', 'SUPERSEDED', 'REVOKED', "
            "'FAILED')",
            name="status",
        ),
        sa.CheckConstraint(
            "result is null or result in ('SUPPORTED', 'PARTIAL', "
            "'MISCONCEPTION', 'INSUFFICIENT_EVIDENCE', 'UNCERTAIN')",
            name="result",
        ),
        sa.CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name="confidence",
        ),
        sa.CheckConstraint(
            "status not in ('PENDING', 'SUCCEEDED', 'SUPERSEDED', 'REVOKED', "
            "'FAILED') or "
            "(status in ('PENDING', 'FAILED') and result is null and "
            "confidence is null and feedback is null) or "
            "(status in ('SUCCEEDED', 'SUPERSEDED', 'REVOKED') and "
            "result is not null and confidence is not null and feedback is not null)",
            name="payload",
        ),
        sa.CheckConstraint(
            "supersedes_id is null or supersedes_id <> id",
            name="not_self_superseding",
        ),
        sa.Index(
            "uq_evaluation_runs_active_response",
            "response_id",
            unique=True,
            postgresql_where=sa.text("status = 'SUCCEEDED'"),
        ),
        sa.Index(
            "ix_evaluation_runs_user_response_created",
            "user_id",
            "response_id",
            sa.desc("created_at"),
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    response_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    evaluator_type: Mapped[str] = mapped_column(sa.Text)
    evaluator_version: Mapped[str] = mapped_column(sa.Text)
    rubric_version: Mapped[str] = mapped_column(sa.Text)
    result: Mapped[str | None] = mapped_column(sa.Text)
    confidence: Mapped[float | None] = mapped_column(sa.Double)
    feedback: Mapped[str | None] = mapped_column(sa.Text)
    status: Mapped[str] = mapped_column(sa.Text)
    supersedes_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )


class LearningEvidence(Base):
    __tablename__ = "learning_evidence"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["entity_id", "objective_id"],
            ["learning_objectives.entity_id", "learning_objectives.id"],
            name="fk_learning_evidence_objective_entity",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "evaluation_run_id", "source_id"],
            [
                "evaluation_runs.user_id",
                "evaluation_runs.id",
                "evaluation_runs.response_id",
            ],
            name="fk_learning_evidence_evaluation_owner_source",
        ),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_learning_evidence_user_id_id"
        ),
        sa.CheckConstraint(
            "evidence_type in ('RECOGNITION', 'RECALL', 'EXPLANATION', "
            "'APPLICATION', 'ARGUMENT', 'PREDICTION', 'CREATION', "
            "'DEMONSTRATION', 'REFLECTION', 'RETENTION')",
            name="type",
        ),
        sa.CheckConstraint(
            "evidence_strength in ('WEAK', 'MODERATE', 'STRONG')",
            name="strength",
        ),
        sa.CheckConstraint(
            f"support_level is null or support_level in ({SUPPORT_LEVEL_SQL})",
            name="support_level",
        ),
        sa.CheckConstraint(
            "evaluation_confidence is null or "
            "(evaluation_confidence >= 0 and evaluation_confidence <= 1)",
            name="confidence",
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'SUPERSEDED', 'REVOKED')", name="status"
        ),
        sa.Index(
            "ix_learning_evidence_user_active_created",
            "user_id",
            sa.desc("created_at"),
            postgresql_where=sa.text("status = 'ACTIVE'"),
        ),
        sa.Index(
            "ix_learning_evidence_objective_status", "objective_id", "status"
        ),
        sa.Index("ix_learning_evidence_evaluation_run_id", "evaluation_run_id"),
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
    objective_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    source_type: Mapped[str] = mapped_column(sa.Text)
    source_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    evaluation_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    evidence_type: Mapped[str] = mapped_column(sa.Text)
    evidence_strength: Mapped[str] = mapped_column(sa.Text)
    support_level: Mapped[str | None] = mapped_column(sa.Text)
    evaluation_confidence: Mapped[float | None] = mapped_column(sa.Double)
    status: Mapped[str] = mapped_column(sa.Text)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
