# M5 Task 1 persistence report

Implemented in commit `4b18d29` (Add immutable exploration delivery persistence and worker finalization grants).

Read and applied `docs/plans/m5-implementation.md` global constraints and Task 1. Historical migrations are unchanged. New revision `0018_exploration_delivery` descends directly from `0017_idempotency_key_reuse`; it adds nullable paired JSONB/TEXT columns and guards exploration identity and prepared snapshot against UPDATE. DELETE is unaffected, preserving account cascade deletion. Exploration ORM metadata matches the new columns/check.

Worker grant is exclusively UPDATE(status, completed_at) on assessment_sessions. No blanket session DML, backend learning_evidence grant, provisioning side effect, or new table. Downgrade removes only the added grant, trigger/function, check and columns.

## Validation

All commands ran from `/home/bhargav/.codex/worktrees/m5-exploration/embyr` with real disposable PostgreSQL via Docker, using `PYTHONPATH=backend:. /tmp/embyr-a9-venv/bin/python -m pytest`.

- Initial TDD red: `database/tests/test_exploration_delivery_migration.py -q` — **2 failed in 7.29s**, missing revision and missing worker column privilege.
- Intermediate run after migration creation before ORM/test corrections — **2 failed in 7.35s**; the shell's `python` executable was unavailable so planned edits had not executed. Retried edits with the specified venv interpreter.
- `database/tests/test_exploration_delivery_migration.py database/tests/test_alembic_marker_autogenerate.py -q` — **29 passed in 10.18s**.
- Final focused run (added actual worker-role SQL proof): `database/tests/test_exploration_delivery_migration.py database/tests/test_alembic_marker_autogenerate.py -q` — **30 passed in 10.99s**. Includes 0017→0018 preservation, paired fields, immutable snapshots/pinned identity, deletion cascade, downgrade/re-upgrade, real Alembic check, one current head, catalog grants and worker-role allowed/denied updates.
- Initial deletion/schema regression run: `database/tests/test_account_deletion_maintenance.py database/tests/test_migrations.py -q` — **1 failed, 15 passed in 11.07s**, because its upgrade-to-head assertion still expected 0017. Updated this generic current-head assertion to 0018; preserved historical revision assertions.
- Final deletion/schema regression run: `database/tests/test_account_deletion_maintenance.py database/tests/test_migrations.py -q` — **16 passed in 9.11s**.
- `git diff --check` — passed.

Only Task 1 files are in the implementation commit. Runtime/routes/content work belongs to the parent task. Whole-branch independent audit and full integration closure remain Task 6 responsibilities.

## Review follow-up

Read `.superpowers/sdd/m5/task1-review.md`. Revised `test_assessment_schema.py` to assert immediate exploration identity rejection before any answer, while retaining the objective mutation's response-insert revalidation. Full execution also found that the new trigger fires before the historical answered-exploration guard; updated that diagnostic expectation to the immutable identity error, preserving answered interaction/objective guards. No model/migration changes or historical migration edits.

- First combined run: `PYTHONPATH=backend:. /tmp/embyr-a9-venv/bin/python -m pytest database/tests/test_assessment_schema.py database/tests/test_exploration_delivery_migration.py -q` — **1 failed, 21 passed in 10.37s**, identifying the answered-exploration diagnostic expectation.
- Final same command — **22 passed in 10.77s**.

## Full database regression compatibility follow-up

The parent full database run (`/tmp/embyr-m5-db-regression.log`) reported **5 failed, 428 passed, 1 skipped in 114.51s**; each failure was a stale current-head expectation. Updated HEAD constants in default ACL and RLS tests, the hosted verifier's current-head check, and the idempotency guard's post-failure revision check. Historical target revisions and migrations are unchanged. The idempotency test still exercises 0017's duplicate-generation downgrade rejection; the failure rolls back the entire transaction including the preceding 0018 downgrade, leaving current head 0018.

- `PYTHONPATH=backend:. /tmp/embyr-a9-venv/bin/python -m pytest database/tests/test_default_acl_hardening.py database/tests/test_issue33_hosted_verifier.py database/tests/test_rls.py database/tests/test_idempotency_key_reuse.py -q` — **112 passed, 1 skipped in 91.68s**. Captured at `/tmp/embyr-m5-head-regressions.log`.
- `git diff --check` — passed.

## Additive response row-lock security fix (0019)

The parent real-backend API journey exposed a historical invoker trigger failure: response validation uses FOR SHARE on learning_objectives, while app_backend correctly has canonical SELECT only. Added `0019_response_lock_security`, descending from 0018, without editing historical migrations. It replaces only the response-validation function with a SECURITY DEFINER function owned by the existing trusted BYPASSRLS app_maintenance role, fixed search_path, schema-qualified tables/catalog, and no PUBLIC/backend/worker EXECUTE. Trigger execution remains available through the existing trigger. The invoker's forced-RLS INSERT check remains in effect.

Backend/member callers must match NEW.user_id to transaction-local app.user_id before privileged reads/locks. Trusted admin/schema calls remain supported. The existing complete owner/reference joins and FOR SHARE locks are retained, so concurrent objective identity changes cannot silently freeze inconsistent history. Maintenance receives canonical SELECT on learning_objectives and UPDATE(id) only on the four joined relations because PostgreSQL requires an UPDATE column privilege for FOR SHARE; no backend/worker privileges are expanded, and no backend evidence grant is added. Downgrade restores the original invoker behavior and removes the additional maintenance grants.

Updated only generic current-head expectations to 0019. The 0018 upgrade/downgrade test retains its explicit historical target and upgrades to head only for final Alembic metadata check. RLS ownership allowlist now includes this approved maintenance-owned trigger function while retaining the prohibition on runtime-owned relations.

Validation (same venv/PYTHONPATH and disposable PostgreSQL as above):

- Initial `database/tests/test_assessment_response_privileges.py -q`: **2 failed in 6.85s**, proving owned real-backend response privilege failure and absent SECURITY DEFINER boundary.
- Initial combined run: **1 failed, 2 passed, 21 errors in 19.73s**; corrected an overlong draft revision identifier (Alembic version column is VARCHAR(32)).
- Combined schema/security/delivery run: **1 failed, 25 passed in 28.78s**; retained historical 0018 migration target, moved its generic final metadata check to current head.
- `database/tests/test_assessment_response_privileges.py database/tests/test_assessment_schema.py database/tests/test_exploration_delivery_migration.py database/tests/test_alembic_marker_autogenerate.py -q`: **53 passed in 17.43s**. Includes backend and admin objective mutation races, isolation, upgrade/downgrade, and Alembic check.
- Six-file security/head/deletion run: **1 failed, 128 passed, 1 skipped in 125.59s**; updated the approved maintenance function ownership allowlist.
- `database/tests/test_assessment_response_privileges.py database/tests/test_rls.py -q`: **46 passed in 47.09s**.
- Final security tests additionally include cross-owner parent spoofing, unchanged backend canonical/evidence privileges, column-only maintenance grants, and a caller-created temporary pg_roles shadow attack. The trigger uses pg_catalog.pg_roles explicitly.
- Final `database/tests/test_assessment_response_privileges.py -q`: **3 passed in 8.32s**, including the temporary catalog-shadow attack check (`/tmp/embyr-m5-response-security-final2.log`).
- `git diff --check`: passed.
