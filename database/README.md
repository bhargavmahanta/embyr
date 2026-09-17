# Database

This directory owns PostgreSQL schema evolution, seed data, and database-level
tests.

Once a migration reaches `main`, it is immutable. Corrections require a new
migration.

## Tooling

M1 uses Python 3.12+, SQLAlchemy 2.x, Alembic, psycopg 3, pgvector, pytest, and
Testcontainers. It does not initialize FastAPI or add deployment containers.

Install the persistence package and test dependencies from the repository root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -e "backend[test]"
```

## Database configuration

- `EMBYR_DATABASE_URL` selects the development database used by Alembic and
  the persistence session factory.
- `EMBYR_TEST_DATABASE_URL` may select a dedicated disposable test database.
  Its database name must contain `test`; the harness rejects common default
  database names.
- Without `EMBYR_TEST_DATABASE_URL`, the tests start an isolated PostgreSQL
  database with pgvector through Testcontainers and require a running
  Docker-compatible daemon.

Apply and inspect migrations with:

```powershell
.venv\Scripts\python -m alembic -c database/alembic.ini upgrade head
.venv\Scripts\python -m alembic -c database/alembic.ini current
.venv\Scripts\python -m alembic -c database/alembic.ini heads
.venv\Scripts\python -m alembic -c database/alembic.ini check
```

Run the database suite with:

```powershell
.venv\Scripts\python -m pytest database/tests -v
```

Downgrades are destructive development verification only. Run `downgrade
base` followed by `upgrade head` solely against a disposable test database.
Production recovery uses backups and forward-fix migrations.

## Provisioning boundary

Environment administrators create databases and credentials, enable `pgcrypto`
or `vector` when the migration owner lacks extension privileges, and create the
runtime roles. Migrations never create or alter cluster roles: migration
`0012_rls_and_security` verifies the externally provisioned roles and their
attributes and aborts when provisioning is incomplete, rather than silently
skipping the security boundary.

The M1 runtime roles are:

| Role | Runtime | Login | Bypass RLS | Owns objects | Purpose |
|------|---------|-------|------------|--------------|---------|
| `app_owner` | migration only | per environment | no | tables, indexes, trigger functions | schema evolution; never a request or worker runtime |
| `app_backend` | FastAPI | per environment | **no** | none | request-path DML under forced RLS |
| `app_worker` | background worker | per environment | **yes** | none | job claiming, evaluation, projections, stories, exports |
| `app_maintenance` | deletion service | NOLOGIN | **yes** | `public.maintenance_delete_account(uuid)` | whole-account physical deletion |

`0012` rejects any runtime role with `SUPERUSER`, `CREATEROLE`, `CREATEDB`, or
`REPLICATION`. It also verifies `app_backend` is `NOBYPASSRLS`, verifies
`app_worker` and `app_maintenance` are `BYPASSRLS`, and requires
`app_maintenance` to be `NOLOGIN`. Each runtime role must be standalone: none
of `app_backend`, `app_worker`, or `app_maintenance` may itself be a member of
another role. Incoming administrative membership such as `app_owner` in
`app_maintenance` remains permitted for ownership transfer.

Provisioning must give the migration identity enough authority to run `ALTER
FUNCTION ... OWNER TO app_maintenance`, grant the temporary schema `CREATE`
needed for that transfer, and run `ALTER DEFAULT PRIVILEGES FOR ROLE
<application object owner>`. For the default-privilege operation, the migration
identity must be the application object owner itself, a member with sufficient
`SET ROLE`/membership semantics, or an administrative/superuser identity capable
of the operation. The migration grants `app_maintenance` `CREATE` on `public`
only for the ownership transfer and revokes it in the same transaction.
Creating a `BYPASSRLS` role requires superuser authority, so on hosted
PostgreSQL the roles, attributes, and administrative membership remain
environment-admin responsibilities.

## Runtime grants and row-level security

`0012_rls_and_security` (current head) applies least-privilege grants and
enables `FORCE ROW LEVEL SECURITY` on every learner-owned table:

- Every learner-owned table carries `user_id` directly. A single policy scoped
  to `app_backend` reads the transaction-local `app.user_id` setting with
  `nullif(current_setting('app.user_id', true), '')::uuid`, so an absent or
  empty/reset setting fails closed without a uuid cast error. The FastAPI
  request path sets this value through
  `backend/app/db/session.py:set_current_user`.
- `app_backend` holds request-path DML on operational tables and read-only
  access to derived Learner State, WorldModel, recommendations, stories, and
  analyses. Canonical ontology and practical-challenge tables are read-only.
- `app_worker` holds `BYPASSRLS` and the DML needed for cross-user jobs,
  evaluation, and projections; immutable-source triggers remain enforced.
- `app_maintenance` holds `SELECT` and `DELETE` on learner-owned tables and
  owns the maintenance function. Only the trusted worker (`app_worker`) may
  execute it; `PUBLIC` retains no `EXECUTE`.
- `app_users` is intentionally outside learner RLS because authentication must
  resolve the internal UUID from `(auth_provider, auth_subject)` before a
  per-user context exists. It is protected by grants only.
- `CREATE` on schema `public` is revoked from `PUBLIC` and is not granted to
  runtime roles, so the hardened `search_path` on `maintenance_delete_account`
  (`pg_catalog, public, pg_temp`) cannot be shadowed.
- Where Supabase client roles (`anon`, `authenticated`, `service_role`) exist,
  their privileges on Embyr application tables are revoked. Embyr clients never
  access the database directly; the API owns authentication and authorization.
- PostgreSQL's implicit function default is global for each creator role, not
  schema-local. `0012` records the application object owner's effective global
  and `public`-schema defaults, revokes `PUBLIC EXECUTE` at both levels, and
  thereby prevents future functions created by that owner from inheriting
  public execution. Downgrade restores only the two recorded `PUBLIC EXECUTE`
  defaults and preserves unrelated default-ACL entries.

### Supabase deployment prerequisite

M1 is not deployable on a hosted Supabase project until that project has
provisioned the runtime roles and attributes above and demonstrated the
ownership transfer of `maintenance_delete_account` to `app_maintenance`. The
migration is provider-independent and deliberately verifies rather than
provisions roles; it cannot create `BYPASSRLS` roles or role memberships.
Future hosted migrations that create Embyr tables must also verify the actual
Supabase default ACLs do not re-grant `anon`, `authenticated`, or `service_role`
access. Migration 0012 does not speculate about unmeasured hosted table-default
ACLs.

## Account deletion maintenance path

`0011a_account_deletion` repairs whole-account deletion ahead of the security
migration:

- `public.maintenance_delete_account(uuid)` is a `SECURITY DEFINER` routine that
  deletes exactly one learner's owned rows with explicit, ordered `DELETE`
  statements and removes `app_users` last. A `NULL` target raises `22004`; an
  unknown target is a no-op, so retries are idempotent.
- The Experience Ledger guard permits DELETE of `learning_events` only when
  `current_user = 'app_maintenance'`. Its UPDATE path and all ordinary-role
  DELETE paths remain rejected.

Migration order is `0011_stories_and_exports` -> `0011a_account_deletion` ->
`0012_rls_and_security`. The routine is inert to application roles after
`0011a`: EXECUTE is revoked from PUBLIC and ownership is not transferred.
`0012` provisions `app_maintenance`, transfers function ownership, and grants
EXECUTE to the trusted worker.
