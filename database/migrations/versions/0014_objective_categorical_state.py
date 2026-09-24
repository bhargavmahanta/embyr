"""Represent objective-relative categorical state without numeric mastery inference.

Revision ID: 0014_objective_categorical_state
Revises: 0013_default_acl_hardening
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0014_objective_categorical_state"
down_revision: str | None = "0013_default_acl_hardening"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "learner_objective_state",
        sa.Column("categorical_state", sa.Text(), nullable=True),
    )
    op.create_check_constraint(
        "ck_learner_objective_state_categorical_state",
        "learner_objective_state",
        "categorical_state is null or categorical_state in "
        "('ENCOUNTERED', 'EXPLORING', 'DEVELOPING', 'UNDERSTOOD', "
        "'REVISITING', 'RETAINED', 'PAUSED')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_learner_objective_state_categorical_state",
        "learner_objective_state",
        type_="check",
    )
    op.drop_column("learner_objective_state", "categorical_state")
