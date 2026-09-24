from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSTZRANGE
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LearnerInterestState(Base):
    __tablename__ = "learner_interest_state"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_interest_state_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_learner_interest_state_entity_id_learning_entities",
        ),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name="uq_learner_interest_state_user_entity",
        ),
        sa.CheckConstraint(
            "voluntary_revisit_count >= 0",
            name="voluntary_revisit_count",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    recent_affinity: Mapped[float] = mapped_column(sa.Double)
    long_term_affinity: Mapped[float] = mapped_column(sa.Double)
    user_initiated_strength: Mapped[float] = mapped_column(sa.Double)
    algorithm_exposure_strength: Mapped[float] = mapped_column(sa.Double)
    voluntary_revisit_count: Mapped[int] = mapped_column(
        sa.Integer, server_default=sa.text("0")
    )
    last_interaction_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    model_version: Mapped[str] = mapped_column(sa.Text)


class LearnerObjectiveState(Base):
    __tablename__ = "learner_objective_state"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_objective_state_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objectives.id"],
            name="fk_learner_objective_state_objective_id_learning_objectives",
        ),
        sa.UniqueConstraint(
            "user_id",
            "objective_id",
            name="uq_learner_objective_state_user_objective",
        ),
        sa.CheckConstraint(
            "evaluation_confidence is null or "
            "(evaluation_confidence >= 0 and evaluation_confidence <= 1)",
            name="evaluation_confidence",
        ),
        sa.CheckConstraint(
            "evidence_count >= 0",
            name="evidence_count",
        ),
        sa.CheckConstraint(
            "categorical_state is null or categorical_state in "
            "('ENCOUNTERED', 'EXPLORING', 'DEVELOPING', 'UNDERSTOOD', "
            "'REVISITING', 'RETAINED', 'PAUSED')",
            name="categorical_state",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    objective_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    understanding_estimate: Mapped[float] = mapped_column(sa.Double)
    categorical_state: Mapped[str | None] = mapped_column(sa.Text)
    evaluation_confidence: Mapped[float | None] = mapped_column(sa.Double)
    support_required: Mapped[bool] = mapped_column(
        sa.Boolean, server_default=sa.text("false")
    )
    last_evidence_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    evidence_count: Mapped[int] = mapped_column(
        sa.Integer, server_default=sa.text("0")
    )
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    model_version: Mapped[str] = mapped_column(sa.Text)


class LearnerRetentionState(Base):
    __tablename__ = "learner_retention_state"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_retention_state_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_learner_retention_state_entity_id_learning_entities",
        ),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name="uq_learner_retention_state_user_entity",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    retention_estimate: Mapped[float] = mapped_column(sa.Double)
    last_successful_recall: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    last_revisit: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True)
    )
    next_revisit_window: Mapped[Any | None] = mapped_column(TSTZRANGE)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    model_version: Mapped[str] = mapped_column(sa.Text)


class LearnerConfidenceState(Base):
    __tablename__ = "learner_confidence_state"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_confidence_state_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_learner_confidence_state_entity_id_learning_entities",
        ),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name="uq_learner_confidence_state_user_entity",
        ),
        sa.CheckConstraint(
            "self_reported_confidence is null or "
            "(self_reported_confidence >= 0 and self_reported_confidence <= 1)",
            name="self_reported",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    entity_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    self_reported_confidence: Mapped[float | None] = mapped_column(sa.Double)
    observed_understanding: Mapped[float | None] = mapped_column(sa.Double)
    calibration_state: Mapped[str | None] = mapped_column(sa.Text)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    model_version: Mapped[str] = mapped_column(sa.Text)


class LearnerChallengeState(Base):
    __tablename__ = "learner_challenge_state"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_challenge_state_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["area_id"],
            ["learning_entities.id"],
            name="fk_learner_challenge_state_area_id_learning_entities",
        ),
        sa.UniqueConstraint(
            "user_id",
            "area_id",
            name="uq_learner_challenge_state_user_area",
        ),
        sa.CheckConstraint(
            "estimate_confidence is null or "
            "(estimate_confidence >= 0 and estimate_confidence <= 1)",
            name="estimate_confidence",
        ),
        sa.CheckConstraint(
            "recent_support_rate is null or "
            "(recent_support_rate >= 0 and recent_support_rate <= 1)",
            name="recent_support_rate",
        ),
        sa.CheckConstraint(
            "recent_success_rate is null or "
            "(recent_success_rate >= 0 and recent_success_rate <= 1)",
            name="recent_success_rate",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    area_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    ability_estimate: Mapped[float] = mapped_column(sa.Double)
    estimate_confidence: Mapped[float | None] = mapped_column(sa.Double)
    recent_support_rate: Mapped[float | None] = mapped_column(sa.Double)
    recent_success_rate: Mapped[float | None] = mapped_column(sa.Double)
    computed_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
    model_version: Mapped[str] = mapped_column(sa.Text)


class StateEvidenceLink(Base):
    __tablename__ = "state_evidence_links"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_state_evidence_links_user_id_app_users",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "learning_evidence_id"],
            ["learning_evidence.user_id", "learning_evidence.id"],
            name="fk_state_evidence_links_evidence_owner",
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "learning_event_id"],
            ["learning_events.user_id", "learning_events.id"],
            name="fk_state_evidence_links_event_owner",
        ),
        sa.CheckConstraint(
            "((learning_evidence_id is not null)::int + "
            "(learning_event_id is not null)::int) = 1",
            name="single_source",
        ),
        sa.Index(
            "ix_state_evidence_links_user_dimension_target",
            "user_id",
            "state_dimension",
            "target_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    state_dimension: Mapped[str] = mapped_column(sa.Text)
    target_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True))
    learning_evidence_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    learning_event_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True))
    weight: Mapped[float | None] = mapped_column(sa.Double)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), server_default=sa.func.now()
    )
