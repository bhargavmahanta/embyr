"""Create the exploration and editable reflection lifecycle.

Revision ID: 0004_exploration
Revises: 0003_preferences
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0004_exploration"
down_revision: str | None = "0003_preferences"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "explorations",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("recommendation_id", _uuid()),
        sa.Column("practical_challenge_id", _uuid()),
        sa.Column("learning_intent", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("returned_at", sa.DateTime(timezone=True)),
        sa.Column("paused_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.CheckConstraint(
            "learning_intent in ('DIRECT_INTEREST', 'PREREQUISITE_SUPPORT', "
            "'RELATED_EXPLORATION', 'RETENTION_REVISIT', 'PRACTICAL_SUPPORT', "
            "'SERENDIPITY')",
            name="ck_explorations_learning_intent",
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'PAUSED', 'COMPLETED')",
            name="ck_explorations_status",
        ),
        sa.CheckConstraint(
            "(status = 'ACTIVE' and completed_at is null) or "
            "(status = 'PAUSED' and paused_at is not null and completed_at is null) or "
            "(status = 'COMPLETED' and completed_at is not null)",
            name="ck_explorations_status_timestamps",
        ),
        sa.CheckConstraint(
            "(returned_at is null or returned_at >= started_at) and "
            "(paused_at is null or paused_at >= started_at) and "
            "(completed_at is null or completed_at >= started_at) and "
            "(paused_at is null or completed_at is null or paused_at <= completed_at)",
            name="ck_explorations_timestamp_order",
        ),
        sa.CheckConstraint("version > 0", name="ck_explorations_version"),
        sa.ForeignKeyConstraint(
            ["entity_id", "entity_version"],
            ["learning_entity_versions.entity_id", "learning_entity_versions.version"],
            name="fk_explorations_entity_version",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_explorations_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_explorations"),
        sa.UniqueConstraint("user_id", "id", name="uq_explorations_user_id_id"),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "entity_id",
            name="uq_explorations_user_id_id_entity_id",
        ),
    )
    op.create_index(
        "ix_explorations_user_status_started",
        "explorations",
        ["user_id", "status", sa.text("started_at DESC")],
    )

    op.create_table(
        "reflections",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("exploration_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_reflections_version"),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "entity_id"],
            ["explorations.user_id", "explorations.id", "explorations.entity_id"],
            ondelete="CASCADE",
            name="fk_reflections_exploration_owner_entity",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_reflections"),
        sa.UniqueConstraint("user_id", "id", name="uq_reflections_user_id_id"),
    )
    op.create_index(
        "ix_reflections_user_exploration",
        "reflections",
        ["user_id", "exploration_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_reflections_user_exploration", table_name="reflections")
    op.drop_table("reflections")
    op.drop_index("ix_explorations_user_status_started", table_name="explorations")
    op.drop_table("explorations")
