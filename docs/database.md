# Database

## Persistence direction

SQLite is the initial database. Application access uses SQLAlchemy 2's async API with
`aiosqlite`; Alembic owns every schema change. PostgreSQL migration remains practical by
keeping SQL and concurrency assumptions isolated in infrastructure adapters and by exercising
portable constraints and queries.

Application services own transactions through a unit of work. Repository operations use the
caller's async session, flush when needed, and never silently commit. SQLite foreign-key
enforcement is enabled on every connection. Production startup refuses to mutate an
unexpected schema revision.

## Data ownership and aggregate boundaries

The initial database is shared, but each table has one logical owner:

| Owner | Persistent responsibility |
| --- | --- |
| Players | Global player identity and lifecycle |
| Economy | Monetary accounts, balance projections, ledger transactions/postings, claim and transfer limits |
| Inventory | Fungible holdings, unique item instances, equipment assignments, item movements |
| Progression | XP facts/projections, profession state, mastery selections, prestige history |
| Commerce | Shop purchase limits/quotes where durable, trade offers and escrow |
| Goals | Quest instances/progress, achievement awards, collection registrations, fact-consumer receipts |
| Safety/access | Restrictions, durable capabilities, approval proposals and immutable access audit |
| Operations | Transport-idempotency records, immutable action facts, administrator audit, content-version references |
| Reporting | Rebuildable leaderboard and economy read models |

Only the owning repository writes a table. Cross-owner foreign keys may enforce identity and
ownership, but cross-system use cases coordinate owners in one application transaction. Read
models may join owners for queries and must not become a backdoor for mutations.

For the first schema, the player table is limited to global identity, creation time, and minimal
lifecycle state. Account XP/level is Progression state, and restrictions/capabilities/audit are
Safety/access state; neither is stored as columns on the player row. The Phase 0 baseline creates
no progression or safety/access tables. Until Slice 1.3 supplies durable restrictions, `/join`
checks only the application-level global join/mutation eligibility boundary documented in
`architecture.md` and never creates placeholder safety state.

## Identifier and timestamp conventions

- Durable entity and transaction identifiers are application-generated UUIDv4 values. Use
  SQLAlchemy's portable UUID type with Python `UUID` values: canonical fixed text on SQLite and
  native UUID on PostgreSQL. Do not depend on database-generated or insertion-order identity.
- Discord snowflakes are non-negative signed 64-bit integers with unique constraints where
  identity requires them; never use display names as identity.
- Stable content keys are bounded lowercase text identifiers and are never recycled.
- Domain/application instants are timezone-aware UTC. Persistent instants are signed 64-bit
  Unix epoch milliseconds on both initial backends, converted only by infrastructure adapters.
  This avoids SQLite timezone ambiguity and has identical comparison semantics on PostgreSQL.
- Ledger ordering, history pagination, and job cursors use a deterministic tuple such as
  `(committed_at, identifier)`, never timestamp alone.
- Durations, cooldowns, and quantities are integer units with the unit named in the schema or
  domain type.

## Integrity requirements

Database constraints backstop, but do not replace, domain rules:

- unique player per Discord identity;
- exactly one initial wallet per joined player; no bank row exists until a bank ADR is accepted;
- account-class polarity from `economy-design.md` and non-negative custody/inventory values;
- non-zero ledger postings and immutable committed ledger rows;
- unique transport-idempotency key plus request fingerprint within an operation scope;
- feature-specific domain uniqueness or expected revisions, including `(player, claim_period)`,
  `(campaign, target)`, quote consumption, action opportunity, and state-machine versions as
  relevant;
- unique fungible holding per owner/item definition;
- one beneficial owner and custody state per item instance, non-overcommitted stack
  reservations, and one equipped instance per player/slot;
- unique action-fact UUID and unique `(consumer_key, fact_id)` consumption;
- unique one-time claims, achievement awards, and collection registrations; and
- valid foreign keys and explicit delete behavior—no accidental cascading loss of economic
  history.

Some invariants, such as postings summing to zero, span rows. The application establishes
them within one transaction and integration/reconciliation checks verify them. PostgreSQL
deferred constraints or triggers may be considered later only if they preserve the same
application contract; SQLite-specific triggers are not the baseline.

## Concurrency, retry, and idempotency

SQLite has one writer at a time. The accepted initial operating mode is one bot/worker process,
`foreign_keys=ON`, write-ahead logging, `synchronous=FULL`, and a 1,000 ms busy timeout on every
connection. Application retries allow at most two attempts after the initial attempt and a
three-second total database retry budget, always with the original transport and domain keys.
No network or Discord wait occurs in a transaction. Mutations use conditional updates or
equivalent guarded persistence that reports insufficient/stale state without a lost update.

Every externally retriable mutation has a scoped transport key, request fingerprint, and
serialized application outcome or stable result reference. A completed key returns its prior
outcome; the same key with different input is an error. Independently, each consumable domain
entitlement has a unique key or guarded revision. Both defenses are exercised in concurrency
tests with distinct transport IDs.

Concurrent `/join` calls rely on unique Discord-player and player-wallet constraints plus a
conflict-safe repository operation in one transaction. They converge on one result; code does
not “check then insert” without handling the database race. `/balance` performs no insert.

The move to PostgreSQL may replace guarded updates with `SELECT ... FOR UPDATE` or stronger
database features inside the adapter. It must not change visible money, inventory, or
idempotency semantics.

## Ledger and history retention

Committed monetary ledger entries, complete item movement audit, action facts, prestige
history, trade history, and administrator corrections are append-only and retained for the
life of the economy unless a legal/privacy policy requires a designed anonymization process.
Player deletion should pseudonymize identity where required without breaking conservation or
audit history. Operational logs and transient idempotency payloads may have shorter retention,
but keys must outlive every possible Discord/job retry and support incident analysis.

Balance projections and read models are rebuildable from authoritative history where the
design claims they are. Reconciliation checks compare postings with account balances and
economic supply by reason; they report or freeze affected mutations but never auto-edit
committed ledger rows.

## Migration policy

- Every schema change receives a reviewed Alembic revision; applied revisions are immutable.
- Test a clean upgrade and an upgrade from every supported production predecessor against a
  real temporary SQLite database.
- Prefer additive staged changes: add nullable/backfillable structure, backfill in bounded
  work, validate, then enforce.
- Data migrations are deterministic, restartable where feasible, and record assumptions.
- Back up and restore a production-like database before launch and rehearse restore plus
  migration rollback/forward remediation.
- Avoid SQLite-only types, implicit rowid behavior, database booleans/timestamps with different
  semantics, and raw SQL without a documented PostgreSQL form.
- Add PostgreSQL CI and a rehearsed copy/validation path before scale forces an emergency
  migration.

## PostgreSQL migration triggers

Phase 0 benchmarks the candidate player/ledger/idempotency transaction at twice the projected
launch peak. Before mining, repeat the benchmark with the complete representative action
(inventory, XP, cooldown, movement audit, action fact, idempotency, and economic telemetry).
The provisional acceptance envelope is p95 transaction time at or below 100 ms, p99 at or
below 250 ms, fewer than 1% attempts requiring a busy retry, no final lock failures, and no
invariant/idempotency failure. The measured sustainable write rate and projected launch peak
are recorded with the test rather than guessed in this document.

The accepted projected launch peak is 17 mutation transactions/second, derived in
`decisions.md`; Phase 0 therefore requires 34 offered transactions/second. The 2026-08-25
open-loop candidate-persistence run is recorded in `sqlite-capacity.md`. On the development host,
all three 30-second measurement runs completed 34.0 transactions/second inside the measurement
window after a 10-second warm-up. Worst-repeat p95/p99 were 17.601/18.595 ms, with no retry,
final lock, backlog, or invariant failure. Slice 0.3 passes for the accepted assumption.

Closed-loop saturation remains a diagnostic rather than the acceptance method. Four writers
were the highest tested passing level at 499.505 transactions/second; eight failed p99. Until a
deployment-host rerun replaces these planning values, use one process, at most four in-flight
writers, 249.75 transactions/second as the provisional PostgreSQL-start rate, and 349.65 as the
provisional migration-completion rate. These are warning thresholds, not capacity promises.

Begin PostgreSQL migration work when any of these occurs: projected peak reaches 50% of the
measured sustainable SQLite rate; p95 exceeds 100 ms or retry rate exceeds 1% for three peak
15-minute windows; a second bot/worker process is required; backup/availability objectives
cannot be met; or reporting affects gameplay latency. Complete migration before projected peak
reaches 70% of measured capacity or final lock failures reach 0.1%. A threshold change requires
a recorded load result and decision, not an emergency tuning edit.

Economy and leaderboard reports use indexed incremental projections with explicit query-time
budgets. Heavy reconciliation and percentile rebuilds run against a safe snapshot/backup. If
that cannot meet freshness needs, reporting pressure itself triggers PostgreSQL work.

## Backup and incident rules

Before real economic data exists, define automated backups, retention, encryption, restore
drills, and the operator responsible for them. During a suspected economic corruption event,
disable affected mutations, preserve the database and logs, reconcile, then use compensating
transactions or a reviewed forward migration. Never repair history with untracked manual SQL.
