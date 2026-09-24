"""Retire expired idempotency generations without changing command identity.

Revision ID: 0017_idempotency_key_reuse
Revises: 0016_recommendation_reason
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "0017_idempotency_key_reuse"
down_revision: str | None = "0016_recommendation_reason"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

ACTIVE_INDEX = "uq_idempotency_records_active_user_key"
OLD_CONSTRAINT = "uq_idempotency_records_user_id_key"


def upgrade() -> None:
    op.add_column(
        "idempotency_records",
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.drop_constraint(OLD_CONSTRAINT, "idempotency_records", type_="unique")
    op.create_index(
        ACTIVE_INDEX,
        "idempotency_records",
        ["user_id", "idempotency_key"],
        unique=True,
        postgresql_where=sa.text("retired_at is null"),
    )


def downgrade() -> None:
    duplicate = op.get_bind().execute(sa.text("""
        select 1 from public.idempotency_records
         group by user_id, idempotency_key
        having count(*) > 1
         limit 1
    """)).first()
    if duplicate is not None:
        raise RuntimeError(
            "cannot restore unique idempotency key constraint while historical "
            "generations share a user/key"
        )
    op.drop_index(ACTIVE_INDEX, table_name="idempotency_records")
    op.create_unique_constraint(
        OLD_CONSTRAINT, "idempotency_records", ["user_id", "idempotency_key"]
    )
    op.drop_column("idempotency_records", "retired_at")
