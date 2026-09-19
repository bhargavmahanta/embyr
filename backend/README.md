# Backend

The `embyr-persistence` package is Embyr's Python backend. It owns the SQLAlchemy
persistence models, the migration tooling, and the FastAPI application that
validates Supabase access tokens and propagates learner identity into
transaction-local RLS.

## Configuration

Process environment only; no secrets are committed and no dotenv dependency is
used.

| Variable | Required | Purpose |
|----------|----------|---------|
| `EMBYR_DATABASE_URL` | yes | Runtime database URL for the process role (FastAPI -> `app_backend`). Must require TLS. |
| `EMBYR_SUPABASE_AUTH_ISSUER` | yes | Supabase Auth issuer, e.g. `https://<project-ref>.supabase.co/auth/v1`. |
| `EMBYR_SUPABASE_JWT_AUDIENCE` | no | Expected token audience; defaults to `authenticated`. |
| `EMBYR_SUPABASE_JWKS_URL` | no | Overrides the derived `<issuer>/.well-known/jwks.json`. |

## Authentication trust model

1. The client sends `Authorization: Bearer <supabase-access-token>`.
2. The backend verifies the token **asymmetrically** (`ES256`/`RS256`) against
   the project JWKS. It validates signature, `iss`, `aud`, `exp`, requires the
   `sub` claim, and requires the Supabase `role` claim to be `authenticated`
   (`anon` and `service_role` tokens are rejected); `nbf` is honored when
   present. Any failure fails closed.
3. The verified external subject is resolved as
   `auth_provider = 'SUPABASE'`, `auth_subject = sub` against `app_users`. The
   external subject is never an Embyr primary key.
4. `GET /api/v1/me` and other authenticated routes require that mapping; an
   unmapped identity is `401 UNMAPPED_IDENTITY`.
5. `POST /api/v1/session/bootstrap` is the only route that may create the
   internal `app_users` row, idempotently through the unique
   `(auth_provider, auth_subject)` mapping.

The runtime database identity is always `app_backend`; the JWT `role` claim is
never translated into a PostgreSQL role.

## Transaction-local identity

After resolution, the internal `app_users.id` is written with
`set_config('app.user_id', <uuid>, true)` (see `app/db/session.py`). Because it
is transaction-local, it cannot survive commit or rollback, and a pooled
connection returns clean. Forced RLS on learner tables reads this value with
`nullif(current_setting('app.user_id', true), '')::uuid`, so an absent identity
fails closed.

## Local testing

Install and run from the repository root:

```bash
python -m venv .venv
.venv/bin/python -m pip install -e "backend[test]"
.venv/bin/python -m pytest backend/tests -q          # unit + FastAPI boundary
.venv/bin/python -m pytest database/tests -q         # database + RLS + identity
```

Auth unit tests sign tokens with locally generated keys; no live Supabase
endpoint is contacted. Database tests use Testcontainers unless
`EMBYR_TEST_DATABASE_URL` selects a disposable database.
