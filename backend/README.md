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
| `EMBYR_SUPABASE_AUTH_ISSUER` | yes | Supabase Auth issuer, e.g. `https://<project-ref>.supabase.co/auth/v1`. The Storage API endpoint is derived from it. |
| `EMBYR_SUPABASE_JWT_AUDIENCE` | no | Expected token audience; defaults to `authenticated`. |
| `EMBYR_SUPABASE_JWKS_URL` | no | Overrides the derived `<issuer>/.well-known/jwks.json`. |
| `EMBYR_SUPABASE_STORAGE_BUCKET` | yes | Private Storage bucket name (for example `embyr-media`). |
| `EMBYR_SUPABASE_STORAGE_SECRET_KEY` | yes | Server-only modern Supabase secret key (`sb_secret_...`); sent on the `apikey` header only. |
| `EMBYR_STORAGE_DOWNLOAD_URL_TTL_SECONDS` | no | Signed download URL lifetime in seconds; defaults to `300`. |

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

## Private object storage

The backend stores object bytes in a private Supabase Storage bucket and keeps
only durable, provider-independent object keys in PostgreSQL. It never accepts
a client-chosen key and never signs an arbitrary path.

- Upload authorization (`POST /api/v1/uploads`) creates an `AUTHORIZED`
  `upload_sessions` row with a server-generated key of the form
  `users/<app_users.id>/artifacts/<opaque_uuid>`, commits it, and only then
  mints a short-lived signed upload capability (`upsert=false`). The signed URL
  and token are ephemeral and are never persisted in `idempotency_records`,
  `upload_sessions`, or logs.
- Upload completion (`POST /api/v1/uploads/{upload_id}/complete`) reads the key
  from `upload_sessions`, inspects Storage metadata for existence, size, and
  reported content type, then advances `AUTHORIZED -> UPLOADED_UNVALIDATED`.
  An absent object (`UPLOAD_OBJECT_MISSING`) or Storage failure
  (`STORAGE_UNAVAILABLE`) is retryable; a present object whose metadata does not
  match is terminal (`REJECTED`).
- Full content validation, trusted SHA-256, metadata stripping, and
  `media_objects` creation are intentionally out of scope for Issue #35. No
  upload reaches `VALIDATED` yet.
- Download capabilities are minted only from a durable, ownership-checked key;
  there is no raw-upload download route. `create_download_capability` is a
  service operation for future artifact/export read models.
- The server credential is a modern Supabase secret key sent on the `apikey`
  header only; no `authenticated` Storage policies are required, because the
  backend mints narrow, token-scoped capabilities.

### Bucket contract (platform provisioning)

Bucket provisioning is a platform operation, not an Alembic migration. The
approved contract is one private bucket per Supabase project:

- name: `embyr-media`
- `public`: `false`
- `file_size_limit`: unset (no product size policy exists yet)
- `allowed_mime_types`: unset (no product MIME allowlist exists yet)
- `storage.objects` policies: none required for the capability model

### Account deletion and orphan cleanup (future ordering)

`maintenance_delete_account(uuid)` deletes database rows only; deleting a row
does not delete a Storage object. Physical cleanup must therefore run, in
order:

1. enumerate the durable object keys while the database references still exist;
2. delete the Storage objects;
3. verify and handle partial failures;
4. only then execute physical database account deletion.

Abandoned `AUTHORIZED` uploads, `REJECTED` uploads, and export result objects
are reconciled by the same future worker/maintenance scope. Issue #35 documents
this contract and does not modify `maintenance_delete_account`, `0011a`, or the
worker deletion architecture.

## Recommendation engine packaging

The backend wheel includes the frozen M3 pure simulator package and the versioned
recommendation policy JSON files. Build from the repository checkout so the
`research/recommendation/simulator` source is present. Runtime query embeddings
use `EMBYR_VOYAGE_API_KEY` when semantic retrieval is enabled. Document
embeddings are derived data keyed by `entity-document/v1`; ontology ingestion
must refresh them when a selected entity version changes.
