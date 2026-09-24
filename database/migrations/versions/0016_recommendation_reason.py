"""Allow M3's valid zero-explanation outcome to persist without fallback copy.

Revision ID: 0016_recommendation_reason
Revises: 0015_recommendation_retrieval
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0016_recommendation_reason"
down_revision: str | None = "0015_recommendation_retrieval"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("recommendations", "reason_code", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.text("select 1 from public.recommendations where reason_code is null limit 1")).first():
        raise RuntimeError("cannot restore non-null reason_code while zero-code recommendations exist")
    op.alter_column("recommendations", "reason_code", existing_type=sa.Text(), nullable=False)
