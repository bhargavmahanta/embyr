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

Environment administrators create databases and credentials and enable
`pgcrypto` or `vector` when the migration owner lacks extension privileges.
The final M1 security migration will validate the provisioned runtime roles and
apply grants and row-level-security policies; it will not store role passwords
or silently skip missing security configuration.
