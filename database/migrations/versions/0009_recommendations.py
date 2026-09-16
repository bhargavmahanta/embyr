"""Create persisted recommendation provenance.

Revision ID: 0009_recommendations
Revises: 0008_learner_state
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0009_recommendations"
down_revision: str | None = "0008_learner_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "recommendations",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=True),
        sa.Column("entity_version", sa.Integer(), nullable=True),
        sa.Column("challenge_id", _uuid(), nullable=True),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("distance_band", sa.Text(), nullable=False),
        sa.Column("ranking_model_version", sa.Text(), nullable=False),
        sa.Column("score_components", postgresql.JSONB(), nullable=False),
        sa.Column("reason_code", sa.Text(), nullable=False),
        sa.Column("presentation_version", sa.Text(), nullable=False),
        sa.Column("presentation", postgresql.JSONB(), nullable=False),
        sa.Column("presented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("decision", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "((entity_id is not null)::int + (challenge_id is not null)::int) = 1",
            name=op.f("ck_recommendations_target_exclusive"),
        ),
        sa.CheckConstraint(
            "(entity_id is not null) = (entity_version is not null)",
            name=op.f("ck_recommendations_entity_version_presence"),
        ),
        sa.CheckConstraint(
            "mode in ('CONTINUE', 'EXPLORE', 'CREATE', 'SURPRISE', 'REVISIT')",
            name=op.f("ck_recommendations_mode"),
        ),
        sa.CheckConstraint(
            "distance_band in ('COMFORT', 'ADJACENT', 'FRONTIER', 'WILD')",
            name=op.f("ck_recommendations_distance_band"),
        ),
        sa.CheckConstraint(
            "decision is null or decision in ('ACCEPT', 'SKIP')",
            name=op.f("ck_recommendations_decision"),
        ),
        sa.CheckConstraint(
            "(decision is null) = (decided_at is null) and "
            "(decided_at is null or decided_at >= presented_at)",
            name=op.f("ck_recommendations_decision_timestamps"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_recommendations_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name=op.f("fk_recommendations_entity_version"),
        ),
        sa.ForeignKeyConstraint(
            ["challenge_id"],
            ["practical_challenges.id"],
            name=op.f("fk_recommendations_challenge_id_practical_challenges"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_recommendations")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_recommendations_user_id_id")
        ),
    )
    op.create_index(
        "ix_recommendations_user_presented",
        "recommendations",
        ["user_id", sa.text("presented_at DESC")],
    )
    op.execute(
        "alter table explorations add constraint "
        "fk_explorations_recommendation_owner "
        "foreign key (user_id, recommendation_id) "
        "references recommendations (user_id, id) "
        "on delete set null (recommendation_id)"
    )


def downgrade() -> None:
    op.execute(
        "alter table explorations drop constraint fk_explorations_recommendation_owner"
    )
    op.drop_index("ix_recommendations_user_presented", table_name="recommendations")
    op.drop_table("recommendations")
