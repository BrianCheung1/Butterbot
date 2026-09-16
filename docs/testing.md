# Testing

## Strategy

- Unit-test pure business rules without Discord or a database.
- Integration-test application services against temporary real SQLite databases.
- Test Discord adapters with narrow fakes at the presentation boundary.
- Exercise complete migrations, constraints, rollback behavior, and transaction atomicity.
- Control clocks and random sources in tests once time or randomness enters the domain.
- Add regression tests before fixing economic exploits or data-loss bugs.

Tests should assert observable outcomes and invariants rather than mirror implementation
details. Concurrency-sensitive use cases need tests for retries, duplicate requests, and
competing updates. PostgreSQL compatibility tests can be added when its driver and CI service
are intentionally adopted.

## Quality gates

The baseline local checks are Ruff linting and formatting, strict Pyright analysis, and
pytest. Coverage is diagnostic; no percentage threshold is chosen yet.

The 2026-09-16 user-authorized exception allows provisional local Slice 1.1 work while the
Slice 1.0 native gate is deferred. It does not waive release acceptance: the final candidate
still requires all native cases and independent review before production use. Join tests use
disposable databases and an injected eligibility policy; normal mutation enablement protections
remain in force. Historical candidate manifests must not be presented as proof of newer source.

Slice 1.1 tests cover real-database creation/retrieval, same-key replay, distinct-interaction
convergence, actor conflicts, stable eligibility denials, rollback after player/outcome writes,
retry after a transient database failure, cancellation, transport expiry, unchanged existing
balances, missing-wallet corruption, and inactive identities. Discord adapter tests verify
private deferral before application work, private success/error responses, no privileged intents,
and recovery after a real commit followed by a lost response. No live Discord or Linux run is
implied by these local tests. Current results are in `slice-1-1-local-report.md`.

## Economic and progression validation

Examples and unit tests are insufficient for a long-lived economy. As relevant systems are
introduced, add:

- invariant/property tests for conservation, non-negative balances/quantities, integer bounds,
  and reward-table selection;
- state-machine tests for trade, claim, crafting, equipment, and prestige workflows;
- concurrent integration tests for duplicate creation, competing spend/removal, transport
  replay, and distinct transport IDs targeting the same business entitlement against a real
  SQLite database;
- catalog checks for missing references, invalid modifier combinations, and deterministic
  shop/crafting arbitrage cycles;
- deterministic simulations for source/sink flow, time-to-milestone, multiplier caps, rare-drop
  variance, casual/regular/optimized cohorts, and returning-player catch-up; and
- reconciliation tests that rebuild or compare monetary balances, inventory provenance, and
  read models from their authoritative history where promised.
- action-fact consumer tests for crash/replay, unique `(consumer_key, fact_id)` handling,
  deterministic cursors, backfill, and separate reward-claim uniqueness.

Simulation results are design evidence, not production guarantees. Shipped features also need
cohort and economic telemetry so assumptions can be compared with observed behavior.

## Migration and portability validation

Every revision upgrades a fresh database and each supported prior schema using real temporary
SQLite files with foreign keys enabled. Data-bearing migrations include representative edge
values and restart/remediation tests. Before PostgreSQL adoption, run the same application
contract suite against both backends; backend-specific locking implementations may differ,
but visible results and invariants may not.

SQLite capacity tests record hardware, journal/synchronous/busy-timeout settings, projected
peak, measured sustainable rate, transaction p95/p99, retry percentage, final lock failures,
and invariant failures. Run the disposable player/ledger experiment before the first migration
and the full representative action transaction before public mining, using the acceptance and
PostgreSQL thresholds in `database.md`.

The Phase 0 acceptance run is an open-loop offered-rate test at twice projected peak, not a
closed-loop saturation comparison. It uses a warm-up, a sustained measurement window, and
multiple fresh-database repeats; queue delay and measurement-window backlog remain visible.
Ordinary tests cover its scheduler/capacity calculation, WAL/busy/retry behavior, guarded debit,
transport and business idempotency semantics, and a source fingerprint that detects stale checked
evidence without running the full load test in pytest.

The accepted development-host evidence does not authorize public mutations on another host.
Before the first public durable mutation, rerun the unchanged accepted 17/34 TPS benchmark on
the selected production VM and actual local database volume, with production runtime versions
and ordinary host agents. All three open-loop repeats, the 99% completion, p95/p99, retry, final
lock, invariant/idempotency, and correctness-diagnostic gates must pass. Preserve the raw reviewed
host evidence and repeat it after the material host/storage/runtime changes listed in
`operations.md`; never tune the offered rate down to pass.

## Operational validation

The first persistence and deployment work adds automated tests for fail-closed configuration,
an existing-file database path, every required connection PRAGMA, exact Alembic readiness,
missing/behind/ahead/incompatible schema outcomes, exclusive process ownership, disabled mutation
composition, bounded graceful shutdown, and structured event fields. Tests must prove a missing
database cannot be silently created and that disabled global eligibility creates no placeholder
restriction rows.

Before production data/public mutations, record an end-to-end backup/restore drill. It must use
SQLite's online backup API, verify checksum, integrity, foreign keys, schema and application
reconciliation, restore to a new path, start with mutations disabled, pass safe-read smoke tests,
and demonstrate the accepted 15-minute RPO/two-hour RTO. Alert tests cover schema failure,
invariant failure, backup failure/age, storage minimum, final lock failure, and mutation-state
changes.

Slice 1.0 now covers the in-application contracts with real temporary SQLite files: clean
baseline upgrade, downgrade/re-upgrade, and field constraints; required PRAGMAs on multiple
runtime connections;
application-boundary commit and rollback; repository non-commit behavior; concurrent
player/wallet creation convergence; missing, corrupt, behind, ahead, unknown, incompatible,
multiple-head, non-WAL, committed-incomplete-claim, approved-root/volume, alias/hard-link, and
process-lock startup failures; active, waiting, captured-post-transaction, commit-racing,
timed-out/fail-stop, and caller-cancelled shutdown behavior with replacement-lock exclusion;
Linux subprocess attacks that unlink/recreate the nominal lock path or replace the data root;
writer-admission and connection-checkout database-identity validation; adversarial transport
shape/NUL constraints; canonical finite outcome JSON with stable round-trip types plus offline verification and
replay rejection of duplicate keys, non-finite values, and non-canonical representations; canonical
UUID and exact SQLite integer storage constraints plus signed-64-bit application/arithmetic
boundaries; final transaction identity validation and fail-closed post-commit confirmation;
cancellation immediately before, during, and after durable commit and during post-commit callbacks;
committed-result preservation across session, connection, and combined cleanup failure; retained
unresolved-resource shutdown retries; successor exclusion until every prior connection is
unusable; committed and rolled-back cleanup failure; repeated retry failure; and caller
cancellation during unresolved cleanup; transport success/rejection replay,
concurrent actor/semantic fingerprint conflicts, unexpected-failure rollback, atomic owning-state
rollback, no committed pending claim, seven-day retention cleanup, and commit-accurate success/
cleanup telemetry plus sink-failure isolation for replay, typed-rejection replay, conflict, busy
retry/exhaustion, cleanup, and post-commit reporting; concurrent bounded transaction/monitor
shutdown with stuck, failed, waiting,
active, caller-cancelled, retried-owner-capture, and non-orphaned monitor-cleanup cases; final-lock
and resilient critical storage signals with ordered pending mutation-safety transitions across
immediate recovery and repeated sink failure; maximum-four-writer admission charged to the
attempt budget, near-deadline admission, post-deadline rejection, waiting cancellation, and busy
retry after admission delay; ambient-versus-programmatic
Alembic target precedence; strict disabled-by-default mutation configuration; and composition failure before
Discord construction. The symlink integration test skips only when the host denies symlink
creation; canonical spelling and hard-link alias tests still run.

Linux production storage tests require the native Linux gate host. They cover the reviewed
administrator UID and Butterbot service-group GID, exact root/database modes `1770`/`0660`,
world or unrelated-user access, incorrect owner/group, service-owned paths, parent replacement,
effective capabilities, and the accepted positive case. Windows runs must report these tests as
skipped and must not claim the Linux ownership/capability guarantees were verified.

The authoritative kernel-backed selection is marked `native_linux_kernel` and is run through:

```bash
sudo .venv/bin/python benchmarks/native_linux_gate.py \
  --parent /var/lib/butterbot-native-gate \
  --report /tmp/butterbot-native-linux-report.json
```

The parent must be administrator-owned, non-writable by the numeric service identity, have at
least the production free-space floor, and resolve through real `/proc/self/mountinfo` to ext4 or
XFS. The runner requires Python 3.13 and provisions a root-owned/service-group `1770` data root and
`0660` database, then executes service probes through `setpriv` with a distinct UID/GID. It records
Python, kernel, mount identity/filesystem, UID/GID/group and mode setup, effective capabilities,
and network-namespace identities. Its JSON reports total collected, run, passed, failed, and
skipped tests plus the reason for every skip. The selection excludes the monkeypatched Linux unit
tests; those remain useful branch coverage but are not counted as kernel proof. A namespace test
may skip only when the host kernel denies `unshare --net`; that skip records the production
assumption that `PrivateNetwork=false` and the service shares the deployment-init network
namespace.

The native Linux gate also runs subprocess SIGTERM coverage while transactions are active,
waiting for writer admission, and already committing. Each probe must exit normally only after
transaction drain/cleanup, engine disposal, and replacement acquisition of the released process
lock. Windows collects these tests as skips and cannot establish the production signal guarantee.

## Open questions

- Which Python 3.13 versions and operating systems will CI cover?
- When should PostgreSQL integration tests become mandatory?
- Which economic invariants should be property-tested or model-tested?
- When should measured launch/session telemetry replace the accepted 17 TPS planning input?


## September 2026 gate remediation

Release head is `20260914_0003`; `20260825_0001` remains the frozen historical
baseline. Upgrade explicitly with mutations stopped. The new revision prevents changes
to player UUID/Discord identity, account UUID/owner/kind/currency/system identity, and
projection account UUID/kind. No-op identity assignments remain legal.

Readiness and the stopped-service verifier compare all application tables, explicit
indexes, and triggers against a release-bound, case-sensitive schema manifest, including
ledger/transport constraints and retention indexes. Work is bounded by schema object
count. Implicit uniqueness indexes are covered by owning table SQL. Unexpected application
schema objects also fail closed.

Native Linux evidence must come from the exact reviewed candidate on the provisioned
Linux host. Capability coverage must be collected and pass using real nonzero effective
capabilities. Failure, skip, or absence fails the runner. Only the exact network-namespace
test may skip for documented host denial of namespace creation; missing unshare is not
an allowed skip. Existing UID/GID/mode, mounts, abstract socket, sticky replacement,
links, namespaces, and active/waiting/committing/fail-stop SIGTERM tests remain required.

## Current native acceptance runner

Run the command above on provisioned native Linux after local verification. Windows and WSL
are rejected. The report now retains a sibling, uniquely named artifacts directory containing
raw JUnit, pytest stdout/stderr and layout evidence. Keep that directory with the JSON report.
The report includes all 16 selected node IDs, per-case outcomes, missing/unexpected cases,
source file hashes before/after execution, git HEAD and working-tree status, and dependency
versions. A dirty tree must be identified by its source manifest; HEAD alone is insufficient.

Every required case must be collected exactly once and pass. Only the namespace test may
skip with the exact approved denial reason. The test fixes LC_ALL=C and distinguishes a
util-linux EPERM/EACCES error before child startup from utility or child failures. Missing
unshare, setpriv/capability failures, and other skips fail. Inherited PYTEST_ADDOPTS and
PYTEST_PLUGINS are removed; automatic third-party plugin loading is disabled and pytest-asyncio
is explicitly loaded. The configured 600-second runner bound produces failure, not acceptance.

The Windows policy unit tests deliberately simulate reports; their generated fixtures are
not native Linux evidence. The independent review artifacts describe the earlier candidate
and must not be reused as evidence for the new head.
