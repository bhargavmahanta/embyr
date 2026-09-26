"""Secure response history row locks without backend ontology write privileges."""
from collections.abc import Sequence

from alembic import op

revision: str = "0019_response_lock_security"
down_revision: str | None = "0018_exploration_delivery"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FUNCTION = "public.validate_assessment_response_objective_version()"
LOCK_TABLES = ("assessment_interactions", "assessment_sessions", "explorations", "learning_objectives")
ORIGINAL = r"""
create or replace function public.validate_assessment_response_objective_version()
        returns trigger
        language plpgsql
        as $$
        begin
            perform 1
              from public.assessment_interactions ai
             where ai.user_id = new.user_id
               and ai.assessment_session_id = new.assessment_session_id
               and ai.id = new.interaction_id;
            if not found then
                return new;
            end if;

            perform 1
              from public.assessment_interactions ai
              join public.assessment_sessions s
                on s.user_id = ai.user_id
               and s.id = ai.assessment_session_id
              join public.explorations e
                on e.user_id = s.user_id
               and e.id = s.exploration_id
              join public.learning_objectives o
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


def upgrade() -> None:
    # FOR SHARE requires SELECT and any UPDATE column privilege. The trusted
    # BYPASSRLS maintenance identity receives only the id column for locks;
    # backend and worker grants stay unchanged.
    op.execute("grant select on public.learning_objectives to app_maintenance")
    for table in LOCK_TABLES:
        op.execute(f"grant update (id) on public.{table} to app_maintenance")
    secured = ORIGINAL.replace(
        "language plpgsql\n        as $$\n        begin",
        "language plpgsql security definer set search_path = pg_catalog, public\n"
        "        as $$\n"
        "        declare invoking_role text;\n"
        "        begin\n"
        "            invoking_role := coalesce(nullif(current_setting('role', true), 'none'), session_user);\n"
        "            if not (select rolsuper from pg_catalog.pg_roles where rolname = invoking_role)\n"
        "               and pg_has_role(invoking_role, 'app_backend', 'USAGE')\n"
        "               and new.user_id is distinct from nullif(current_setting('app.user_id', true), '')::uuid then\n"
        "                raise exception 'assessment response owner must match transaction identity' using errcode = '42501';\n"
        "            end if;",
    )
    op.execute(secured)
    op.execute(f"revoke all on function {FUNCTION} from public, app_backend, app_worker")
    op.execute("grant create on schema public to app_maintenance")
    op.execute(f"alter function {FUNCTION} owner to app_maintenance")
    op.execute("revoke create on schema public from app_maintenance")


def downgrade() -> None:
    op.execute(f"alter function {FUNCTION} owner to current_user")
    op.execute(ORIGINAL)
    op.execute(f"alter function {FUNCTION} security invoker")
    op.execute(f"alter function {FUNCTION} reset search_path")
    op.execute(f"grant execute on function {FUNCTION} to public")
    for table in LOCK_TABLES:
        op.execute(f"revoke update (id) on public.{table} from app_maintenance")
    op.execute("revoke select on public.learning_objectives from app_maintenance")
