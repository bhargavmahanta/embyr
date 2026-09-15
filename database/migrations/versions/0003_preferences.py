"""Create learner onboarding and explicit-interest preferences.

Revision ID: 0003_preferences
Revises: 0002_ontology
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0003_preferences"
down_revision: str | None = "0002_ontology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "learner_preferences",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("adventure_preference", sa.Text(), nullable=False),
        sa.Column("preferred_effort", sa.Text(), nullable=False),
        sa.Column("support_style", sa.Text(), nullable=False),
        sa.Column(
            "practical_opt_in",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("version > 0", name="ck_learner_preferences_version"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_learner_preferences_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint("user_id", name="pk_learner_preferences"),
    )

    op.create_table(
        "user_motivations",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("motivation_code", sa.Text(), nullable=False),
        sa.Column("free_text", sa.Text()),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_user_motivations_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "motivation_code", name="pk_user_motivations"
        ),
    )

    op.create_table(
        "explicit_interest_preferences",
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("preference", sa.Text(), nullable=False),
        sa.Column(
            "version", sa.Integer(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "preference in ('NEUTRAL', 'MORE', 'LESS', 'PAUSED', "
            "'NOT_INTERESTED')",
            name="ck_explicit_interest_preferences_preference",
        ),
        sa.CheckConstraint(
            "version > 0", name="ck_explicit_interest_preferences_version"
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name="fk_explicit_interest_preferences_entity_id_learning_entities",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name="fk_explicit_interest_preferences_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "entity_id", name="pk_explicit_interest_preferences"
        ),
    )


def downgrade() -> None:
    op.drop_table("explicit_interest_preferences")
    op.drop_table("user_motivations")
    op.drop_table("learner_preferences")
