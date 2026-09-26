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
