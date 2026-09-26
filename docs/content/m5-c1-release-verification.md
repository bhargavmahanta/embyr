# M5-C1 human content approval and release-candidate verification

The human content gate is complete: **3 / 3 APPROVED**, with no unresolved notes
and no package-byte changes. Bhargav Mahanta explicitly approved each asset in
the M5-C1 conversation and accepted identical STRONG_HINT / EXPLANATION wording
as nonblocking for this pilot. No AI approval was substituted for that decision.

Starting HEAD: `ed95e346d5d92a42361ab3712bad806516deda98`.
Frozen main baseline: `de332683cb54d68afc66bbcb5c5c5629016ed1eb`.
Branch: `bhargav/m5-exploration`.

## Exact approval boundary

All three assets reside in `backend/app/learning/packages/pilot-v1.json`.
Package identity/version: `c105ee83-8ec9-58d6-a8df-b6a2974693d4` / 1.
Approval uses `app.learning.content.package_digest()`, SHA-256 of the exact file
bytes, as required by [pilot-review.md](pilot-review.md):

```text
4bb87f2c3c852a2e30de2dcc7f2a7b72d871a077d0395370de56fbdfc294a3a1
```

This same package digest binds **each** asset approval. Per-asset canonical
hashes in the private pre-review inventory are diagnostics, not replacement
approval digests. The original raw-byte snapshot, human verdicts and operational
HUMAN attestation are stored outside the checkout with restricted access. The
approval was recorded at `2026-09-26T15:08:30Z` from the explicit human message;
the procedure defines no separate approval-mechanism version.

| Asset | Source JSON pointer | Content identity / version | Entity identity / version | Verdict |
|---|---|---|---|---|
| Everyday reasoning | `/definitions/0`, `/entities/0` | `a0b1f3ee-6006-5d58-b07d-f0fd854aaca6` / 1 | `32431fed-6c8e-5d02-9ba7-3d160fb0d4ad` / 1 | HUMAN APPROVE |
| Noticing patterns | `/definitions/1`, `/entities/1` | `33b7c692-57cd-51f8-bad4-e115b7c722cc` / 1 | `db71444d-73d4-5cd9-bf19-110ad7102318` / 1 | HUMAN APPROVE |
| Comparing fairly | `/definitions/2`, `/entities/2` | `d1ec9c81-7511-50f3-86b9-997884d97b0d` / 1 | `fffc25fc-5a72-5606-8250-a49e8c150ee1` / 1 | HUMAN APPROVE |

The file retains its original AI-assisted draft authoring metadata. Rewriting
that metadata would change approved bytes; runtime authorization comes from the
valid external HUMAN attestation. Any future package-byte change invalidates
this approval and requires a new human review of the new digest.

## Explicit disposable provisioning

The documented operator CLI was run against a new disposable local PostgreSQL
17 database with the actual HUMAN attestation, without the TEST override. It was
run twice to verify idempotency, followed by the documented `--check-only` command.
No application-startup provisioning and no hosted/production mutation occurred.

Persisted entity/version/objective identity and text matched the approved package.
Each entity was REVIEWED at current version 1, with exactly one version row and
the exact HUMAN approval digest in version source metadata. All three exact
definitions were available through runtime lookup. There were exactly three
objectives, three primary-domain memberships, two PART_OF and two RELATED_TO
edges pinned to version 1, and no REQUIRES edges or extra ontology assets.

| Coverage metric | Result |
|---|---:|
| Expected assets | 3 |
| Found assets | 3 |
| Human-approved assets | 3 |
| Explicitly provisioned assets | 3 |
| Deliverable assets | 3 |
| Missing assets | 0 |
| Unexpected assets | 0 |

**Provisioning and coverage: PASS.** The disposable database was destroyed after
verification; this does not claim content is installed in a production service.
Production operators must execute the same explicit procedure in a separately
authorized environment using the external approval.

## Fresh post-approval verification

| Gate | Result |
|---|---|
| Full backend and frozen M3 suites | **1,195 passed**, 13.30s |
| Full PostgreSQL 17 database suite | **464 passed, zero skipped**, 115.07s |
| Content/schema, provisioning and coverage tests | PASS; included in the full suites |
| M5 lifecycle integration and public client fixtures | PASS; included in the full suites |
| Actual HUMAN-attestation public API / real worker journey | PASS; bootstrap/onboarding/recommendation/ACCEPT/delivery/assessment/answer/completion/late evaluation/feedback/reflection/edit |
| Prepared snapshot immutability with exact private definition | PASS; attempted mutation rejected and snapshot preserved |
| One Alembic head | `0019_response_lock_security` |
| Fresh isolated `alembic check` | PASS: no new upgrade operations detected |
| Upgrade/downgrade and role/RLS regressions | PASS; included in the database suite |
| Source distribution and wheel | PASS; packaged code/content bytes match source |
| Installed wheel outside checkout | PASS; all three exact HUMAN-approved definitions deliverable |
| Frozen M3/M4 and historical migrations | Unchanged; protected-path diff is empty and full regression passes |
| `git diff --check` | PASS |

The suites emitted the existing Starlette TestClient deprecation warning.
Evidence was captured on the verification host in
`/tmp/embyr-m5-c1-unit.log`, `/tmp/embyr-m5-c1-database.log`,
`/tmp/embyr-m5-c1-provision.log` and `/tmp/embyr-m5-c1-build.log`; private
provisioning evidence records each asset's persisted identity/version/digest.

The tests preserve empty-interest Surprise, historical delivery, optional
completion, unanswered-check abandonment, late evaluation without reopening,
supported-only weak evidence, private editable reflection, learner-controlled
pause/return/resume, worker fencing/retry and frozen recommendation semantics.
No runtime, content, API, policy, worker or historical migration bytes changed
during M5-C1; this follow-up changes verification documentation only.

## Release and governance boundary

The exact release-candidate SHA is recorded after this verification-only commit
in the external freeze record and the implementation PR description, with a clean
worktree. This avoids a self-referential commit hash in its own tracked file.
The [independent implementation audit](../architecture/m5-independent-audit.md)
has zero HIGH, NORMAL or open LOW findings; an additional independent PR check is
performed after opening the PR.

Existing GitHub milestone **#5 — M5 — Exploration Experience** and umbrella
**#92 — [M5] Exploration Experience** are reused. No duplicate governance objects
are required. The PR remains unmerged and the milestone remains open.

Android scaffolding may proceed separately against frozen public DTOs, fixtures
and lifecycle semantics. Android implementation, learner-state/Curiosity Memory
projection, world/forest growth, Curiosity Stories, generative AI, practical
artifacts and offline synchronization are excluded from this backend PR.
