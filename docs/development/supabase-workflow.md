# Supabase Development Workflow

This is the canonical, reproducible workflow for developing Embyr against
Supabase. It consolidates material that is otherwise spread across
[`database/README.md`](../../database/README.md),
[`database/provisioning/README.md`](../../database/provisioning/README.md),
[`backend/README.md`](../../backend/README.md), and
[`.env.example`](../../.env.example).

Scope: documentation only. Embyr's schema is owned by repository Alembic
migrations; the hosted Supabase Dashboard is used for platform setup, not for
schema authorship.

## A. Development architecture

Embyr separates responsibilities across four PostgreSQL roles. Every component
connects with the least-privileged role it needs; no runtime component
connects as a schema owner. The role topology is frozen and verified by
migration `0012_rls_and_security` and
[`provisioning/supabase_roles.sql`](../../database/provisioning/supabase_roles.sql).

| Role | Runtime | Purpose |
|------|---------|---------|
| `app_owner` | Alembic migrations only | Owns Embyr application objects and evolves the schema. Never serves request or worker traffic. |
| `app_backend` | FastAPI | Request-path DML under forced row-level security. `NOBYPASSRLS`. |
| `app_worker` | background worker | Cross-user jobs, evaluation, projections, stories, exports. `BYPASSRLS`. |
| `app_maintenance` | deletion service | Owns `public.maintenance_delete_account(uuid)` for whole-account physical deletion. `NOLOGIN`, `BYPASSRLS`. |

Runtime roles must stay least-privileged: they receive only the grants their
component needs, and none may be a member of another role. The single approved
administrative membership is `app_owner` in `app_maintenance`, which migration
`0012` needs for ownership transfer. See
[`database/README.md`](../../database/README.md) for the full grant and RLS
contract.

## B. Database connectivity

The development database is PostgreSQL 17.6 on hosted Supabase. The established
Embyr connection pattern is:

- **Supavisor Session mode** (shared pooler) on port `5432`;
- **role-scoped username** `<role>.<project-ref>`, for example
  `app_backend.<project-ref>`;
- **TLS required**: `sslmode=require`, or `sslmode=verify-full` with the
  downloaded server certificate and `sslrootcert`.

`EMBYR_DATABASE_URL` is a single variable supplied **per process** for that
process's role: Alembic uses `app_owner`, FastAPI uses `app_backend`, and the
worker uses `app_worker`. Credentials and connection strings are never
committed; they come from secure environment or secret storage.

The current Embyr session and prepared-statement behavior uses **Session mode**.
Transaction mode (port `6543`) is not used by Embyr because it does not
preserve the session semantics Embyr relies on. This is an Embyr constraint,
not a general statement about Supabase.

The direct endpoint (`db.<project-ref>.supabase.co:5432`) is a supported
fallback when the network reaches IPv6 or the project has paid IPv4 support.
Full rationale and the transaction-local identity contract live in
[`database/README.md`](../../database/README.md).

## C. Environment variables

All names are defined in [`.env.example`](../../.env.example). Embyr reads
**process environment variables only**. There is no `dotenv` dependency and no
environment file is loaded by application code. Inject variables locally
through your shell, an IDE run configuration, or your secret manager.

| Variable | Secret? | Purpose |
|----------|---------|---------|
| `EMBYR_DATABASE_URL` | **secret** | Database URL for the current process role. Must require TLS. |
| `EMBYR_TEST_DATABASE_URL` | **secret** | Optional dedicated disposable test database; its name must contain `test`. Without it, database tests use Testcontainers. |
| `EMBYR_SUPABASE_AUTH_ISSUER` | config | Supabase Auth issuer, e.g. `https://<project-ref>.supabase.co/auth/v1`. The Storage API endpoint is derived from it. |
| `EMBYR_SUPABASE_JWT_AUDIENCE` | config | Expected token audience; defaults to `authenticated`. |
| `EMBYR_SUPABASE_JWKS_URL` | config | Optional override of the derived `<issuer>/.well-known/jwks.json`. |
| `EMBYR_SUPABASE_STORAGE_BUCKET` | config | Private Storage bucket name (for example `embyr-media`). |
| `EMBYR_SUPABASE_STORAGE_SECRET_KEY` | **secret** | Server-only modern Supabase secret key (`sb_secret_...`); sent on the `apikey` header only. |
| `EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS` | config | Signed download URL lifetime in seconds; defaults to `300`. |

`.env.example` contains names and non-secret defaults only. No actual value
belongs in git. Do not commit `.env` or any `.env.*` file; those patterns are
ignored by [`.gitignore`](../../.gitignore) and only `.env.example` is tracked.

## D. Alembic authority

Repository Alembic migrations are the **source of truth** for Embyr-owned
schema. They are reviewed and versioned in git.

- Migrations must be applied with `app_owner` only.
- Migrations `0001` through `0013` are frozen after reaching `main`. Never edit
  a merged migration; correct mistakes with a new migration.
- New schema or security changes require a new, reviewed migration.
- Supabase Dashboard schema edits are not a substitute for a migration, and
  neither is a manual SQL change applied to a hosted database.
- Dashboard or manual schema authorship by `app_owner`-alternatives is
  prohibited; only `app_owner` authors Embyr schema through migrations.

Apply and inspect migrations from the repository root:

```bash
python -m alembic -c database/alembic.ini upgrade head
python -m alembic -c database/alembic.ini current
python -m alembic -c database/alembic.ini heads
python -m alembic -c database/alembic.ini check
```

See [`database/migrations/README.md`](../../database/migrations/README.md).

## E. Dashboard vs repository boundary

Keep the two surfaces separate when configuring the development environment.

**Supabase Dashboard / hosted platform setup (not schema):**

- creating the Supabase project;
- creating API keys and the modern server secret key;
- viewing Auth configuration (providers, issuer, audience);
- creating or inspecting the private Storage bucket where appropriate;
- platform-level hosted settings.

**Repository (schema and application behavior):**

- schema, roles, grants, and RLS;
- database functions and triggers;
- Alembic migrations;
- backend auth verification behavior;
- upload and storage application logic.

Platform provisioning that Alembic must not perform (cluster roles and schema
authority) lives in
[`provisioning/supabase_roles.sql`](../../database/provisioning/supabase_roles.sql)
and is applied by the platform administrative `postgres` identity, never by an
Embyr migration or runtime identity. See
[`database/provisioning/README.md`](../../database/provisioning/README.md).

## F. Supabase Auth

Embyr validates Supabase access tokens asymmetrically and maps the external
subject to an internal identity:

```
verified Supabase JWT
  -> auth_provider = 'SUPABASE'
  -> auth_subject = JWT sub
  -> lookup internal app_users row by (auth_provider, auth_subject)
  -> internal app_users.id
  -> set_config('app.user_id', <app_users.id>, true)   # transaction-local
  -> FORCE RLS on learner-owned tables
```

- The JWT `sub` is an opaque external identifier. It is **not** `app_users.id`
  and is never used as an Embyr primary key.
- Tokens are verified asymmetrically (`ES256`/`RS256`) against the project
  JWKS derived from the issuer; the backend is never given a signing secret.
- `iss`, `aud`, `exp`, and `sub` are validated, and `nbf` is honored when
  present. Any failure fails closed.
- Learner tokens use `role = authenticated`. `anon` and `service_role` tokens
  are **not** learner authentication and are rejected on authenticated routes.
- The JWT `role` claim is never translated into a PostgreSQL role. The runtime
  database identity is always `app_backend`.
- `POST /api/v1/session/bootstrap` is the only route that may create the
  internal `app_users` row, idempotently.

The full trust model is in [`backend/README.md`](../../backend/README.md).

## G. Supabase Storage

Object bytes live in a private Supabase Storage bucket; PostgreSQL stores only
durable, provider-independent object keys.

Bucket contract (platform provisioning, not a migration):

- name: `embyr-media`
- `public`: `false`
- no broad `storage.objects` policies are required by the capability model
- `file_size_limit` and `allowed_mime_types`: unset (no product policy yet)

Behavior:

- object keys are generated server-side (`users/<app_users.id>/artifacts/<opaque_uuid>`);
  the backend never accepts a client-chosen key and never signs an arbitrary path;
- signed upload/download URLs are ephemeral capabilities and are never
  persisted as durable state;
- the backend authenticates with the modern server-only `sb_secret_...` key,
  sent on the `apikey` header only; this key must never reach client code;
- uploads are authorized with `upsert=false`;
- upload completion currently advances `AUTHORIZED -> UPLOADED_UNVALIDATED`
  only. Full content validation, trusted SHA-256, metadata stripping, and
  `media_objects` creation are not implemented yet, and no upload reaches
  `VALIDATED`.

See [`backend/README.md`](../../backend/README.md) for the upload lifecycle and
the account-deletion/orphan-cleanup ordering contract.

## H. Hosted blockers and constraints

- Direct hosted database connectivity may require IPv6, or the paid IPv4
  add-on; the shared Supavisor Session pooler is the normal development path.
- Credentials are role-specific. There is no single shared application role.
- TLS must be explicitly required; libpq defaults to `sslmode=prefer` and can
  silently fall back to plaintext.
- Hosted verification must avoid unintended application, Auth, or database
  mutations. The M2 hosted verifier
  ([`database/tools/issue33_hosted_verifier.py`](../../database/tools/issue33_hosted_verifier.py))
  does not perform the destructive rebuild. Its `--preflight` and
  `--post-upgrade` modes are inspection-oriented, while its `--behavioral`
  mode is intentionally mutating: it creates temporary verification fixtures
  and temporarily grants/revokes `UPDATE` privileges while exercising worker
  behavior, then cleans up the temporary state.
- Developer tests must not be casually pointed at hosted production-like state.
  Until a disposable-target guard exists, the current safe practice is:
  - leave `EMBYR_TEST_DATABASE_URL` unset so tests start an isolated
    Testcontainers PostgreSQL with pgvector; or
  - point it only at a dedicated disposable database whose name contains
    `test`, never at a shared or production-like database.

These constraints are documented here as limitations. Guaranteeing that an
exported `EMBYR_DATABASE_URL` can never be targeted by tests is a separate,
future hardening task and is **not** implemented.

### M2 hosted verification outcomes

During the M2 hosted verification, the development setup established for Embyr
used:

- a Supabase project on PostgreSQL 17;
- a private Storage bucket named `embyr-media`;
- a Storage smoke verification that passed, with the final smoke fixture
  deleted afterward;
- a signed upload/download capability flow that was verified; and
- unsigned public access that was denied.

These were verified outcomes of the M2 work. This document does not assert a
live, present-tense hosted state; re-verify through the repository verifier
before relying on it.

## I. Developer setup walkthrough

1. Clone or fetch the repository and create the worktree/branch you will use.
2. Read [`.env.example`](../../.env.example) to see every variable name.
3. Obtain the required credentials securely (database role URL, Auth issuer,
   and the server Storage secret key) from your secret manager or team
   administrator. Never paste them into tracked files.
4. Supply the environment variables to each process (shell, IDE run config, or
   secret manager). Do not use a committed `.env` file.
5. Choose the correct database role for the process: `app_owner` for Alembic,
   `app_backend` for FastAPI, `app_worker` for the worker.
6. Run migrations with `app_owner` only:
   `python -m alembic -c database/alembic.ini upgrade head`.
7. Run the backend with `EMBYR_DATABASE_URL` scoped to `app_backend`.
8. Run the worker with `EMBYR_DATABASE_URL` scoped to `app_worker`.
9. Verify Auth configuration: issuer, audience, and JWKS resolve; a learner
   token has `role = authenticated`.
10. Verify Storage configuration: bucket `embyr-media`, `public = false`, and
    the server key authenticates on the `apikey` header.
11. Run local tests safely (see [`backend/README.md`](../../backend/README.md)):

    ```bash
    python -m venv .venv
    .venv/bin/python -m pip install -e "backend[test]"
    .venv/bin/python -m pytest backend/tests -q
    .venv/bin/python -m pytest database/tests -q
    ```

No step in this walkthrough includes real secret values.

## J. Safety notes

- Never commit `.env` files or any secret value.
- Never print, log, or return the Storage secret key.
- Do not fall back to `service_role` for learner authentication.
- Do not treat signed upload/download URLs as durable state.
- Never use a JWT `sub` as an internal Embyr user id.
- Never edit a frozen migration (`0001`–`0013`); add a new migration instead.
- Do not run destructive tests or `alembic downgrade` against a hosted,
  non-disposable database. Downgrades are development verification only, on a
  disposable database.
