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

## Open questions

- Which Python 3.13 versions and operating systems will CI cover?
- When should PostgreSQL integration tests become mandatory?
- Which economic invariants should be property-tested or model-tested?
- What performance and load targets represent realistic Discord activity?
