"""Create recomputable derived learner state and its evidence provenance.

Revision ID: 0008_learner_state
Revises: 0007_experience_ledger
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0008_learner_state"
down_revision: str | None = "0007_experience_ledger"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "learner_interest_state",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("recent_affinity", sa.Double(), nullable=False),
        sa.Column("long_term_affinity", sa.Double(), nullable=False),
        sa.Column("user_initiated_strength", sa.Double(), nullable=False),
        sa.Column("algorithm_exposure_strength", sa.Double(), nullable=False),
        sa.Column(
            "voluntary_revisit_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True)),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "voluntary_revisit_count >= 0",
            name=op.f("ck_learner_interest_state_voluntary_revisit_count"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_interest_state_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_learner_interest_state_entity_id_learning_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_interest_state")),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name=op.f("uq_learner_interest_state_user_entity"),
        ),
    )

    op.create_table(
        "learner_objective_state",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("objective_id", _uuid(), nullable=False),
        sa.Column("understanding_estimate", sa.Double(), nullable=False),
        sa.Column("evaluation_confidence", sa.Double()),
        sa.Column(
            "support_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("last_evidence_at", sa.DateTime(timezone=True)),
        sa.Column(
            "evidence_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "evaluation_confidence is null or "
            "(evaluation_confidence >= 0 and evaluation_confidence <= 1)",
            name=op.f("ck_learner_objective_state_evaluation_confidence"),
        ),
        sa.CheckConstraint(
            "evidence_count >= 0",
            name=op.f("ck_learner_objective_state_evidence_count"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_objective_state_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objectives.id"],
            name=op.f("fk_learner_objective_state_objective_id_learning_objectives"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_objective_state")),
        sa.UniqueConstraint(
            "user_id",
            "objective_id",
            name=op.f("uq_learner_objective_state_user_objective"),
        ),
    )

    op.create_table(
        "learner_retention_state",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("retention_estimate", sa.Double(), nullable=False),
        sa.Column("last_successful_recall", sa.DateTime(timezone=True)),
        sa.Column("last_revisit", sa.DateTime(timezone=True)),
        sa.Column("next_revisit_window", postgresql.TSTZRANGE()),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_retention_state_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_learner_retention_state_entity_id_learning_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_retention_state")),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name=op.f("uq_learner_retention_state_user_entity"),
        ),
    )

    op.create_table(
        "learner_confidence_state",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("self_reported_confidence", sa.Double()),
        sa.Column("observed_understanding", sa.Double()),
        sa.Column("calibration_state", sa.Text()),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "self_reported_confidence is null or "
            "(self_reported_confidence >= 0 and self_reported_confidence <= 1)",
            name=op.f("ck_learner_confidence_state_self_reported"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_confidence_state_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_learner_confidence_state_entity_id_learning_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_confidence_state")),
        sa.UniqueConstraint(
            "user_id",
            "entity_id",
            name=op.f("uq_learner_confidence_state_user_entity"),
        ),
    )

    op.create_table(
        "learner_challenge_state",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("area_id", _uuid(), nullable=False),
        sa.Column("ability_estimate", sa.Double(), nullable=False),
        sa.Column("estimate_confidence", sa.Double()),
        sa.Column("recent_support_rate", sa.Double()),
        sa.Column("recent_success_rate", sa.Double()),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "estimate_confidence is null or "
            "(estimate_confidence >= 0 and estimate_confidence <= 1)",
            name=op.f("ck_learner_challenge_state_estimate_confidence"),
        ),
        sa.CheckConstraint(
            "recent_support_rate is null or "
            "(recent_support_rate >= 0 and recent_support_rate <= 1)",
            name=op.f("ck_learner_challenge_state_recent_support_rate"),
        ),
        sa.CheckConstraint(
            "recent_success_rate is null or "
            "(recent_success_rate >= 0 and recent_success_rate <= 1)",
            name=op.f("ck_learner_challenge_state_recent_success_rate"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learner_challenge_state_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["area_id"],
            ["learning_entities.id"],
            name=op.f("fk_learner_challenge_state_area_id_learning_entities"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learner_challenge_state")),
        sa.UniqueConstraint(
            "user_id",
            "area_id",
            name=op.f("uq_learner_challenge_state_user_area"),
        ),
    )

    op.create_table(
        "state_evidence_links",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("state_dimension", sa.Text(), nullable=False),
        sa.Column("target_id", _uuid(), nullable=False),
        sa.Column("learning_evidence_id", _uuid()),
        sa.Column("learning_event_id", _uuid()),
        sa.Column("weight", sa.Double()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "((learning_evidence_id is not null)::int + "
            "(learning_event_id is not null)::int) = 1",
            name=op.f("ck_state_evidence_links_single_source"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_state_evidence_links_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "learning_evidence_id"],
            ["learning_evidence.user_id", "learning_evidence.id"],
            name=op.f("fk_state_evidence_links_evidence_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "learning_event_id"],
            ["learning_events.user_id", "learning_events.id"],
            name=op.f("fk_state_evidence_links_event_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_state_evidence_links")),
    )
    op.create_index(
        "ix_state_evidence_links_user_dimension_target",
        "state_evidence_links",
        ["user_id", "state_dimension", "target_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_state_evidence_links_user_dimension_target",
        table_name="state_evidence_links",
    )
    op.drop_table("state_evidence_links")
    op.drop_table("learner_challenge_state")
    op.drop_table("learner_confidence_state")
    op.drop_table("learner_retention_state")
    op.drop_table("learner_objective_state")
    op.drop_table("learner_interest_state")
