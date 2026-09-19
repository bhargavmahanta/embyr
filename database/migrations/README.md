# Migrations

Embyr's PostgreSQL schema is defined by the versioned Alembic migrations in
`versions/` (`0001_foundation` through `0013_default_acl_hardening`). These
migrations are the source of truth for Embyr-owned schema.

- Migrations merged to `main` are immutable. Correct mistakes with a
  subsequent migration; never edit a merged migration.
- Apply migrations with `app_owner` only. Each process connects with its own
  least-privileged role; see
  [`docs/development/supabase-workflow.md`](../../docs/development/supabase-workflow.md).
- Supabase Dashboard schema edits are not a substitute for a migration.

Apply and inspect from the repository root:

```bash
python -m alembic -c database/alembic.ini upgrade head
python -m alembic -c database/alembic.ini current
python -m alembic -c database/alembic.ini heads
python -m alembic -c database/alembic.ini check
```

See [`database/README.md`](../README.md) for the schema, RLS, and provisioning
contracts.
