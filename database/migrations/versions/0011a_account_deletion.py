"""Add the trusted account-deletion maintenance path.

Revision ID: 0011a_account_deletion
Revises: 0011_stories_and_exports

This prerequisite repairs whole-account deletion without weakening runtime
immutability:

* The Experience Ledger guard on ``learning_events`` gains a single DELETE
  exception for the ``app_maintenance`` identity. UPDATE stays forbidden for
  every role, and ordinary roles still cannot DELETE ledger rows.
* ``public.maintenance_delete_account(uuid)`` performs an explicit, ordered,
  direct deletion of one learner's owned rows and deletes ``app_users`` last.

The routine is inert to application roles after this migration: EXECUTE is
revoked from PUBLIC and ownership is not transferred. Migration
``0012_rls_and_security`` is expected to provision ``app_maintenance``, transfer
ownership, and grant EXECUTE to the trusted worker.

Migrations ``0001``-``0011`` are immutable and are not modified here.
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0011a_account_deletion"
down_revision: str | None = "0011_stories_and_exports"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Ordered, dependency-safe deletion of one learner's rows. Every table carries
# a ``user_id``; ``app_users`` is always last. The order exists to satisfy
# NO ACTION ownership FKs explicitly and to remove ledger rows before commands
# and devices (whose FK is ON DELETE SET NULL and would otherwise induce an
# UPDATE against the immutable ledger).
DELETION_ORDER: tuple[str, ...] = (
    "state_evidence_links",
    "artifact_analyses",
    "world_changes",
    "world_artifacts",
    "world_connections",
    "world_nodes",
    "world_regions",
    "learner_worlds",
    "learning_events",
    "learning_evidence",
    "evaluation_runs",
    "assessment_support_requests",
    "assessment_responses",
    "assessment_interactions",
    "assessment_sessions",
    "artifacts",
    "media_objects",
    "upload_sessions",
    "reflections",
    "curiosity_stories",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "explicit_interest_preferences",
    "explorations",
    "recommendations",
    "account_operation_requests",
    "jobs",
    "user_devices",
    "idempotency_records",
    "learner_preferences",
    "user_motivations",
)

_ORIGINAL_LEARNING_EVENT_GUARD = """
create or replace function prevent_learning_event_mutation()
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

_MAINTENANCE_LEARNING_EVENT_GUARD = """
create or replace function prevent_learning_event_mutation()
returns trigger
language plpgsql
as $$
begin
    if tg_op = 'DELETE' and current_user = 'app_maintenance' then
        return old;
    end if;
    raise exception using
        errcode = '55000',
        message = 'learning events are immutable',
        constraint = 'ck_learning_events_immutable';
end;
$$
"""


def _maintenance_function_sql() -> str:
    # The search_path is fixed to a hardened, non-caller-controlled list.
    # ``public`` must remain in the path because pre-existing immutable trigger
    # functions (0005/0006) resolve unqualified table names; ``pg_catalog`` is
    # first so built-ins always win and ``pg_temp`` is last so a temporary
    # schema cannot shadow anything. Request runtime roles hold no CREATE on
    # ``public``, so it is not a writable shadowing surface.
    statements = "\n".join(
        f"    delete from public.{table} where user_id = p_user_id;"
        for table in DELETION_ORDER
    )
    return f"""
create function public.maintenance_delete_account(p_user_id uuid)
returns void
language plpgsql
security definer
set search_path = pg_catalog, public, pg_temp
as $$
begin
    if p_user_id is null then
        raise exception using
            errcode = '22004',
            message = 'maintenance_delete_account requires a target user id',
            constraint = 'ck_maintenance_delete_account_target';
    end if;

{statements}
    delete from public.app_users where id = p_user_id;
end;
$$
"""


def upgrade() -> None:
    op.execute(_MAINTENANCE_LEARNING_EVENT_GUARD)
    op.execute(_maintenance_function_sql())
    op.execute(
        "revoke all on function public.maintenance_delete_account(uuid) "
        "from public"
    )


def downgrade() -> None:
    op.execute("drop function public.maintenance_delete_account(uuid)")
    op.execute(_ORIGINAL_LEARNING_EVENT_GUARD)
