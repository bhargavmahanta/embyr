# Supabase / PostgreSQL provisioning

This directory owns the **platform-level** provisioning that Alembic must not
perform: creating cluster roles, converging their attributes, and granting the
migration identity the schema authority migrations require.

Alembic remains the schema source of truth. `app_owner` is the sole author of
Embyr application schema. Supabase's `postgres` role is reserved for platform
administration and provisioning only.

## Files

- `supabase_roles.sql` — idempotent role and schema-authority provisioning.
  Contains no credentials.

## Role topology (frozen M1 contract)

| Role | Login | Super | Bypass RLS | Create role | Create DB | Replication | Purpose |
|------|-------|-------|------------|-------------|-----------|-------------|---------|
| `app_owner` | yes | no | **no** | no | no | no | Migration identity and owner of Embyr objects |
| `app_backend` | yes | no | **no** | no | no | no | FastAPI request path under forced RLS |
| `app_worker` | yes | no | **yes** | no | no | no | Trusted background/cross-user work |
| `app_maintenance` | no | no | **yes** | no | no | no | Whole-account physical deletion |

Runtime roles (`app_backend`, `app_worker`, `app_maintenance`) must not be
members of any other role. The only approved administrative membership is
`app_owner` in `app_maintenance`, which migration `0012_rls_and_security` needs
to transfer ownership of `public.maintenance_delete_account(uuid)`.

## Schema authority

The hosted `public` schema is owned by the platform (`pg_database_owner`).
Ownership is **not** reassigned. Instead, `app_owner` is granted:

```sql
grant usage, create on schema public to app_owner with grant option;
```

This is sufficient (verified empirically on PostgreSQL 17) for `app_owner` to:

- create and own Embyr objects in `public`;
- alter and drop its own objects;
- set its own `ALTER DEFAULT PRIVILEGES`;
- grant and revoke the temporary `CREATE ON SCHEMA public` that `0012` needs to
  transfer the maintenance function;
- run every existing migration as a non-superuser.

## Ownership-transfer membership

PostgreSQL requires the transferrer to be able to `SET ROLE` the new owner
before `ALTER FUNCTION ... OWNER TO ...`. `INHERIT` and `ADMIN` are not needed:

```sql
grant app_maintenance to app_owner with set true, inherit false, admin false;
```

## Password boundary

`supabase_roles.sql` never contains passwords. Roles are created/converged
without credentials. Passwords and connection strings are provisioned
separately, stored only in secure environment/secret storage, and must never be
committed. Runtime and migration credentials/connection strings are established
by the database-connectivity work, not by this script.

## Applying

Run `supabase_roles.sql` as the Supabase administrative `postgres` identity
through one of:

- the Dashboard SQL Editor;
- the Supabase Management API SQL endpoint;
- an administrative `psql` connection.

It is idempotent and safe to re-run; attributes and grants are converged, and it
raises an error if the runtime-membership invariant is violated.

## Verifying

```sql
select rolname, rolsuper, rolbypassrls, rolcanlogin, rolcreaterole,
       rolcreatedb, rolreplication
  from pg_roles
 where rolname in ('app_owner', 'app_backend', 'app_worker', 'app_maintenance')
 order by rolname;

select member.rolname as member, granted.rolname as granted,
       am.admin_option, am.inherit_option, am.set_option
  from pg_auth_members am
  join pg_roles member on member.oid = am.member
  join pg_roles granted on granted.oid = am.roleid
 where member.rolname in ('app_owner', 'app_backend', 'app_worker', 'app_maintenance')
 order by 1, 2;

select has_schema_privilege('app_owner', 'public', 'usage')  as owner_usage,
       has_schema_privilege('app_owner', 'public', 'create') as owner_create;
```
