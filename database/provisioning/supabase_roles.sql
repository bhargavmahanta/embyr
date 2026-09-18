-- Embyr Supabase/PostgreSQL role provisioning.
--
-- Purpose
-- -------
-- Create and converge the PostgreSQL roles required by Embyr's frozen M1
-- security boundary (``0012_rls_and_security``) and grant the dedicated
-- migration/object owner the schema authority it needs.
--
-- Execution
-- ---------
-- Run as a Supabase administrative identity (the project ``postgres`` role)
-- through the Dashboard SQL Editor, the Management API, or an admin ``psql``
-- session. This script is idempotent and safe to re-run.
--
-- Credentials
-- -----------
-- This file intentionally contains NO passwords, connection strings, API keys,
-- or other secrets. Role passwords are provisioned separately and stored only
-- in secure environment/secret storage. See ``README.md`` in this directory.
--
-- Authority boundary
-- ------------------
-- This script only creates cluster roles, converges their attributes, and
-- grants schema authority/membership. It never creates application tables,
-- never changes RLS, and never edits migrations. Alembic remains the schema
-- source of truth, and ``app_owner`` remains the sole author of Embyr schema.

-- 1. Create roles when absent. Attributes are converged in step 2 so the
--    script has a single source of truth for the approved attribute matrix.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'app_owner') then
        create role app_owner;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'app_backend') then
        create role app_backend;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'app_worker') then
        create role app_worker;
    end if;
    if not exists (select 1 from pg_roles where rolname = 'app_maintenance') then
        create role app_maintenance;
    end if;
end
$$;

-- 2. Converge attributes on every run.
--    app_owner       migration/object owner; never a request or worker runtime.
--    app_backend     request runtime; RLS must apply, so NOBYPASSRLS.
--    app_worker      background runtime; cross-user work, so BYPASSRLS.
--    app_maintenance account deletion; NOLOGIN and BYPASSRLS.
--
--    The SUPERUSER attribute is intentionally not set here. PostgreSQL forbids
--    a non-superuser from specifying SUPERUSER/NOSUPERUSER in ALTER ROLE, and
--    the host administrative identity (``postgres``) is not a superuser. Newly
--    created roles are NOSUPERUSER by default; step 5 verifies that every
--    attribute, including NOSUPERUSER, matches the approved matrix and aborts
--    if a pre-existing role violates it.
alter role app_owner
    with login nobypassrls nocreaterole nocreatedb noreplication;
alter role app_backend
    with login nobypassrls nocreaterole nocreatedb noreplication;
alter role app_worker
    with login bypassrls nocreaterole nocreatedb noreplication;
alter role app_maintenance
    with nologin bypassrls nocreaterole nocreatedb noreplication;

-- 3. Schema authority app_owner needs.
--    ``USAGE`` lets it reference public objects; ``CREATE ... WITH GRANT
--    OPTION`` lets it create/own Embyr objects and lets migration 0012 grant
--    and revoke the temporary ``CREATE`` that transfers
--    ``public.maintenance_delete_account(uuid)`` to app_maintenance.
--    Schema ownership intentionally stays with the platform
--    (``pg_database_owner``); it is not reassigned.
grant usage, create on schema public to app_owner with grant option;

-- 4. Minimum ownership-transfer membership required by 0012.
--    PostgreSQL requires the transferrer to be able to ``SET ROLE
--    app_maintenance`` before ``ALTER FUNCTION ... OWNER TO app_maintenance``.
--    INHERIT and ADMIN are deliberately omitted; SET is the minimum.
grant app_maintenance to app_owner with set true, inherit false, admin false;

-- 5. Fail loudly if an approved invariant does not hold after provisioning.
do $$
declare
    offending text;
    transfer_membership integer;
begin
    select string_agg(
               format(
                   '%s (superuser=%s, bypassrls=%s, login=%s, createrole=%s, '
                   'createdb=%s, replication=%s)',
                   rolname, rolsuper, rolbypassrls, rolcanlogin,
                   rolcreaterole, rolcreatedb, rolreplication
               ),
               '; ' order by rolname
           )
      into offending
      from pg_roles
     where rolname in ('app_owner', 'app_backend', 'app_worker', 'app_maintenance')
       and (
               rolsuper
            or rolcreaterole
            or rolcreatedb
            or rolreplication
            or (rolname in ('app_owner', 'app_backend')
                and (rolbypassrls or not rolcanlogin))
            or (rolname = 'app_worker'
                and (not rolbypassrls or not rolcanlogin))
            or (rolname = 'app_maintenance'
                and (not rolbypassrls or rolcanlogin))
       );

    if offending is not null then
        raise exception
            'role attributes violate the approved matrix: %', offending;
    end if;

    select string_agg(
               format('%s -> %s', member.rolname, granted.rolname),
               ', ' order by member.rolname, granted.rolname
           )
      into offending
      from pg_auth_members am
      join pg_roles member on member.oid = am.member
      join pg_roles granted on granted.oid = am.roleid
     where member.rolname in ('app_backend', 'app_worker', 'app_maintenance');

    if offending is not null then
        raise exception
            'runtime roles must not be members of other roles; found: %',
            offending;
    end if;

    select count(*)
      into transfer_membership
      from pg_auth_members am
      join pg_roles member on member.oid = am.member
      join pg_roles granted on granted.oid = am.roleid
     where member.rolname = 'app_owner'
       and granted.rolname = 'app_maintenance';

    if transfer_membership <> 1 then
        raise exception
            'app_owner must be a member of app_maintenance for the 0012 '
            'ownership transfer';
    end if;
end
$$;
