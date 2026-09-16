"""Create the immutable Experience Ledger.

Revision ID: 0007_experience_ledger
Revises: 0006_practical_artifacts
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0007_experience_ledger"
down_revision: str | None = "0006_practical_artifacts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


def upgrade() -> None:
    op.create_table(
        "learning_events",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("device_id", _uuid(), nullable=True),
        sa.Column("command_id", _uuid(), nullable=True),
        sa.Column("event_ordinal", sa.SmallInteger(), nullable=True),
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=True),
        sa.Column("exploration_id", _uuid(), nullable=True),
        sa.Column("assessment_session_id", _uuid(), nullable=True),
        sa.Column("artifact_id", _uuid(), nullable=True),
        sa.Column("learning_intent", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column(
            "metadata",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(command_id is null and event_ordinal is null) or "
            "(command_id is not null and event_ordinal is not null)",
            name=op.f("ck_learning_events_command_ordinal_pair"),
        ),
        sa.CheckConstraint(
            "event_ordinal is null or event_ordinal >= 0",
            name=op.f("ck_learning_events_event_ordinal"),
        ),
        sa.CheckConstraint(
            "learning_intent is null or learning_intent in "
            "('DIRECT_INTEREST', 'PREREQUISITE_SUPPORT', "
            "'RELATED_EXPLORATION', 'RETENTION_REVISIT', "
            "'PRACTICAL_SUPPORT', 'SERENDIPITY')",
            name=op.f("ck_learning_events_learning_intent"),
        ),
        sa.CheckConstraint(
            "schema_version > 0",
            name=op.f("ck_learning_events_schema_version"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            name=op.f("fk_learning_events_user_id_app_users"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["device_id", "user_id"],
            ["user_devices.id", "user_devices.user_id"],
            name=op.f("fk_learning_events_device_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["command_id"],
            ["idempotency_records.id"],
            name=op.f("fk_learning_events_command_id_idempotency_records"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["learning_entities.id"],
            name=op.f("fk_learning_events_entity_id_learning_entities"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id"],
            ["explorations.user_id", "explorations.id"],
            name=op.f("fk_learning_events_exploration_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id"],
            ["assessment_sessions.user_id", "assessment_sessions.id"],
            name=op.f("fk_learning_events_assessment_session_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "artifact_id"],
            ["artifacts.user_id", "artifacts.id"],
            name=op.f("fk_learning_events_artifact_owner"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_events")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_learning_events_user_id_id")
        ),
    )
    op.create_index(
        "uq_learning_events_command_ordinal",
        "learning_events",
        ["command_id", "event_ordinal"],
        unique=True,
        postgresql_where=sa.text("command_id is not null"),
    )
    op.create_index(
        "ix_learning_events_user_occurred",
        "learning_events",
        ["user_id", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_learning_events_user_type_occurred",
        "learning_events",
        ["user_id", "event_type", sa.text("occurred_at DESC")],
    )
    op.create_index(
        "ix_learning_events_entity_occurred",
        "learning_events",
        ["entity_id", sa.text("occurred_at DESC")],
    )

    op.execute(
        """
        create function validate_learning_event_command_owner()
        returns trigger
        language plpgsql
        as $$
        declare
            command_user_id uuid;
        begin
            if new.command_id is null then
                return new;
            end if;

            select user_id
              into command_user_id
              from idempotency_records
             where id = new.command_id
               for share;

            if not found then
                return new;
            end if;

            if command_user_id <> new.user_id then
                raise exception using
                    errcode = '23514',
                    message = 'command must belong to the learning event owner',
                    constraint = 'ck_learning_events_command_owner';
            end if;

            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_learning_events_command_owner
        before insert on learning_events
        for each row execute function validate_learning_event_command_owner()
        """
    )
    op.execute(
        """
        create function prevent_referenced_command_owner_change()
        returns trigger
        language plpgsql
        as $$
        begin
            if new.user_id is distinct from old.user_id
               and exists (
                    select 1
                      from learning_events
                     where command_id = old.id
               ) then
                raise exception using
                    errcode = '55000',
                    message = 'a referenced command owner is immutable',
                    constraint =
                        'ck_idempotency_records_referenced_owner_immutable';
            end if;

            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_idempotency_records_referenced_owner_immutable
        before update of user_id on idempotency_records
        for each row execute function prevent_referenced_command_owner_change()
        """
    )
    op.execute(
        """
        create function prevent_learning_event_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            raise exception using
                errcode = '55000',
                message = 'learning events are immutable',
                constraint = 'ck_learning_events_immutable';
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_learning_events_immutable
        before update or delete on learning_events
        for each row execute function prevent_learning_event_mutation()
        """
    )


def downgrade() -> None:
    op.execute("drop trigger trg_learning_events_immutable on learning_events")
    op.execute("drop function prevent_learning_event_mutation()")
    op.execute(
        "drop trigger trg_idempotency_records_referenced_owner_immutable "
        "on idempotency_records"
    )
    op.execute("drop function prevent_referenced_command_owner_change()")
    op.execute("drop trigger trg_learning_events_command_owner on learning_events")
    op.execute("drop function validate_learning_event_command_owner()")
    op.drop_index(
        "ix_learning_events_entity_occurred", table_name="learning_events"
    )
    op.drop_index(
        "ix_learning_events_user_type_occurred", table_name="learning_events"
    )
    op.drop_index(
        "ix_learning_events_user_occurred", table_name="learning_events"
    )
    op.drop_index(
        "uq_learning_events_command_ordinal", table_name="learning_events"
    )
    op.drop_table("learning_events")
