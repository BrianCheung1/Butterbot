# Slice 1.0 remediation candidate

This candidate is prepared for independent review, not declared PASS. Native Linux
execution of the exact reviewed candidate remains required. Slice 1.1 was not started.

## Behavior

- Revision `20260914_0002` rejects aggregate identity/ownership changes using SQLite
  BEFORE UPDATE triggers, with null-safe comparisons; no-op assignments remain allowed.
  Protected fields: players.id/discord_user_id; economy_accounts.id/player_id/account_kind/
  currency_key/system_key; economy_account_balances.account_id/account_kind.
- The upgrade reconstructs missing aggregate sentinel rows once while stopped, covering
  holes created by the old update bypass. It does not repair missing economic state.
- Startup and the stopped-service verifier reject same-head stale schemas, missing
  required indexes/triggers, changed table definitions, and weakened ledger/transport
  constraints through a case-sensitive full schema manifest. Checks remain bounded by
  schema object count. Raw SQL identity changes abort before corruption occurs; surviving
  incomplete aggregates fail readiness. The manifest includes explicit indexes and table
  SQL that defines implicit uniqueness indexes.
- Historical baseline trigger DDL is embedded in the migration, with no mutable runtime
  schema dependency. A frozen snapshot and monkeypatch/upgrade/downgrade tests establish
  rebuild independence. New identity triggers belong to the new migration.
- The native runner requires collected, passing effective-capability coverage. Failure,
  skip, or missing collection fails. Only the exact namespace test with the documented
  host-denial reason can skip; unrelated skips and missing unshare fail.
- Future input-derived outcomes require explicit byte/depth/collection limits, recorded
  in decisions. Optional capacity-validator hardening was deferred; evidence is unchanged.

## Tests

`tests/test_release_gate_remediation.py` adds real SQLite mutation fixtures for each
manifest object, individual identity fields, multi-column and multi-row updates,
statement failure and explicit rollback, stale-sentinel deletion, weak ledger/transport
constraints, same-head baseline shape, startup and stopped-service verification, frozen
baseline independence, and migration of the reproduced preexisting hole. Runner unit
cases cover capability pass/fail/error/skip/absence and exact namespace skip policy.
Existing migration/revision assertions and identity-error expectations were updated.

## Verification

Commands use the repository `.venv/Scripts` executables on Windows, Python 3.13.

- `ruff check .`: passed.
- `ruff format --check .`: passed (85 files).
- `pyright`: passed, zero errors/warnings.
- `pytest -q -ra` and `pytest -q -ra -x`: each 405 passed, 32 skipped, one cache-write warning.
  A preceding full run reported a failure and stalled without a traceback; it was
  interrupted. Both the fail-fast rerun and subsequent exact-command rerun completed successfully. This intermittent event
  should remain visible to the independent reviewer.
- Focused release-remediation, prior gate-findings, and migration suites: 110 passed
  before the final additional preexisting-hole regression; the final remediation-only
  suite passed all 49 tests. All are also included in the full suite.
- `alembic upgrade head`: passed against a fresh uniquely named temporary database.
- `alembic check`: passed, no new upgrade operations detected.
- `git diff --check`: passed; Git emitted existing LF/CRLF notices.

32 skips are expected on this Windows host: 7 native kernel gate tests, 7 Linux
process-lock tests, 4 POSIX SIGTERM cases, 13 Linux storage-permission cases, and 1
file-symlink test because Windows did not permit symlink creation. Pytest also emitted
one cache-write permission warning. No native gate evidence was fabricated.

Run the documented root-controlled native gate on the provisioned Linux host with real
service/admin identities, ext4/XFS storage and capability tooling. Preserve the report
and exact candidate identity. Native evidence is an unresolved gate prerequisite.

## Exact files changed in this remediation

The working tree already contained extensive Slice 1.0 changes when this task began.
This list identifies files edited or added by this remediation, not all preexisting changes.

- `benchmarks/native_linux_gate.py`
- `migrations/versions/20260825_0001_slice_1_0_baseline.py`
- `migrations/versions/20260914_0002_aggregate_identity.py`
- `src/butterbot/infrastructure/persistence/readiness.py`
- `src/butterbot/infrastructure/persistence/release_manifest.py`
- `tests/baseline_schema_snapshot.json`
- `tests/test_release_gate_remediation.py`
- `tests/test_composition.py`
- `tests/test_database_runtime.py`
- `tests/test_migrations.py`
- `tests/test_slice_1_0_remediation.py`
- `docs/database.md`
- `docs/operations.md`
- `docs/testing.md`
- `docs/decisions.md`
- `migrations/README.md`
- `docs/slice-1-0-remediation-report.md`
