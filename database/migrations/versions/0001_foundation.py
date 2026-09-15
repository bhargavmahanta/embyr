"""Create extensions, internal identities, idempotency, and jobs.

Revision ID: 0001_foundation
Revises:
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0001_foundation"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("create extension if not exists pgcrypto")
    op.execute("create extension if not exists vector")

    op.create_table(
        "app_users",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("auth_provider", sa.Text(), nullable=False),
        sa.Column("auth_subject", sa.Text(), nullable=False),
        sa.Column("onboarding_completed_at", sa.DateTime(timezone=True)),
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
        sa.PrimaryKeyConstraint("id", name="pk_app_users"),
        sa.UniqueConstraint(
            "auth_provider",
            "auth_subject",
            name="uq_app_users_auth_provider_auth_subject",
        ),
    )

    op.create_table(
        "user_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("push_token", sa.Text()),
        sa.Column("app_version", sa.Text()),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "platform in ('ANDROID', 'IOS')", name="ck_user_devices_platform"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_users.id"], ondelete="CASCADE",
            name="fk_user_devices_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_devices"),
        sa.UniqueConstraint("user_id", "id", name="uq_user_devices_user_id_id"),
    )

    op.create_table(
        "idempotency_records",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("command_name", sa.Text(), nullable=False),
        sa.Column("request_fingerprint", sa.Text(), nullable=False),
        sa.Column("result_type", sa.Text()),
        sa.Column("result_id", postgresql.UUID(as_uuid=True)),
        sa.Column("response_status", sa.Integer()),
        sa.Column("response_body", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(idempotency_key) between 1 and 128",
            name="ck_idempotency_records_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_users.id"], ondelete="CASCADE",
            name="fk_idempotency_records_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_records"),
        sa.UniqueConstraint(
            "user_id", "id", name="uq_idempotency_records_user_id_id"
        ),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_idempotency_records_user_id_key",
        ),
    )

    op.create_table(
        "jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True)),
        sa.Column("job_type", sa.Text(), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("locked_at", sa.DateTime(timezone=True)),
        sa.Column("locked_by", sa.Text()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("attempt_count >= 0", name="ck_jobs_attempt_count"),
        sa.CheckConstraint(
            "status in ('PENDING', 'RUNNING', 'SUCCEEDED', "
            "'RETRYABLE_FAILURE', 'FAILED')",
            name="ck_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["app_users.id"], ondelete="CASCADE",
            name="fk_jobs_user_id_app_users",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_jobs"),
    )
    op.create_index(
        "ix_jobs_available_pending",
        "jobs",
        ["available_at", "created_at"],
        unique=False,
        postgresql_where=sa.text("status in ('PENDING', 'RETRYABLE_FAILURE')"),
    )


def downgrade() -> None:
    op.drop_index("ix_jobs_available_pending", table_name="jobs")
    op.drop_table("jobs")
    op.drop_table("idempotency_records")
    op.drop_table("user_devices")
    op.drop_table("app_users")
    op.execute("drop extension if exists vector")
    op.execute("drop extension if exists pgcrypto")
