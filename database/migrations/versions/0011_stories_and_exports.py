"""Create generated Curiosity Stories and account operation requests.

Revision ID: 0011_stories_and_exports
Revises: 0010_worldmodel
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0011_stories_and_exports"
down_revision: str | None = "0010_worldmodel"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "curiosity_stories",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("story_type", sa.Text(), nullable=False),
        sa.Column("covered_from", sa.Date(), nullable=False),
        sa.Column("covered_to", sa.Date(), nullable=False),
        sa.Column("content", postgresql.JSONB(), nullable=False),
        sa.Column("generator_version", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "covered_to >= covered_from",
            name=op.f("ck_curiosity_stories_window"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_curiosity_stories_user_id_app_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_curiosity_stories")),
        sa.UniqueConstraint(
            "user_id",
            "story_type",
            "covered_from",
            "covered_to",
            "generator_version",
            name=op.f("uq_curiosity_stories_generation_window"),
        ),
    )
    op.create_index(
        "ix_curiosity_stories_user_type_created",
        "curiosity_stories",
        ["user_id", "story_type", sa.text("created_at DESC")],
    )

    op.create_table(
        "account_operation_requests",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("idempotency_record_id", _uuid(), nullable=False),
        sa.Column("operation_type", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("result_object_key", sa.Text(), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "operation_type in ('EXPORT', 'DELETE')",
            name=op.f("ck_account_operation_requests_operation_type"),
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')",
            name=op.f("ck_account_operation_requests_status"),
        ),
        sa.CheckConstraint(
            "result_object_key is null or "
            "(btrim(result_object_key) <> '' and "
            "position('://' in result_object_key) = 0)",
            name=op.f("ck_account_operation_requests_private_result_object_key"),
        ),
        sa.CheckConstraint(
            "error_code is null or btrim(error_code) <> ''",
            name=op.f("ck_account_operation_requests_error_code"),
        ),
        sa.CheckConstraint(
            "status not in ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED') or "
            "(status = 'PENDING' and started_at is null and "
            "completed_at is null and result_object_key is null and "
            "error_code is null) or "
            "(status = 'RUNNING' and started_at is not null and "
            "completed_at is null and result_object_key is null and "
            "error_code is null) or "
            "(status = 'SUCCEEDED' and started_at is not null and "
            "completed_at is not null and error_code is null) or "
            "(status = 'FAILED' and started_at is not null and "
            "completed_at is not null and error_code is not null and "
            "result_object_key is null)",
            name=op.f("ck_account_operation_requests_lifecycle"),
        ),
        sa.CheckConstraint(
            "(started_at is null or started_at >= created_at) and "
            "(completed_at is null or completed_at >= started_at)",
            name=op.f("ck_account_operation_requests_timestamp_order"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_account_operation_requests_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "idempotency_record_id"],
            ["idempotency_records.user_id", "idempotency_records.id"],
            ondelete="CASCADE",
            name=op.f("fk_account_operation_requests_idempotency_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_account_operation_requests")),
        sa.UniqueConstraint(
            "idempotency_record_id",
            name=op.f("uq_account_operation_requests_idempotency_record_id"),
        ),
    )
    op.create_index(
        "ix_account_operation_requests_user_status_created",
        "account_operation_requests",
        ["user_id", "status", sa.text("created_at DESC")],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_account_operation_requests_user_status_created",
        table_name="account_operation_requests",
    )
    op.drop_table("account_operation_requests")

    op.drop_index(
        "ix_curiosity_stories_user_type_created",
        table_name="curiosity_stories",
    )
    op.drop_table("curiosity_stories")
