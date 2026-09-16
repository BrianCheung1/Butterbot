# Slice 1.1 provisional local implementation

Implemented 2026-09-16 under the user's explicit authorization to defer Linux and continue
locally. Local verification passed; release acceptance is still pending. This is an
implementation report, not an independent review or a Linux PASS.

## Behavior

- `/join` creates or retrieves one global player and complete zero-balance wallet. It issues
  no currency and preserves existing balances. Non-active identities are not reactivated,
  and missing existing wallet state is corruption rather than an invitation to recreate it.
- One application-owned transaction covers the player, wallet/projection, transport claim,
  and fixed outcome. `players.join` uses the Discord interaction ID and actor fingerprint;
  completed outcomes are retained for seven days. Different interaction IDs still converge.
- New requests check injected global eligibility inside the transaction. Denials record only
  transport bookkeeping; replay returns its original outcome without reexecuting the join.
  Normal bot composition retains disabled-by-default mutations and production storage checks.
- Every Discord response is private. Deferral precedes the transaction; delivery follows commit.
  Cancellation before commit rolls back; a lost response after commit permits safe replay/retry.
  No privileged intents, role-based authority, restriction tables, or new schema were added.
- Outcome payloads are exactly `{}` with fixed codes. There are no user-derived persisted
  outcome payloads. Invalid stored join outcome shapes/codes fail closed.

Allowed creation is tested using disposable local databases and an injected eligibility policy.
Starting the normal bot locally with mutations disabled makes `/join` unavailable; this work
does not add a Windows production-enable bypass or connect to Discord.

## Verification observed

Repository Windows `.venv/Scripts` executables, current working-tree source:

| Check | Result |
| --- | --- |
| `ruff check .` | Passed |
| `ruff format --check .` | Passed; 97 files |
| `pyright` | 0 errors, 0 warnings, 0 informations |
| Full `pytest -vv -ra -p no:cacheprovider -o faulthandler_timeout=60` | 588 passed, 32 skipped; 47.72 seconds; no warnings |
| `git diff --check` | Passed |
| Historical migration comparison | No migration bytes changed |

The initial focused run passed 37 tests before three further recovery tests were added.
Initial lint formatting/import issues and two misplaced Pyright suppressions in callback tests
were corrected before the final checks. No runtime test failed or stalled. The 32 skips remain
Linux-only tests and the Windows-denied symlink fixture, not native evidence.

Full stdout/stderr is retained in `.gate-local/slice-1-1-check-0.log` through `check-4.log`,
with `slice-1-1-results.json` and `slice-1-1-full.xml`. The focused run is retained separately.
`.gate-local/slice-1-1-source.json` records the current source hashes and dirty Git state.
The tested source-map SHA-256 is
`9c96e764f4b30aae7ebc2f43fa0c30076426dd2fb8f3cc1b6ff3010c16b55388`.
At verification, HEAD was the historical Slice 1.0 candidate
`075252ea9a1419cc431f3466902953309ec34b91`; the implementation was uncommitted and was
not identified by that HEAD alone. The subsequent commit containing this report records the
provisional Slice 1.1 checkpoint. The previous candidate bundle/archive/manifest remain unchanged.

## Remaining gates

Slice 1.0 release verdict remains FAIL because native Linux evidence is absent. The roadmap
exception permits this provisional local Slice 1.1 work only. Before release acceptance or
production use, validate the complete then-final candidate on native Linux and obtain independent
review of the foundation and join behavior. Fix any resulting defects, including dependent work.
Production capacity, backup/restore, and other public-enable prerequisites remain separate.
No later slice is started or accepted by this report.
