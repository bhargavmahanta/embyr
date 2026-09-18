"""Harden Supabase default privileges for future Embyr objects.

Revision ID: 0013_default_acl_hardening
Revises: 0012_rls_and_security

Supabase's platform defaults historically grant newly created ``public``
objects to the Data API client roles (``anon``, ``authenticated``,
``service_role``). Embyr never exposes tables through the Data API; FastAPI is
the only data-access boundary. ``0012_rls_and_security`` revokes client-role
access on the objects that exist when it runs, but it does not neutralise the
default privileges that would grant *future* objects.

This migration freezes the architectural rule that only ``app_owner`` authors
Embyr application schema. For objects ``app_owner`` creates in ``public``,
future default privileges must not grant ``anon``, ``authenticated``, or
``service_role`` access to tables, sequences, or functions.

PostgreSQL adds per-schema defaults to global defaults, so a global client-role
default cannot be removed by a schema-scoped ``REVOKE``. Rather than silently
leave such a grant in force, the migration rejects a global client-role default
for ``app_owner`` and aborts, keeping its ``public`` scope honest.

It records the prior ``app_owner`` schema-``public`` default-ACL state, revokes
the client-role defaults, and — for Embyr objects ``app_owner`` already owns in
``public`` — revokes any client-role privileges. Downgrade restores the
recorded default-ACL state exactly and leaves unrelated default-ACL entries
untouched. It never touches Supabase system schemas and never manages
``supabase_admin`` defaults.

Migrations ``0001``-``0012`` are immutable and are not modified here.
"""
import json
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_default_acl_hardening"
down_revision: str | None = "0012_rls_and_security"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OBJECT_OWNER_ROLE = "app_owner"
SCHEMA_NAME = "public"
CLIENT_ROLES: tuple[str, ...] = ("anon", "authenticated", "service_role")

# (pg_default_acl.defaclobjtype, GRANT/REVOKE keyword)
DEFAULT_ACL_TYPES: tuple[tuple[str, str], ...] = (
    ("r", "TABLES"),
    ("S", "SEQUENCES"),
    ("f", "FUNCTIONS"),
)

# The rollback marker is stored as a comment on an Embyr-owned table so it can
# be read back by upgrade-created objects. ``app_users`` is chosen because it
# exists before 0013, is owned by the migration/object owner, and is not used
# by any other migration marker.
MARKER_OBJECT = "public.app_users"
MARKER_KIND = "pg_class"


def _quote(bind: sa.engine.Connection, identifier: str) -> str:
    return bind.dialect.identifier_preparer.quote(identifier)


def _owner_exists(bind: sa.engine.Connection) -> bool:
    return (
        bind.execute(
            sa.text("select 1 from pg_roles where rolname = :role"),
            {"role": OBJECT_OWNER_ROLE},
        ).scalar_one_or_none()
        is not None
    )


def _existing_client_roles(bind: sa.engine.Connection) -> list[str]:
    present = set(
        bind.execute(
            sa.text("select rolname from pg_roles where rolname = any(:roles)"),
            {"roles": list(CLIENT_ROLES)},
        )
        .scalars()
        .all()
    )
    return [role for role in CLIENT_ROLES if role in present]


def _record_defaults(
    bind: sa.engine.Connection, roles: Sequence[str]
) -> dict[str, dict[str, list[str]]]:
    recorded: dict[str, dict[str, list[str]]] = {}
    statement = sa.text(
        """
        select acl.privilege_type
        from pg_default_acl d
        join pg_roles owner on owner.oid = d.defaclrole
        cross join lateral aclexplode(d.defaclacl) acl
        join pg_roles grantee on grantee.oid = acl.grantee
        where owner.rolname = :owner
          and d.defaclnamespace = 'public'::regnamespace
          and d.defaclobjtype = :objtype
          and grantee.rolname = :role
        order by acl.privilege_type
        """
    )
    for objtype, _keyword in DEFAULT_ACL_TYPES:
        recorded[objtype] = {}
        for role in roles:
            privileges = (
                bind.execute(
                    statement,
                    {
                        "owner": OBJECT_OWNER_ROLE,
                        "objtype": objtype,
                        "role": role,
                    },
                )
                .scalars()
                .all()
            )
            if privileges:
                recorded[objtype][role] = list(privileges)
    return recorded


def _public_function_execute_defaults(
    bind: sa.engine.Connection,
) -> tuple[bool, bool]:
    """Record whether app_owner function defaults grant EXECUTE to PUBLIC.

    Client roles inherit ``PUBLIC``, so future functions are only guaranteed to
    be unreachable when the implicit ``PUBLIC EXECUTE`` default is also removed.
    """
    owner_oid = bind.execute(
        sa.text("select oid from pg_roles where rolname = :role"),
        {"role": OBJECT_OWNER_ROLE},
    ).scalar_one()
    global_default = bind.execute(
        sa.text(
            """
            select exists (
                select 1
                from aclexplode(
                    coalesce(
                        (
                            select d.defaclacl
                            from pg_default_acl d
                            where d.defaclrole = :owner
                              and d.defaclnamespace = 0
                              and d.defaclobjtype = 'f'
                        ),
                        acldefault('f', :owner)
                    )
                ) acl
                where acl.grantee = 0
                  and acl.privilege_type = 'EXECUTE'
            )
            """
        ),
        {"owner": owner_oid},
    ).scalar_one()
    schema_default = bind.execute(
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
                    where d.defaclrole = :owner
                      and d.defaclobjtype = 'f'
                      and n.nspname = :schema
                ),
                false
            )
            """
        ),
        {"owner": owner_oid, "schema": SCHEMA_NAME},
    ).scalar_one()
    return global_default, schema_default


def _write_marker(bind: sa.engine.Connection, recorded: dict) -> None:
    state = dict(recorded)
    global_public, schema_public = _public_function_execute_defaults(bind)
    state["public_function_execute"] = {
        "global": global_public,
        "schema": schema_public,
    }
    marker = json.dumps(
        {
            "revision": revision,
            "owner": OBJECT_OWNER_ROLE,
            "defaults": state,
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
        f"comment on table {MARKER_OBJECT} is {marker_literal}"
    )


def _read_marker(bind: sa.engine.Connection) -> dict:
    marker = bind.execute(
        sa.text("select obj_description(cast(:obj as regclass), :kind)"),
        {"obj": MARKER_OBJECT, "kind": MARKER_KIND},
    ).scalar_one_or_none()
    if marker is None:
        raise RuntimeError(
            "0013 default-privilege rollback state is missing; refusing to guess"
        )
    try:
        state = json.loads(marker)
    except (TypeError, json.JSONDecodeError) as error:
        raise RuntimeError(
            "0013 default-privilege rollback state is malformed"
        ) from error
    required = {"revision", "owner", "defaults"}
    if (
        not isinstance(state, dict)
        or set(state) != required
        or state.get("revision") != revision
        or state.get("owner") != OBJECT_OWNER_ROLE
        or not isinstance(state.get("defaults"), dict)
    ):
        raise RuntimeError("0013 default-privilege rollback state is malformed")
    return state


def _reject_global_client_defaults(bind: sa.engine.Connection) -> None:
    """Refuse to proceed if a global client-role default would survive.

    Per-schema default privileges are additive to global ones, so a global
    client-role default for ``app_owner`` cannot be removed by the
    schema-scoped revokes this migration performs. Fail loudly instead of
    claiming a boundary that does not hold.
    """
    offending = bind.execute(
        sa.text(
            """
            select distinct grantee.rolname
            from pg_default_acl d
            join pg_roles owner on owner.oid = d.defaclrole
            cross join lateral aclexplode(d.defaclacl) acl
            join pg_roles grantee on grantee.oid = acl.grantee
            where owner.rolname = :owner
              and d.defaclnamespace = 0
              and grantee.rolname = any(:roles)
            order by grantee.rolname
            """
        ),
        {"owner": OBJECT_OWNER_ROLE, "roles": list(CLIENT_ROLES)},
    ).scalars().all()
    if offending:
        raise RuntimeError(
            "0013_default_acl_hardening cannot enforce the public default-ACL "
            "boundary because global client-role defaults exist for app_owner: "
            + ", ".join(offending)
        )


def _revoke_client_defaults(
    bind: sa.engine.Connection, roles: Sequence[str]
) -> None:
    owner = _quote(bind, OBJECT_OWNER_ROLE)
    for role in roles:
        quoted_role = _quote(bind, role)
        for _objtype, keyword in DEFAULT_ACL_TYPES:
            op.execute(
                f"alter default privileges for role {owner} in schema "
                f"{SCHEMA_NAME} revoke all on {keyword} from {quoted_role}"
            )


def _revoke_client_privileges_on_owned_objects(
    bind: sa.engine.Connection, roles: Sequence[str]
) -> None:
    if not roles:
        return
    owner_literal = "'" + OBJECT_OWNER_ROLE.replace("'", "''") + "'"
    roles_literal = ", ".join(
        "'" + role.replace("'", "''") + "'" for role in roles
    )
    bind.exec_driver_sql(
        f"""
        do $$
        declare
            client_role text;
            target record;
        begin
            foreach client_role in array array[{roles_literal}]
            loop
                for target in
                    select c.relname, c.relkind
                    from pg_class c
                    join pg_namespace n on n.oid = c.relnamespace
                    where n.nspname = '{SCHEMA_NAME}'
                      and pg_get_userbyid(c.relowner) = {owner_literal}
                      and c.relkind in ('r', 'S')
                loop
                    if target.relkind = 'r' then
                        execute 'revoke all on table {SCHEMA_NAME}.'
                            || quote_ident(target.relname)
                            || ' from ' || quote_ident(client_role);
                    else
                        execute 'revoke all on sequence {SCHEMA_NAME}.'
                            || quote_ident(target.relname)
                            || ' from ' || quote_ident(client_role);
                    end if;
                end loop;

                for target in
                    select p.oid::regprocedure::text as signature
                    from pg_proc p
                    join pg_namespace n on n.oid = p.pronamespace
                    where n.nspname = '{SCHEMA_NAME}'
                      and pg_get_userbyid(p.proowner) = {owner_literal}
                loop
                    execute 'revoke all on function ' || target.signature
                        || ' from ' || quote_ident(client_role);
                end loop;
            end loop;
        end
        $$
        """
    )


def _revoke_public_function_defaults(bind: sa.engine.Connection) -> None:
    owner = _quote(bind, OBJECT_OWNER_ROLE)
    op.execute(
        f"alter default privileges for role {owner} "
        "revoke execute on functions from public"
    )
    op.execute(
        f"alter default privileges for role {owner} in schema {SCHEMA_NAME} "
        "revoke execute on functions from public"
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _owner_exists(bind):
        raise RuntimeError(
            "0013_default_acl_hardening requires the externally "
            "provisioned app_owner role. Provision Embyr roles before applying "
            "this migration."
        )

    roles = _existing_client_roles(bind)
    _reject_global_client_defaults(bind)
    recorded = _record_defaults(bind, roles)
    _write_marker(bind, recorded)

    _revoke_client_defaults(bind, roles)
    _revoke_client_privileges_on_owned_objects(bind, roles)
    _revoke_public_function_defaults(bind)


def downgrade() -> None:
    bind = op.get_bind()
    state = _read_marker(bind)
    owner = _quote(bind, OBJECT_OWNER_ROLE)

    for objtype, keyword in DEFAULT_ACL_TYPES:
        for role, privileges in state["defaults"].get(objtype, {}).items():
            if not privileges:
                continue
            quoted_role = _quote(bind, role)
            privilege_list = ", ".join(privileges)
            op.execute(
                f"alter default privileges for role {owner} in schema "
                f"{SCHEMA_NAME} grant {privilege_list} on {keyword} "
                f"to {quoted_role}"
            )

    public_defaults = state["defaults"].get("public_function_execute", {})
    if public_defaults.get("global"):
        op.execute(
            f"alter default privileges for role {owner} "
            "grant execute on functions to public"
        )
    if public_defaults.get("schema"):
        op.execute(
            f"alter default privileges for role {owner} in schema "
            f"{SCHEMA_NAME} grant execute on functions to public"
        )

    bind.exec_driver_sql(f"comment on table {MARKER_OBJECT} is null")
