"""Create immutable assessment responses and versioned evaluation evidence.

Revision ID: 0005_assessment_evidence
Revises: 0004_exploration
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "0005_assessment_evidence"
down_revision: str | None = "0004_exploration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid() -> postgresql.UUID:
    return postgresql.UUID(as_uuid=True)


SUPPORT_LEVEL_SQL = (
    "'SMALL_NUDGE', 'STRONG_HINT', 'MISSING_CONCEPT', 'EXPLANATION'"
)


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_explorations_user_id_id_entity_version"),
        "explorations",
        ["user_id", "id", "entity_version"],
    )

    op.create_table(
        "assessment_sessions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("exploration_id", _uuid(), nullable=False),
        sa.Column("entity_version", sa.Integer(), nullable=False),
        sa.Column("strategy_version", sa.Text(), nullable=False),
        sa.Column("confidence_before", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "entity_version > 0",
            name=op.f("ck_assessment_sessions_entity_version"),
        ),
        sa.CheckConstraint(
            "confidence_before in ('FUZZY', 'MAIN_IDEA', 'COULD_EXPLAIN', "
            "'CHALLENGE_ME')",
            name=op.f("ck_assessment_sessions_confidence_before"),
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'WAITING_FOR_EVALUATION', 'COMPLETED', "
            "'ABANDONED')",
            name=op.f("ck_assessment_sessions_status"),
        ),
        sa.CheckConstraint(
            "status not in ('ACTIVE', 'WAITING_FOR_EVALUATION', 'COMPLETED', "
            "'ABANDONED') or "
            "(status in ('ACTIVE', 'WAITING_FOR_EVALUATION') and "
            "completed_at is null) or "
            "(status in ('COMPLETED', 'ABANDONED') and completed_at is not null "
            "and completed_at >= started_at)",
            name=op.f("ck_assessment_sessions_lifecycle"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "exploration_id", "entity_version"],
            ["explorations.user_id", "explorations.id", "explorations.entity_version"],
            ondelete="CASCADE",
            name=op.f("fk_assessment_sessions_exploration_owner_version"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_sessions")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_assessment_sessions_user_id_id")
        ),
    )
    op.create_index(
        "ix_assessment_sessions_user_status_started",
        "assessment_sessions",
        ["user_id", "status", sa.text("started_at DESC")],
    )

    op.create_table(
        "assessment_interactions",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("assessment_session_id", _uuid(), nullable=False),
        sa.Column("objective_id", _uuid(), nullable=False),
        sa.Column("interaction_type", sa.Text(), nullable=False),
        sa.Column("prompt_definition", postgresql.JSONB(), nullable=False),
        sa.Column("rubric_version", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "sequence > 0", name=op.f("ck_assessment_interactions_sequence")
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id"],
            ["assessment_sessions.user_id", "assessment_sessions.id"],
            ondelete="CASCADE",
            name=op.f("fk_assessment_interactions_session_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["objective_id"],
            ["learning_objectives.id"],
            name=op.f(
                "fk_assessment_interactions_objective_id_learning_objectives"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_interactions")),
        sa.UniqueConstraint(
            "user_id",
            "assessment_session_id",
            "id",
            name=op.f("uq_assessment_interactions_owner_session_id"),
        ),
        sa.UniqueConstraint(
            "assessment_session_id",
            "sequence",
            name=op.f("uq_assessment_interactions_session_sequence"),
        ),
    )
    op.create_index(
        "ix_assessment_interactions_session_sequence",
        "assessment_interactions",
        ["assessment_session_id", "sequence"],
    )

    op.create_table(
        "assessment_support_requests",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("assessment_session_id", _uuid(), nullable=False),
        sa.Column("interaction_id", _uuid(), nullable=False),
        sa.Column("requested_level", sa.Text(), nullable=False),
        sa.Column("delivered_content", postgresql.JSONB(), nullable=False),
        sa.Column("support_source", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"requested_level in ({SUPPORT_LEVEL_SQL})",
            name=op.f("ck_assessment_support_requests_requested_level"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id", "interaction_id"],
            [
                "assessment_interactions.user_id",
                "assessment_interactions.assessment_session_id",
                "assessment_interactions.id",
            ],
            ondelete="CASCADE",
            name=op.f(
                "fk_assessment_support_requests_interaction_owner_session"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_support_requests")),
        sa.UniqueConstraint(
            "user_id",
            "id",
            name=op.f("uq_assessment_support_requests_user_id_id"),
        ),
    )
    op.create_index(
        "ix_assessment_support_requests_user_session_created",
        "assessment_support_requests",
        ["user_id", "assessment_session_id", "created_at"],
    )

    op.create_table(
        "assessment_responses",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("assessment_session_id", _uuid(), nullable=False),
        sa.Column("interaction_id", _uuid(), nullable=False),
        sa.Column("response_type", sa.Text(), nullable=False),
        sa.Column("response_content", postgresql.JSONB(), nullable=False),
        sa.Column("support_used", sa.Text()),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            f"support_used is null or support_used in ({SUPPORT_LEVEL_SQL})",
            name=op.f("ck_assessment_responses_support_used"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "assessment_session_id", "interaction_id"],
            [
                "assessment_interactions.user_id",
                "assessment_interactions.assessment_session_id",
                "assessment_interactions.id",
            ],
            ondelete="CASCADE",
            name=op.f("fk_assessment_responses_interaction_owner_session"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_assessment_responses")),
        sa.UniqueConstraint(
            "interaction_id",
            name=op.f("uq_assessment_responses_interaction_id"),
        ),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_assessment_responses_user_id_id")
        ),
    )
    op.create_index(
        "ix_assessment_responses_user_submitted",
        "assessment_responses",
        ["user_id", sa.text("submitted_at DESC")],
    )

    op.execute(
        """
        create function prevent_assessment_response_mutation()
        returns trigger
        language plpgsql
        as $$
        begin
            if tg_op = 'UPDATE' then
                raise exception using
                    errcode = '55000',
                    message = 'assessment responses are immutable';
            end if;
            if tg_op = 'DELETE' and current_user <> 'app_maintenance' then
                raise exception using
                    errcode = '55000',
                    message = 'assessment responses may be deleted only by app_maintenance';
            end if;
            return old;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_assessment_responses_immutable
        before update or delete on assessment_responses
        for each row execute function prevent_assessment_response_mutation()
        """
    )


def downgrade() -> None:
    op.execute(
        "drop trigger trg_assessment_responses_immutable on assessment_responses"
    )
    op.execute("drop function prevent_assessment_response_mutation()")
    op.drop_index(
        "ix_assessment_responses_user_submitted",
        table_name="assessment_responses",
    )
    op.drop_table("assessment_responses")
    op.drop_index(
        "ix_assessment_support_requests_user_session_created",
        table_name="assessment_support_requests",
    )
    op.drop_table("assessment_support_requests")
    op.drop_index(
        "ix_assessment_interactions_session_sequence",
        table_name="assessment_interactions",
    )
    op.drop_table("assessment_interactions")
    op.drop_index(
        "ix_assessment_sessions_user_status_started",
        table_name="assessment_sessions",
    )
    op.drop_table("assessment_sessions")
    op.drop_constraint(
        op.f("uq_explorations_user_id_id_entity_version"),
        "explorations",
        type_="unique",
    )
