# M6-05 — Final projection operations and acceptance gate

Status: implementation and local release-candidate verification in progress.
Issue: #108. Baseline: `6f699d6f0d9095d3e680e5c1ed488a3442536c88`.
Worktree: `/home/bhargav/orca/workspaces/embyr/m6-05-final-acceptance`.
Branch: `bhargav/m6-05-final-acceptance`; sole writer: Codex.

The frozen [M6 contract](../api/m6-projection-memory-world-v1.md),
[schema](../api/schemas/m6-v1.schema.json), and
[fixtures](../api/fixtures/m6-v1.json) remain authoritative. This issue adds
no API route, migration, grant, ranking feature, or automatic backfill.

## Internal operator

Invoke only from a reviewed internal environment with an existing trusted
database credential and a TLS-required `EMBYR_DATABASE_URL`. The operator never
prints the URL. Replace the UUID below with the exact reviewed owner ID; there
is no wildcard or `--all` mode. A credential must already be allowed to
`SET LOCAL ROLE` to the required role. This issue does not provision one.

```text
python -m app.learning.projection_operator bootstrap --user-id 11111111-1111-4111-8111-111111111111
python -m app.learning.projection_operator bootstrap --user-id 11111111-1111-4111-8111-111111111111 --apply
python -m app.learning.projection_operator audit --user-id 11111111-1111-4111-8111-111111111111
python -m app.learning.projection_operator requeue --user-id 11111111-1111-4111-8111-111111111111 --source-group 12345
python -m app.learning.projection_operator requeue --user-id 11111111-1111-4111-8111-111111111111 --source-group 12345 --apply
```

Run a dry-run before each mutation, inspect its bounded status/counts, then
invoke `--apply` explicitly if the review still authorizes that exact owner and
group. Dry-run rolls the whole transaction back. It does not reserve a cutoff
or authorize a later apply on its own. Apply repeats every check under its own
locks and may refuse if the state changed. Refusals emit a bounded category;
the tool does not print reflection text, answers, source metadata, evidence
payloads, credentials, signed URLs, or SQL errors.

### Historical bootstrap

Bootstrap switches to existing `app_maintenance` authority. That NOLOGIN role
can be reached only through an already provisioned trusted connection where
environment policy allows role switching. The transaction uses READ COMMITTED.
It first takes the existing owner-existence lock, then locks the per-user source
head `FOR UPDATE`. Only then does it read source sequence `C` and database
`clock_timestamp()` as `cutoff_at`. The head lock remains held until commit.
Sources waiting behind it allocate after the baseline marker.

An existing user in `REQUIRED` state is eligible. A post-install `READY` user
with no baseline metadata is a fresh no-op. A coherent `READY` baseline with
its original marker is an idempotent no-op; it keeps the original cutoff.
Inconsistent metadata and unknown Learner State or World provenance are
refusals, never repair requests. In particular, numeric legacy understanding,
foreign World identity, invalid pins/seeds, topology, or revision stream are
not adopted or overwritten.

The operator enumerates supported owned ledger events by factual occurrence
time, receipt time, command identity, event ordinal, and event UUID. It calls
the existing closed M6 capture function, which reconstructs lineage from
owned rows and reuses identical receipts in `1..C`. Any unsupported or
contradictory source fails the whole import. It next enumerates current
supported evidence by evidence UUID. New historical evidence snapshots contain
the current status and a null `transition_at` because an old transition instant
cannot be inferred. An identical already-captured transition retains its
original known instant. No intermediate correction history is invented.

After historical receipts are appended, one `learner-projection/v1:baseline`
marker records exactly `C` and `cutoff_at`. The complete `1..B` prefix then
passes parser, lineage, and reducer validation before commit. Its allocated
sequence `B` and the `READY`/cutoff metadata commit together.
The existing append function extends its transaction-group job to `1..B`.
Failure rolls back every imported receipt, head increment, marker, metadata
update, and job change. Baseline publication uses the existing projection
worker; old ordinary jobs already covered by `B` later acknowledge without
another World revision.

### Read-only audit

Audit switches to owner-scoped `app_backend` reads in a repeatable-read,
read-only transaction. At checkpoint horizon `H`
it loads only immutable receipts `1..H`, runs the same pure reducer, compares
both checkpoint fingerprints, objective state and provenance, World identity,
pins, seeds, semantic snapshot, current revision, and canonical complete delta
reconstruction through the existing publisher verification. If source head is
ahead of `H`, the unpublished suffix is reported as pending; audit does not
compare it to published state or advance the checkpoint. A blocked group is
diagnostic. Any drift is a bounded refusal; audit has no write or repair mode.

### Safe same-group requeue

Requeue switches to existing `app_worker` authority. It takes the owner lock,
checkpoint `FOR UPDATE`, then the target projection job `FOR UPDATE`. The
requested group must equal the checkpoint's current blocking group and have
exactly one `FAILED` projection job. The immutable payload, owner, group range,
baseline gate, earliest unprocessed position, checkpoint fingerprint, current
published projection, and reducer over the complete target prefix must all
validate. `PENDING`, `RUNNING`, `RETRYABLE_FAILURE`, `SUCCEEDED`, a deleted
owner, a wrong group, and corrupt facts are refused.

Apply reuses that same job ID and payload. It sets `PENDING`, attempt count
zero, database-current availability, and clears lease/completion fields. It
atomically clears only the matching checkpoint block and failure code.
Checkpoint horizon, generation, and fingerprints stay unchanged. Requeue does
not repair receipts, World history, objective state, or a deterministic
publisher defect. The normal worker still must claim and publish the job.

## Verification and release boundary

The disposable PostgreSQL suite tests historical import, overlap, unknown
provenance, rollback, lock/cutoff races, audit corruption, failed-job recovery,
trusted deletion, and owner isolation. The final API journey uses the normal
`app_backend` request role and `app_worker` evaluation/projection roles. It
checks projection lag, Learner State, Memory, World, and complete delta
reconstruction. Existing M6-02/03/04 suites retain capture, replay,
correction, deletion races, private reads, and role-isolation coverage. Frozen
M3/M4 tests and the M6-05 compatibility guard check categorical readiness,
distinct hard-prerequisite reasons, preference suppression, profile identity,
weights, and no-result policy without changing recommendation production code.

Trusted deletion remains `public.maintenance_delete_account(uuid)`; no HTTP
delete route was added. Verify M6 owned rows and the user are gone while a
second owner remains. Database deletion does not itself assert deletion of
external Storage objects. New M6 receipts and projections may be future export
requirements, but this issue implements no export path.

The local release-candidate gate passed: M6-05 operator/journey tests 29,
M6-05 recommendation compatibility 18, full disposable PostgreSQL suite 668
passed with one intentional historical-verifier skip, backend suite 440, and
recommendation/research suite 856. Focused prior-M6 checks passed: M6-02 84,
M6-03 publisher 50 and reducer 44, M6-04 reads 42. Migration upgrade to
0020, Alembic check, downgrade to 0019, and upgrade back to 0020 passed.
The package wheel contains the operator; imports, lint, local links, and
`git diff --check` passed. These are local tests only. No hosted bootstrap,
production rollout, M7 work, or PR merge is part of #108 implementation.

The first full database run exposed stale pre-0020 test assumptions, classified
`STALE · LOW`: several tests still named 0019 as the repository head, the
current RLS inventory omitted 0020's three metadata tables and reviewed
maintenance functions, and the frozen Issue #33 verifier's synthetic old
Exploration event violates the 0020 capture boundary. The historical verifier
now runs against an isolated 0019 database; current-head tests assert 0020's
exact reviewed policy/grant additions. No historical migration, grant, or
runtime capture behavior changed to make those tests pass.

Local disposable PostgreSQL 16 + pgvector characterization, without an SLA:

| Operation | Receipts | Groups | Wall time |
| --- | ---: | ---: | ---: |
| Bootstrap dry-run, small | 2 | 1 | 0.061 s |
| Bootstrap apply, small | 2 | 1 | 0.060 s |
| Audit, small published prefix | 2 | 1 | 0.039 s |
| Bootstrap dry-run, larger | 202 | 1 | 0.694 s |
| Bootstrap apply, larger | 202 | 1 | 0.798 s |
| Audit, larger published prefix | 202 | 1 | 0.102 s |
| Requeue dry-run | 1 | 1 | 0.044 s |
| Complete real-role API journey | — | — | 1.192 s |

These are individual local observations; database setup and test fixture
provisioning are excluded from each measured operation. Complete-prefix
validation, owner/head locking, and role separation were retained.
