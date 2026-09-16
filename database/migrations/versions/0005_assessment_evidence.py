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
        "ix_assessment_interactions_objective_id",
        "assessment_interactions",
        ["objective_id"],
    )

    op.execute(
        """
        create function validate_assessment_interaction_objective_version()
        returns trigger
        language plpgsql
        as $$
        declare
            assessed_entity_id uuid;
            assessed_entity_version integer;
            objective_entity_id uuid;
            objective_entity_version integer;
        begin
            select entity_id, entity_version
              into objective_entity_id, objective_entity_version
              from learning_objectives
             where id = new.objective_id;
            if not found then
                return new;
            end if;

            select e.entity_id, s.entity_version
              into assessed_entity_id, assessed_entity_version
              from assessment_sessions s
              join explorations e
                on e.user_id = s.user_id
               and e.id = s.exploration_id
               and e.entity_version = s.entity_version
             where s.user_id = new.user_id
               and s.id = new.assessment_session_id;
            if not found then
                return new;
            end if;

            if objective_entity_id <> assessed_entity_id
               or objective_entity_version <> assessed_entity_version then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_assessment_interactions_objective_version',
                    message = 'assessment objective must match the assessed entity version';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_assessment_interactions_objective_version
        before insert or update of user_id, assessment_session_id, objective_id
        on assessment_interactions
        for each row execute function validate_assessment_interaction_objective_version()
        """
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
        create function validate_assessment_response_objective_version()
        returns trigger
        language plpgsql
        as $$
        begin
            perform 1
              from assessment_interactions ai
             where ai.user_id = new.user_id
               and ai.assessment_session_id = new.assessment_session_id
               and ai.id = new.interaction_id;
            if not found then
                return new;
            end if;

            perform 1
              from assessment_interactions ai
              join assessment_sessions s
                on s.user_id = ai.user_id
               and s.id = ai.assessment_session_id
              join explorations e
                on e.user_id = s.user_id
               and e.id = s.exploration_id
              join learning_objectives o
                on o.id = ai.objective_id
               and o.entity_id = e.entity_id
               and o.entity_version = s.entity_version
             where ai.user_id = new.user_id
               and ai.assessment_session_id = new.assessment_session_id
               and ai.id = new.interaction_id
             for share of ai, s, e, o;
            if not found then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_assessment_responses_objective_version',
                    message = 'assessment response objective must match the assessed entity version';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_assessment_responses_objective_version
        before insert on assessment_responses
        for each row execute function validate_assessment_response_objective_version()
        """
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

    op.execute(
        """
        create function protect_answered_assessment_interaction()
        returns trigger
        language plpgsql
        as $$
        begin
            if exists (
                select 1
                  from assessment_responses ar
                 where ar.user_id = old.user_id
                   and ar.assessment_session_id = old.assessment_session_id
                   and ar.interaction_id = old.id
            ) then
                if tg_op = 'DELETE' then
                    if current_user <> 'app_maintenance' then
                        raise exception using
                            errcode = '55000',
                            constraint = 'ck_assessment_interactions_historical_prompt',
                            message = 'answered assessment interactions are historical';
                    end if;
                    return old;
                end if;
                if new is distinct from old then
                    raise exception using
                        errcode = '55000',
                        constraint = 'ck_assessment_interactions_historical_prompt',
                        message = 'answered assessment interactions are historical';
                end if;
            end if;
            if tg_op = 'DELETE' then
                return old;
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_assessment_interactions_historical_prompt
        before update or delete on assessment_interactions
        for each row execute function protect_answered_assessment_interaction()
        """
    )

    op.execute(
        """
        create function protect_assessed_objective_version()
        returns trigger
        language plpgsql
        as $$
        begin
            if (new.entity_id is distinct from old.entity_id
                or new.entity_version is distinct from old.entity_version)
               and exists (
                    select 1
                      from assessment_interactions ai
                      join assessment_responses ar
                        on ar.user_id = ai.user_id
                       and ar.assessment_session_id = ai.assessment_session_id
                       and ar.interaction_id = ai.id
                     where ai.objective_id = old.id
               ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_learning_objectives_assessment_history',
                    message = 'objectives referenced by assessment history cannot change entity version';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_learning_objectives_assessment_history
        before update of entity_id, entity_version on learning_objectives
        for each row execute function protect_assessed_objective_version()
        """
    )

    op.execute(
        """
        create function protect_assessed_exploration_entity()
        returns trigger
        language plpgsql
        as $$
        begin
            if (new.entity_id is distinct from old.entity_id
                or new.entity_version is distinct from old.entity_version)
               and exists (
                    select 1
                      from assessment_sessions s
                      join assessment_interactions ai
                        on ai.user_id = s.user_id
                       and ai.assessment_session_id = s.id
                      join assessment_responses ar
                        on ar.user_id = ai.user_id
                       and ar.assessment_session_id = ai.assessment_session_id
                       and ar.interaction_id = ai.id
                     where s.user_id = old.user_id
                       and s.exploration_id = old.id
               ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_explorations_assessment_history',
                    message = 'explorations referenced by assessment history cannot change entity version';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_explorations_assessment_history
        before update of entity_id, entity_version on explorations
        for each row execute function protect_assessed_exploration_entity()
        """
    )

    op.create_unique_constraint(
        op.f("uq_learning_objectives_entity_id_id"),
        "learning_objectives",
        ["entity_id", "id"],
    )

    op.create_table(
        "evaluation_runs",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("response_id", _uuid(), nullable=False),
        sa.Column("evaluator_type", sa.Text(), nullable=False),
        sa.Column("evaluator_version", sa.Text(), nullable=False),
        sa.Column("rubric_version", sa.Text(), nullable=False),
        sa.Column("result", sa.Text()),
        sa.Column("confidence", sa.Double()),
        sa.Column("feedback", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("supersedes_id", _uuid()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status in ('PENDING', 'SUCCEEDED', 'SUPERSEDED', 'REVOKED', "
            "'FAILED')",
            name=op.f("ck_evaluation_runs_status"),
        ),
        sa.CheckConstraint(
            "result is null or result in ('SUPPORTED', 'PARTIAL', "
            "'MISCONCEPTION', 'INSUFFICIENT_EVIDENCE', 'UNCERTAIN')",
            name=op.f("ck_evaluation_runs_result"),
        ),
        sa.CheckConstraint(
            "confidence is null or (confidence >= 0 and confidence <= 1)",
            name=op.f("ck_evaluation_runs_confidence"),
        ),
        sa.CheckConstraint(
            "status not in ('PENDING', 'SUCCEEDED', 'SUPERSEDED', 'REVOKED', "
            "'FAILED') or "
            "(status in ('PENDING', 'FAILED') and result is null and "
            "confidence is null and feedback is null) or "
            "(status in ('SUCCEEDED', 'SUPERSEDED', 'REVOKED') and "
            "result is not null and confidence is not null and feedback is not null)",
            name=op.f("ck_evaluation_runs_payload"),
        ),
        sa.CheckConstraint(
            "supersedes_id is null or supersedes_id <> id",
            name=op.f("ck_evaluation_runs_not_self_superseding"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "response_id"],
            ["assessment_responses.user_id", "assessment_responses.id"],
            ondelete="CASCADE",
            name=op.f("fk_evaluation_runs_response_owner"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "supersedes_id", "response_id"],
            ["evaluation_runs.user_id", "evaluation_runs.id", "evaluation_runs.response_id"],
            name=op.f("fk_evaluation_runs_superseded_owner_response"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_evaluation_runs")),
        sa.UniqueConstraint(
            "user_id",
            "id",
            "response_id",
            name=op.f("uq_evaluation_runs_owner_id_response"),
        ),
        sa.UniqueConstraint(
            "supersedes_id", name=op.f("uq_evaluation_runs_supersedes_id")
        ),
    )
    op.create_index(
        "uq_evaluation_runs_active_response",
        "evaluation_runs",
        ["response_id"],
        unique=True,
        postgresql_where=sa.text("status = 'SUCCEEDED'"),
    )
    op.create_index(
        "ix_evaluation_runs_user_response_created",
        "evaluation_runs",
        ["user_id", "response_id", sa.text("created_at DESC")],
    )

    op.create_table(
        "learning_evidence",
        sa.Column(
            "id", _uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False
        ),
        sa.Column("user_id", _uuid(), nullable=False),
        sa.Column("entity_id", _uuid(), nullable=False),
        sa.Column("objective_id", _uuid(), nullable=False),
        sa.Column("source_type", sa.Text(), nullable=False),
        sa.Column("source_id", _uuid(), nullable=False),
        sa.Column("evaluation_run_id", _uuid()),
        sa.Column("evidence_type", sa.Text(), nullable=False),
        sa.Column("evidence_strength", sa.Text(), nullable=False),
        sa.Column("support_level", sa.Text()),
        sa.Column("evaluation_confidence", sa.Double()),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "evidence_type in ('RECOGNITION', 'RECALL', 'EXPLANATION', "
            "'APPLICATION', 'ARGUMENT', 'PREDICTION', 'CREATION', "
            "'DEMONSTRATION', 'REFLECTION', 'RETENTION')",
            name=op.f("ck_learning_evidence_type"),
        ),
        sa.CheckConstraint(
            "evidence_strength in ('WEAK', 'MODERATE', 'STRONG')",
            name=op.f("ck_learning_evidence_strength"),
        ),
        sa.CheckConstraint(
            f"support_level is null or support_level in ({SUPPORT_LEVEL_SQL})",
            name=op.f("ck_learning_evidence_support_level"),
        ),
        sa.CheckConstraint(
            "evaluation_confidence is null or "
            "(evaluation_confidence >= 0 and evaluation_confidence <= 1)",
            name=op.f("ck_learning_evidence_confidence"),
        ),
        sa.CheckConstraint(
            "status in ('ACTIVE', 'SUPERSEDED', 'REVOKED')",
            name=op.f("ck_learning_evidence_status"),
        ),
        sa.CheckConstraint(
            "(source_type = 'ASSESSMENT_RESPONSE' and "
            "evaluation_run_id is not null) or "
            "(source_type <> 'ASSESSMENT_RESPONSE' and "
            "evaluation_run_id is null)",
            name=op.f("ck_learning_evidence_assessment_source"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["app_users.id"],
            ondelete="CASCADE",
            name=op.f("fk_learning_evidence_user_id_app_users"),
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "objective_id"],
            ["learning_objectives.entity_id", "learning_objectives.id"],
            name=op.f("fk_learning_evidence_objective_entity"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id", "evaluation_run_id", "source_id"],
            [
                "evaluation_runs.user_id",
                "evaluation_runs.id",
                "evaluation_runs.response_id",
            ],
            name=op.f("fk_learning_evidence_evaluation_owner_source"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_learning_evidence")),
        sa.UniqueConstraint(
            "user_id", "id", name=op.f("uq_learning_evidence_user_id_id")
        ),
    )
    op.create_index(
        "ix_learning_evidence_user_active_created",
        "learning_evidence",
        ["user_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_learning_evidence_objective_status",
        "learning_evidence",
        ["objective_id", "status"],
    )
    op.create_index(
        "ix_learning_evidence_evaluation_run_id",
        "learning_evidence",
        ["evaluation_run_id"],
    )

    op.execute(
        """
        create function protect_evaluation_run_history()
        returns trigger
        language plpgsql
        as $$
        begin
            if tg_op = 'DELETE' then
                if current_user <> 'app_maintenance' then
                    raise exception using
                        errcode = '55000',
                        constraint = 'ck_evaluation_runs_maintenance_delete',
                        message = 'evaluation runs may be deleted only by app_maintenance';
                end if;
                return old;
            end if;

            if new.id is distinct from old.id
               or new.user_id is distinct from old.user_id
               or new.response_id is distinct from old.response_id
               or new.evaluator_type is distinct from old.evaluator_type
               or new.evaluator_version is distinct from old.evaluator_version
               or new.rubric_version is distinct from old.rubric_version
               or new.supersedes_id is distinct from old.supersedes_id
               or new.created_at is distinct from old.created_at
               or (
                    (new.result is distinct from old.result
                     or new.confidence is distinct from old.confidence
                     or new.feedback is distinct from old.feedback)
                    and not (
                        old.status = 'PENDING'
                        and new.status in ('SUCCEEDED', 'FAILED')
                    )
               ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_evaluation_runs_immutable_payload',
                    message = 'evaluation identity and completed payload are immutable';
            end if;

            if new.status is distinct from old.status
               and not (
                    (old.status = 'PENDING' and new.status in ('SUCCEEDED', 'FAILED'))
                    or (old.status = 'SUCCEEDED' and new.status in ('SUPERSEDED', 'REVOKED'))
                    or (old.status = 'SUPERSEDED' and new.status = 'REVOKED')
               ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_evaluation_runs_status_transition',
                    message = 'invalid evaluation status transition';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_evaluation_runs_history
        before update or delete on evaluation_runs
        for each row execute function protect_evaluation_run_history()
        """
    )

    op.execute(
        """
        create function validate_learning_evidence_evaluation()
        returns trigger
        language plpgsql
        as $$
        declare
            evaluation_status text;
            evaluation_result text;
            response_objective_id uuid;
        begin
            if new.evaluation_run_id is null then
                return new;
            end if;

            select er.status, er.result, ai.objective_id
              into evaluation_status, evaluation_result, response_objective_id
              from evaluation_runs er
              join assessment_responses ar
                on ar.user_id = er.user_id
               and ar.id = er.response_id
              join assessment_interactions ai
                on ai.user_id = ar.user_id
               and ai.assessment_session_id = ar.assessment_session_id
               and ai.id = ar.interaction_id
             where er.user_id = new.user_id
               and er.id = new.evaluation_run_id
               and er.response_id = new.source_id
             for share of er;
            if not found then
                return new;
            end if;

            if response_objective_id <> new.objective_id then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_learning_evidence_evaluation_objective',
                    message = 'evaluation evidence objective must match the response interaction';
            end if;
            if new.status = 'ACTIVE'
               and (evaluation_status <> 'SUCCEEDED'
                    or evaluation_result = 'UNCERTAIN') then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_learning_evidence_active_evaluation',
                    message = 'active evidence requires a current conclusive evaluation';
            end if;
            if evaluation_status in ('PENDING', 'FAILED')
               or evaluation_result = 'UNCERTAIN' then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_learning_evidence_evaluation_result',
                    message = 'inconclusive evaluation cannot produce learning evidence';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_learning_evidence_20_validate_evaluation
        before insert or update of user_id, objective_id, source_type, source_id,
            evaluation_run_id, status
        on learning_evidence
        for each row execute function validate_learning_evidence_evaluation()
        """
    )

    op.execute(
        """
        create function protect_learning_evidence_history()
        returns trigger
        language plpgsql
        as $$
        begin
            if tg_op = 'DELETE' then
                if current_user <> 'app_maintenance' then
                    raise exception using
                        errcode = '55000',
                        constraint = 'ck_learning_evidence_maintenance_delete',
                        message = 'learning evidence may be deleted only by app_maintenance';
                end if;
                return old;
            end if;

            if new.id is distinct from old.id
               or new.user_id is distinct from old.user_id
               or new.entity_id is distinct from old.entity_id
               or new.objective_id is distinct from old.objective_id
               or new.source_type is distinct from old.source_type
               or new.source_id is distinct from old.source_id
               or new.evaluation_run_id is distinct from old.evaluation_run_id
               or new.evidence_type is distinct from old.evidence_type
               or new.evidence_strength is distinct from old.evidence_strength
               or new.support_level is distinct from old.support_level
               or new.evaluation_confidence is distinct from old.evaluation_confidence
               or new.created_at is distinct from old.created_at then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_learning_evidence_immutable_payload',
                    message = 'learning evidence provenance and payload are immutable';
            end if;

            if new.status is distinct from old.status
               and not (
                    (old.status = 'ACTIVE' and new.status in ('SUPERSEDED', 'REVOKED'))
                    or (old.status = 'SUPERSEDED' and new.status = 'REVOKED')
               ) then
                raise exception using
                    errcode = '55000',
                    constraint = 'ck_learning_evidence_status_transition',
                    message = 'invalid learning evidence status transition';
            end if;
            return new;
        end;
        $$
        """
    )
    op.execute(
        """
        create trigger trg_learning_evidence_10_history
        before update or delete on learning_evidence
        for each row execute function protect_learning_evidence_history()
        """
    )

    op.execute(
        """
        create function validate_evaluation_active_evidence()
        returns trigger
        language plpgsql
        as $$
        begin
            if (new.status <> 'SUCCEEDED' or new.result = 'UNCERTAIN')
               and exists (
                    select 1
                      from learning_evidence le
                     where le.evaluation_run_id = new.id
                       and le.status = 'ACTIVE'
               ) then
                raise exception using
                    errcode = '23514',
                    constraint = 'ck_evaluation_runs_active_evidence',
                    message = 'non-current or inconclusive evaluation cannot retain active evidence';
            end if;
            return null;
        end;
        $$
        """
    )
    op.execute(
        """
        create constraint trigger ct_evaluation_runs_active_evidence
        after insert or update on evaluation_runs
        deferrable initially deferred
        for each row execute function validate_evaluation_active_evidence()
        """
    )


def downgrade() -> None:
    op.execute(
        "drop trigger ct_evaluation_runs_active_evidence on evaluation_runs"
    )
    op.execute("drop function validate_evaluation_active_evidence()")
    op.execute(
        "drop trigger trg_learning_evidence_10_history on learning_evidence"
    )
    op.execute("drop function protect_learning_evidence_history()")
    op.execute(
        "drop trigger trg_learning_evidence_20_validate_evaluation "
        "on learning_evidence"
    )
    op.execute("drop function validate_learning_evidence_evaluation()")
    op.execute("drop trigger trg_evaluation_runs_history on evaluation_runs")
    op.execute("drop function protect_evaluation_run_history()")
    op.execute(
        "drop trigger trg_explorations_assessment_history on explorations"
    )
    op.execute("drop function protect_assessed_exploration_entity()")
    op.execute(
        "drop trigger trg_learning_objectives_assessment_history "
        "on learning_objectives"
    )
    op.execute("drop function protect_assessed_objective_version()")
    op.execute(
        "drop trigger trg_assessment_interactions_historical_prompt "
        "on assessment_interactions"
    )
    op.execute("drop function protect_answered_assessment_interaction()")
    op.drop_index(
        "ix_learning_evidence_evaluation_run_id", table_name="learning_evidence"
    )
    op.drop_index(
        "ix_learning_evidence_objective_status", table_name="learning_evidence"
    )
    op.drop_index(
        "ix_learning_evidence_user_active_created", table_name="learning_evidence"
    )
    op.drop_table("learning_evidence")
    op.drop_index(
        "ix_evaluation_runs_user_response_created", table_name="evaluation_runs"
    )
    op.drop_index(
        "uq_evaluation_runs_active_response", table_name="evaluation_runs"
    )
    op.drop_table("evaluation_runs")
    op.drop_constraint(
        op.f("uq_learning_objectives_entity_id_id"),
        "learning_objectives",
        type_="unique",
    )
    op.execute(
        "drop trigger trg_assessment_responses_immutable on assessment_responses"
    )
    op.execute("drop function prevent_assessment_response_mutation()")
    op.execute(
        "drop trigger trg_assessment_responses_objective_version "
        "on assessment_responses"
    )
    op.execute("drop function validate_assessment_response_objective_version()")
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
    op.execute(
        "drop trigger trg_assessment_interactions_objective_version "
        "on assessment_interactions"
    )
    op.execute("drop function validate_assessment_interaction_objective_version()")
    op.drop_index(
        "ix_assessment_interactions_objective_id",
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
