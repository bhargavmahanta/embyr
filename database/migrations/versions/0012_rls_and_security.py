"""Activate the database security boundary: roles, grants, and forced RLS.

Revision ID: 0012_rls_and_security
Revises: 0011a_account_deletion

This migration is the M1 security boundary and the head of the chain.

Responsibilities
----------------
* Verify the externally provisioned runtime roles ``app_backend``,
  ``app_worker``, and ``app_maintenance`` and their security attributes. It
  never creates or alters cluster roles: creating a ``BYPASSRLS`` role requires
  superuser authority that a migration credential is not guaranteed to hold on
  hosted PostgreSQL.
* Harden the ``public`` schema: runtime roles receive ``USAGE`` but never
  ``CREATE``; ``CREATE`` is revoked from ``PUBLIC``.
* Apply least-privilege grants. Canonical corpus tables are read-only to
  runtime roles. Request-path tables are writable by ``app_backend`` under
  RLS; derived Learner State, WorldModel, recommendations, stories, and
  analyses are read-only to ``app_backend``.
* Transfer ownership of ``public.maintenance_delete_account(uuid)`` to
  ``app_maintenance`` (so ``current_user`` inside the ``SECURITY DEFINER``
  routine satisfies the 0011a ledger guard) and grant ``EXECUTE`` only to the
  trusted worker role ``app_worker``.
* Enable and FORCE row level security on every learner-owned table, with a
  single policy scoped to ``app_backend`` that reads the transaction-local
  ``app.user_id`` setting.
* Ensure Supabase client roles (``anon``, ``authenticated``, ``service_role``)
  hold no privileges on Embyr application tables, no ``CREATE`` on ``public``,
  and no ``EXECUTE`` on the privileged maintenance function, when those roles
  exist.
* Record and reversibly strip the implicit global and explicit ``public``
  schema ``PUBLIC EXECUTE`` defaults from future functions created by the
  application object owner.

The policy expression uses ``nullif(current_setting('app.user_id', true), '')``
so that an absent setting (NULL) and a reset/empty pooled setting ('') both
fail closed without a uuid cast error. A malformed non-empty setting still
raises; the trusted backend only ever sets a validated UUID.

Migrations ``0001``-``0011a`` are immutable and are not modified here.
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_rls_and_security"
down_revision: str | None = "0011a_account_deletion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Runtime roles verified (never provisioned) by this migration.
BACKEND_ROLE = "app_backend"
WORKER_ROLE = "app_worker"
MAINTENANCE_ROLE = "app_maintenance"
RUNTIME_ROLES: tuple[str, ...] = (BACKEND_ROLE, WORKER_ROLE, MAINTENANCE_ROLE)

# Supabase client roles that must never reach application tables directly.
CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")

MAINTENANCE_FUNCTION_ARGS = "public.maintenance_delete_account(uuid)"
POLICY_IDENTITY = "nullif(current_setting('app.user_id', true), '')::uuid"
DEFAULT_PRIVILEGE_MARKER_POLICY = "user_devices_user_policy"

CANONICAL_TABLES: tuple[str, ...] = (
    "learning_entities",
    "learning_entity_versions",
    "entity_domains",
    "ontology_edges",
    "learning_objectives",
    "misconceptions",
    "claims",
    "entity_embeddings",
    "practical_challenges",
    "practical_challenge_versions",
)

# Every learner-owned table carries user_id directly and receives RLS.
LEARNER_TABLES: tuple[str, ...] = (
    "user_devices",
    "idempotency_records",
    "jobs",
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    "explorations",
    "reflections",
    "assessment_sessions",
    "assessment_interactions",
    "assessment_support_requests",
    "assessment_responses",
    "evaluation_runs",
    "learning_evidence",
    "artifacts",
    "media_objects",
    "upload_sessions",
    "artifact_analyses",
    "learning_events",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "recommendations",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    "curiosity_stories",
    "account_operation_requests",
)

# app_backend request-path grants.
BACKEND_FULL_DML: tuple[str, ...] = (
    "user_devices",
    "idempotency_records",
    "learner_preferences",
    "user_motivations",
    "explicit_interest_preferences",
    "explorations",
    "reflections",
    "assessment_sessions",
    "assessment_interactions",
    "assessment_support_requests",
    "upload_sessions",
)
BACKEND_INSERT_SELECT: tuple[str, ...] = (
    "assessment_responses",
    "media_objects",
    "artifacts",
    "learning_events",
)
BACKEND_SELECT_INSERT_UPDATE: tuple[str, ...] = (
    "jobs",
    "evaluation_runs",
    "recommendations",
    "account_operation_requests",
)
BACKEND_SELECT_ONLY: tuple[str, ...] = (
    "learning_evidence",
    "artifact_analyses",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
    "curiosity_stories",
)

# app_worker projection/job grants. SELECT is granted across all learner tables
# first; write grants are narrowed per group below.
WORKER_WRITE_FULL: tuple[str, ...] = (
    "jobs",
    "learner_interest_state",
    "learner_confidence_state",
    "learner_retention_state",
    "learner_objective_state",
    "learner_challenge_state",
    "state_evidence_links",
    "learner_worlds",
    "world_regions",
    "world_nodes",
    "world_connections",
    "world_artifacts",
    "world_changes",
)
WORKER_WRITE_NO_DELETE: tuple[str, ...] = (
    "evaluation_runs",
    "learning_evidence",
    "recommendations",
    "artifact_analyses",
    "curiosity_stories",
    "account_operation_requests",
)
WORKER_SPECIAL_UPDATES: tuple[str, ...] = ("upload_sessions",)
WORKER_SPECIAL_INSERTS: tuple[str, ...] = (
    "idempotency_records",
    "media_objects",
    "learning_events",
)


def _quoted(tables: Sequence[str]) -> str:
    return ", ".join(f"public.{table}" for table in tables)


def _verify_runtime_roles(bind: sa.engine.Connection) -> None:
    rows = {
        row.rolname: row
        for row in bind.execute(
            sa.text(
                "select rolname, rolcanlogin, rolbypassrls, rolsuper, "
                "rolcreaterole, rolcreatedb, rolreplication from pg_roles "
                "where rolname = any(:roles)"
            ),
            {"roles": list(RUNTIME_ROLES)},
        ).all()
    }

    missing = sorted(set(RUNTIME_ROLES) - set(rows))
    if missing:
        raise RuntimeError(
            "0012_rls_and_security requires externally provisioned runtime "
            f"roles; missing: {', '.join(missing)}. Environment administrators "
            "must create them (with the documented attributes) before applying "
            "this migration."
        )

    memberships = bind.execute(
        sa.text(
            """
            select member_role.rolname as member_name,
                   granted_role.rolname as granted_name
            from pg_auth_members membership
            join pg_roles member_role on member_role.oid = membership.member
            join pg_roles granted_role on granted_role.oid = membership.roleid
            where member_role.rolname = any(:roles)
            order by member_role.rolname, granted_role.rolname
            """
        ),
        {"roles": list(RUNTIME_ROLES)},
    ).all()
    if memberships:
        edges = ", ".join(
            f"{row.member_name} -> {row.granted_name}" for row in memberships
        )
        raise RuntimeError(
            "runtime roles must not be members of other roles; found: "
            f"{edges}"
        )

    for role, row in rows.items():
        if row.rolsuper:
            raise RuntimeError(f"{role} must not be SUPERUSER")
        if row.rolcreaterole:
            raise RuntimeError(f"{role} must not have CREATEROLE")
        if row.rolcreatedb:
            raise RuntimeError(f"{role} must not have CREATEDB")
        if row.rolreplication:
            raise RuntimeError(f"{role} must not have REPLICATION")

    if rows[BACKEND_ROLE].rolbypassrls:
        raise RuntimeError(
            "app_backend must be NOBYPASSRLS so row level security applies"
        )
    if not rows[WORKER_ROLE].rolbypassrls:
        raise RuntimeError("app_worker must be BYPASSRLS for cross-user work")
    if not rows[MAINTENANCE_ROLE].rolbypassrls:
        raise RuntimeError(
            "app_maintenance must be BYPASSRLS for cross-user physical cleanup"
        )
    if rows[MAINTENANCE_ROLE].rolcanlogin:
        raise RuntimeError("app_maintenance must be NOLOGIN")


def _harden_schema() -> None:
    op.execute("revoke create on schema public from public")
    op.execute(
        "grant usage on schema public to "
        "app_backend, app_worker, app_maintenance"
    )


def _grant_canonical_read() -> None:
    op.execute(
        f"grant select on {_quoted(CANONICAL_TABLES)} "
        "to app_backend, app_worker"
    )


def _grant_identity() -> None:
    # app_users stays outside learner RLS because authentication resolves the
    # internal UUID from (auth_provider, auth_subject) before app.user_id exists.
    op.execute("grant select, insert, update on public.app_users to app_backend")
    op.execute("grant select on public.app_users to app_worker")


def _grant_backend() -> None:
    op.execute(
        f"grant select, insert, update, delete on {_quoted(BACKEND_FULL_DML)} "
        "to app_backend"
    )
    op.execute(
        f"grant select, insert on {_quoted(BACKEND_INSERT_SELECT)} to app_backend"
    )
    op.execute(
        f"grant select, insert, update on {_quoted(BACKEND_SELECT_INSERT_UPDATE)} "
        "to app_backend"
    )
    op.execute(f"grant select on {_quoted(BACKEND_SELECT_ONLY)} to app_backend")


def _grant_worker() -> None:
    op.execute(f"grant select on {_quoted(LEARNER_TABLES)} to app_worker")
    op.execute(
        f"grant insert, update, delete on {_quoted(WORKER_WRITE_FULL)} "
        "to app_worker"
    )
    op.execute(
        f"grant insert, update on {_quoted(WORKER_WRITE_NO_DELETE)} to app_worker"
    )
    op.execute(
        f"grant update on {_quoted(WORKER_SPECIAL_UPDATES)} to app_worker"
    )
    op.execute(
        f"grant insert on {_quoted(WORKER_SPECIAL_INSERTS)} to app_worker"
    )


def _grant_maintenance() -> None:
    op.execute(
        f"grant select, delete on {_quoted((*LEARNER_TABLES, 'app_users'))} "
        "to app_maintenance"
    )


def _activate_maintenance_function() -> None:
    # Ownership transfer makes current_user = 'app_maintenance' inside the
    # SECURITY DEFINER routine, satisfying the 0011a ledger guard. BYPASSRLS
    # and the SELECT/DELETE grants above let its ordered deletes run.
    # Remove every explicit executor except the trusted worker before the
    # transfer. The current owner retains its implicit owner privilege, and
    # app_maintenance gains that privilege when ownership moves below.
    op.execute(
        f"""
        do $$
        declare
            executor_role text;
        begin
            for executor_role in
                select grantee.rolname
                from pg_proc routine
                join pg_namespace namespace
                  on namespace.oid = routine.pronamespace
                cross join lateral aclexplode(
                    coalesce(
                        routine.proacl,
                        acldefault('f', routine.proowner)
                    )
                ) acl
                join pg_roles grantee on grantee.oid = acl.grantee
                where namespace.nspname = 'public'
                  and routine.oid =
                      '{MAINTENANCE_FUNCTION_ARGS}'::regprocedure
                  and acl.privilege_type = 'EXECUTE'
                  and acl.grantee <> routine.proowner
                  and grantee.rolname <> '{WORKER_ROLE}'
            loop
                execute format(
                    'revoke all on function {MAINTENANCE_FUNCTION_ARGS} from %I',
                    executor_role
                );
            end loop;
        end
        $$
        """
    )
    op.execute(
        f"revoke all on function {MAINTENANCE_FUNCTION_ARGS} from public"
    )
    op.execute(
        f"grant execute on function {MAINTENANCE_FUNCTION_ARGS} to {WORKER_ROLE}"
    )
    # PostgreSQL requires a function's new owner to have CREATE on the
    # containing schema. Grant that capability only for the transactional
    # ownership transfer and remove it before the migration commits.
    op.execute(f"grant create on schema public to {MAINTENANCE_ROLE}")
    op.execute(
        f"alter function {MAINTENANCE_FUNCTION_ARGS} owner to {MAINTENANCE_ROLE}"
    )
    op.execute(f"revoke create on schema public from {MAINTENANCE_ROLE}")


def _enable_rls() -> None:
    for table in LEARNER_TABLES:
        op.execute(f"alter table public.{table} enable row level security")
        op.execute(f"alter table public.{table} force row level security")
        op.execute(
            f"create policy {table}_user_policy on public.{table} "
            f"to {BACKEND_ROLE} using (user_id = {POLICY_IDENTITY}) "
            f"with check (user_id = {POLICY_IDENTITY})"
        )


def _revoke_client_roles() -> None:
    # Supabase provisions anon/authenticated/service_role and may grant
    # privileges on public objects. Embyr clients never access the database
    # directly, so strip any such access when the roles exist. This is scoped
    # to Embyr application tables and the privileged maintenance function; it
    # never touches extension or ordinary functions.
    app_tables = (*LEARNER_TABLES, *CANONICAL_TABLES, "app_users")
    table_array = ", ".join(f"'{table}'" for table in app_tables)
    op.execute(
        f"""
        do $$
        declare
            client_role text;
            target_table text;
            app_tables text[] := array[{table_array}];
        begin
            foreach client_role in array
                array['anon', 'authenticated', 'service_role']
            loop
                if exists (
                    select 1 from pg_roles where rolname = client_role
                ) then
                    execute format(
                        'revoke create on schema public from %I', client_role
                    );
                    execute format(
                        'revoke all on function {MAINTENANCE_FUNCTION_ARGS} '
                        'from %I', client_role
                    );
                    foreach target_table in array app_tables loop
                        execute format(
                            'revoke all on table public.%I from %I',
                            target_table, client_role
                        );
                    end loop;
                end if;
            end loop;
        end
        $$
        """
    )


def _application_object_owner(bind: sa.engine.Connection) -> tuple[int, str]:
    row = bind.execute(
        sa.text(
            """
            select c.relowner, pg_get_userbyid(c.relowner) as owner_name
            from pg_class c
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public' and c.relname = 'app_users'
            """
        )
    ).one()
    return row.relowner, row.owner_name


def _public_execute_defaults(
    bind: sa.engine.Connection,
    owner_oid: int,
) -> tuple[bool, bool]:
    global_public_execute = bind.execute(
        sa.text(
            """
            select exists (
                select 1
                from aclexplode(
                    coalesce(
                        (
                            select d.defaclacl
                            from pg_default_acl d
                            where d.defaclrole = :owner_oid
                              and d.defaclnamespace = 0
                              and d.defaclobjtype = 'f'
                        ),
                        acldefault('f', :owner_oid)
                    )
                ) acl
                where acl.grantee = 0
                  and acl.privilege_type = 'EXECUTE'
            )
            """
        ),
        {"owner_oid": owner_oid},
    ).scalar_one()
    schema_public_execute = bind.execute(
        sa.text(
            """
            select coalesce(
                (
                    select exists (
                        select 1
                        from aclexplode(d.defaclacl) acl
                        where acl.grantee = 0
                          and acl.privilege_type = 'EXECUTE'
                    )
                    from pg_default_acl d
                    join pg_namespace n on n.oid = d.defaclnamespace
                    where d.defaclrole = :owner_oid
                      and d.defaclobjtype = 'f'
                      and n.nspname = 'public'
                ),
                false
            )
            """
        ),
        {"owner_oid": owner_oid},
    ).scalar_one()
    return global_public_execute, schema_public_execute


def _quoted_role(bind: sa.engine.Connection, role: str) -> str:
    return bind.dialect.identifier_preparer.quote(role)


def _harden_default_privileges(bind: sa.engine.Connection) -> None:
    owner_oid, owner_name = _application_object_owner(bind)
    global_public_execute, schema_public_execute = _public_execute_defaults(
        bind, owner_oid
    )
    marker = json.dumps(
        {
            "revision": revision,
            "creator_role": owner_name,
            "global_public_execute": global_public_execute,
            "schema_public_execute": schema_public_execute,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    marker_literal = str(
        sa.literal(marker).compile(
            dialect=bind.dialect,
            compile_kwargs={"literal_binds": True},
        )
    )
    bind.exec_driver_sql(
        "comment on policy user_devices_user_policy on public.user_devices "
        f"is {marker_literal}"
    )

    role = _quoted_role(bind, owner_name)
    op.execute(
        f"alter default privileges for role {role} "
        "revoke execute on functions from public"
    )
    op.execute(
        f"alter default privileges for role {role} in schema public "
        "revoke execute on functions from public"
    )


def _restore_default_privileges(bind: sa.engine.Connection) -> None:
    marker = bind.execute(
        sa.text(
            """
            select obj_description(p.oid, 'pg_policy')
            from pg_policy p
            join pg_class c on c.oid = p.polrelid
            join pg_namespace n on n.oid = c.relnamespace
            where n.nspname = 'public'
              and c.relname = 'user_devices'
              and p.polname = :policy
            """
        ),
        {"policy": DEFAULT_PRIVILEGE_MARKER_POLICY},
    ).scalar_one_or_none()
    if marker is None:
        raise RuntimeError(
            "0012 default-privilege rollback state is missing; refusing to guess"
        )

    try:
        state = json.loads(marker)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "0012 default-privilege rollback state is malformed"
        ) from error

    required = {
        "revision",
        "creator_role",
        "global_public_execute",
        "schema_public_execute",
    }
    if (
        not isinstance(state, dict)
        or set(state) != required
        or state.get("revision") != revision
        or not isinstance(state.get("creator_role"), str)
        or not isinstance(state.get("global_public_execute"), bool)
        or not isinstance(state.get("schema_public_execute"), bool)
    ):
        raise RuntimeError("0012 default-privilege rollback state is malformed")

    owner_name = state["creator_role"]
    owner_exists = bind.execute(
        sa.text("select 1 from pg_roles where rolname = :role"),
        {"role": owner_name},
    ).scalar_one_or_none()
    if owner_exists is None:
        raise RuntimeError(
            "0012 default-privilege creator role no longer exists; "
            "refusing to guess"
        )

    role = _quoted_role(bind, owner_name)
    if state["global_public_execute"]:
        op.execute(
            f"alter default privileges for role {role} "
            "grant execute on functions to public"
        )
    if state["schema_public_execute"]:
        op.execute(
            f"alter default privileges for role {role} in schema public "
            "grant execute on functions to public"
        )


def upgrade() -> None:
    _verify_runtime_roles(op.get_bind())

    _harden_schema()
    _grant_canonical_read()
    _grant_identity()
    _grant_backend()
    _grant_worker()
    _grant_maintenance()

    _revoke_client_roles()
    _activate_maintenance_function()
    _enable_rls()

    _harden_default_privileges(op.get_bind())


def downgrade() -> None:
    _restore_default_privileges(op.get_bind())

    for table in LEARNER_TABLES:
        op.execute(f"drop policy if exists {table}_user_policy on public.{table}")
        op.execute(f"alter table public.{table} no force row level security")
        op.execute(f"alter table public.{table} disable row level security")

    op.execute(
        f"revoke execute on function {MAINTENANCE_FUNCTION_ARGS} from {WORKER_ROLE}"
    )
    op.execute(
        f"alter function {MAINTENANCE_FUNCTION_ARGS} owner to current_user"
    )

    op.execute(
        "revoke all on all tables in schema public from "
        "app_backend, app_worker, app_maintenance"
    )
    op.execute(
        "revoke usage on schema public from "
        "app_backend, app_worker, app_maintenance"
    )
