# Slice 1.0 blocker fixes — revision 20260914_0003

The four code blockers from `docs/reviews/slice-1-0-independent/report.md` are addressed.
This is an implementation/verification report, not an independent release acceptance.
Native Linux evidence remains outstanding. Slice 1.0 is not declared PASS and Slice 1.1
remains blocked.

## Changes

- B1: New migration `20260914_0003_aggregate_replacement.py` rejects uniqueness collisions
  on player identity, account identity/ownership/system keys, and projection account identity
  before INSERT can invoke SQLite REPLACE deletion. It works with recursive_triggers both OFF
  and ON. Conflicting UPSERT/INSERT OR IGNORE also abort; legal no-op UPDATEs remain allowed.
  Repositories now find existing players/wallets under the existing BEGIN IMMEDIATE transaction
  before inserting, preserving create-if-absent and concurrent convergence. Transport replay
  insertion behavior is unchanged. Upgrade reconstructs missing completeness sentinels from
  older holes without creating accounts, ownership or balance state. Both prior migration files
  are byte-identical to the reviewed candidate.
- B2: Readiness uses a literal reserved prefix (`name NOT GLOB 'sqlite_*'`) instead of LIKE's
  wildcard underscore. Legal near-prefix extra tables, indexes, views and triggers are rejected
  by both startup and the stopped-service verifier. The release manifest adds only the three
  new trigger hashes; all previous object hashes remain unchanged.
- B3: The native runner has a release-bound 16-case inventory, with full module identity and
  individual parameterized SIGTERM phases. Missing, duplicate, unexpected, failed, errored or
  improperly skipped cases fail. JUnit shape/counts are validated; malformed reports produce a
  failure result. Inherited pytest options/plugins cannot narrow selection, and pytest-asyncio
  is explicitly loaded. Reports preserve raw JUnit/stdout/stderr/layout files and record source
  hashes before/after execution, working-tree state, selected cases and dependency versions.
  A source change during the run fails acceptance.
- B4: The namespace child announces startup before importing application code. Only the exact
  C-locale util-linux EPERM/EACCES denial with no child output can produce the approved exact
  skip reason. Missing unshare fails; import errors, unexpected child exits and other utility
  errors fail. The runner accepts this reason only for the fully qualified namespace testcase.
- B5: Still outstanding. Windows/WSL cannot pass preflight. No native Linux host/evidence was
  provided during this task, so no native acceptance run was attempted or fabricated.

## Verification observed

All commands used the repository `.venv/Scripts` executables on Windows.

| Check | Result |
| --- | --- |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 89 files |
| `pyright` | 0 errors, 0 warnings |
| `pytest -q -ra -o faulthandler_timeout=60` | 554 passed, 32 skipped, 1 warning; 45.24s |
| Fresh `alembic upgrade head` | Passed through 0001, 0002, 0003 |
| `alembic check` | Passed; no new upgrade operations detected |
| `git diff --check` | Passed; existing LF/CRLF notices |
| Historical migration SHA-256 comparison | 0001 and 0002 unchanged from independent-review manifest |
| Actual pytest native selection on Windows | 16 skipped; no missing/unexpected cases or JUnit parse errors; gate accounting correctly failed |

The skips are platform-specific Linux cases plus the Windows-denied file-symlink fixture.
The warning is the existing `.pytest_cache` access denial. No intermittent failure/stall
reproduced in this full run.

New regressions cover all aggregate collision keys with both recursive-trigger settings,
UPSERT/REPLACE variants, statement abort/multirow behavior, savepoints and transaction rollback,
the exact reported deletion/replacement attack, old-corruption migration and injected upgrade
failure/retry, data-bearing downgrade/re-upgrade, stale same-head schemas, and near-prefix
objects. Native policy coverage includes the full 80-case pass/fail/error/skip/missing matrix,
partial/malformed/duplicate reports, namespace denial classification, evidence retention,
source changes, inherited selection and actual marker-inventory consistency. Existing full-suite
concurrency, idempotency and frozen-baseline tests also pass.

The review artifacts in `docs/reviews/slice-1-0-independent` remain the historical review of the
previous candidate; their deliberately simulated native-policy results are not acceptance evidence.

## Remaining release requirement

On the provisioned root-controlled native Linux host, with the approved ext4/XFS parent and
service/admin identities, run:

```bash
sudo .venv/bin/python benchmarks/native_linux_gate.py \
  --parent /var/lib/butterbot-native-gate \
  --report /tmp/butterbot-native-linux-report.json
```

Preserve the JSON report and its sibling artifacts directory. Review source identity, complete
mandatory test results, host/layout/capabilities, and any precisely justified namespace skip.
Then perform the independent acceptance review of that exact repaired candidate. This local
implementation task does not authorize Slice 1.1.
