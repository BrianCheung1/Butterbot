# Database

## Persistence direction

SQLite is the initial database. Application access uses SQLAlchemy 2's async API with
`aiosqlite`; Alembic owns every schema change. PostgreSQL migration remains practical by
keeping SQL and concurrency assumptions isolated in infrastructure adapters and by exercising
portable constraints and queries.

Application services own transactions through a unit of work. Repository operations use the
caller's async session, flush when needed, and never silently commit. SQLite foreign-key
enforcement is enabled on every connection. Production startup opens an existing database in
read/write mode without silently creating or migrating it and refuses normal service against an
unexpected schema revision. The complete runtime, backup, and recovery contract is in
`operations.md`.

The first production head is Alembic revision `20260825_0001`. It contains exactly:

- `players` for global Discord identity, creation time, and minimal lifecycle state;
- `economy_accounts` and `economy_account_balances` for the initial wallet/system account
  taxonomy and guarded projections;
- `economy_ledger_transactions` and `economy_ledger_postings` for immutable committed monetary
  history; and
- `operations_transport_requests` for application-wide transport replay outcomes; and
- `operations_integrity_violations`, a bounded startup sentinel maintained transactionally by
  SQLite triggers for missing account projections and player wallets.

It contains no seeded economic value and no progression, inventory, banking, gameplay,
safety/access, business-entitlement, or command-specific idempotency structure.

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
Safety/access state; neither is stored as columns on the player row. The first production
baseline creates no progression or safety/access tables. Until Slice 1.3 supplies durable
restrictions, `/join` checks only the application-level global join/mutation eligibility
boundary documented in
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

SQLite's dynamic typing does not weaken these contracts. Every Slice 1.0 UUID column has a
SQLite-only canonical 32-character lowercase hexadecimal storage check. Every identifier,
timestamp, version, monetary amount, and posting represented as an integer has a SQLite-only
`typeof(column) = 'integer'` backstop, including nullable variants. Application boundaries reject
booleans, non-integers, and values outside signed 64-bit range before SQL; checked arithmetic
rejects overflow or underflow for the whole mutation. PostgreSQL continues to use native UUID and
integer types without SQLite expressions in its DDL.

## Integrity requirements

Database constraints backstop, but do not replace, domain rules:

- unique player per Discord identity;
- exactly one initial wallet per joined player; no bank row exists until a bank ADR is accepted;
- account-class polarity from `economy-design.md` and non-negative custody/inventory values;
- non-zero ledger postings and immutable committed ledger rows;
- Operations-owned unique transport-idempotency key plus request fingerprint within a stable
  application-operation namespace;
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
them within one transaction and integration/reconciliation checks verify them. The SQLite
baseline uses narrowly isolated triggers only to maintain the indexed aggregate-completeness
sentinel, so startup does not scan all players/accounts. Application repositories independently
enforce the same rule. A wallet insert is authorized only by explicit proof that its player was
inserted by the same unit of work; an already committed player without a wallet is corruption and
cannot be repaired by join retry. The sentinel's active rows are database-protected from direct
delete/update, while the maintenance triggers can remove a row only after the underlying aggregate
has genuinely become complete. Startup verifies fingerprinted definitions for the sentinel and
the three aggregate tables its predicates depend on, the required sentinel index, and the exact
maintenance/protection trigger names and normalized definitions; an
unchanged Alembic head is not sufficient. PostgreSQL's equivalent is selected at its adoption gate;
SQLite-specific triggers are not used for ledger balancing or business rules.

## Transport-idempotency persistence ownership

Operations/application support owns the shared transport-request persistence and its repository
port. The application-layer coordinator calls that port inside the mutating use case's unit of
work; the SQLAlchemy infrastructure adapter implements it. Economy and other domains can use the
facility but cannot write its table through their domain repositories.

The first baseline may persist only generic request execution data: stable operation namespace,
opaque transport-key representation, request fingerprint, stable applied or typed-rejection
outcome/reference, completion time, and `retain_until`. Logical uniqueness is
`(namespace, transport_key)`. There is no generic business-entitlement table and no committed
pending transport state: an unexpected failure rolls the request claim back with the use case.

Initial Discord mutation outcomes remain for seven days. Each later namespace registers a period
covering its maximum legitimate redelivery window plus investigation margin. Operations owns
incremental expiry and storage-growth metrics. Expiry never removes ledger/audit history or a
domain-owned one-use constraint/revision, so an old transport key cannot make a consumed business
entitlement available again.

Slice 1.0 stores the opaque transport key directly in its bounded Operations column; logs never
emit it. A claim row is inserted without an outcome only inside the owning uncommitted unit of
work. The repository completes it with canonical outcome JSON and retention instants, and the
unit of work refuses commit while any claim it created remains unfinished. The committed ledger
may store the request UUID for durable correlation without a foreign key, so expiry can remove
the transport outcome without removing or blocking permanent ledger history.

SQLite `CHECK` constraints backstop application validation for non-empty bounded fields,
embedded NUL rejection, lowercase dotted namespace shape, stable actor-kind and outcome-code
shape, an exact lowercase hexadecimal 64-character SHA-256 fingerprint, canonical UUID storage,
exact-integer completion/retention storage, and a valid JSON object outcome payload. Startup
rejects committed outcome-less claims and incomplete account/player aggregates,
while an uncommitted claim remains invisible to other connections. Replay converts any
post-startup externally corrupted payload into a persistence-contract error rather than exposing
a JSON parser exception. Application writes reject values that would change type during JSON
round-trip or cannot be encoded as finite canonical JSON; the offline verifier and replay reject
duplicate object keys, non-finite decoded numbers, and non-canonical stored representations.
Successful applied/rejection and cleanup events are registered with the
unit of work and emitted only after its commit succeeds; rollback emits no committed-success
event. Every operational telemetry invocation is isolated behind a non-throwing boundary; sink
failure is logged where possible but cannot alter replay, conflict, typed rejection, retry,
commit/rollback, or cleanup outcomes.

Permanent opaque identity/audit references (`actor_reference`, `domain_reference`,
`content_version`, including transport actor references) use one application-and-SQLite contract:
one to the field maximum visible ASCII characters (`!` through `~`). Empty values, all whitespace,
any leading/trailing or embedded whitespace, controls, NUL, and non-ASCII spellings are rejected;
values are never trimmed or otherwise canonicalized before persistence. Stable-name and
namespaced-name fields additionally retain their lowercase dotted grammar.

## Concurrency, retry, and idempotency

SQLite has one writer at a time. The accepted initial operating mode is one bot/worker process,
`foreign_keys=ON`, write-ahead logging, `synchronous=FULL`, and a 1,000 ms busy timeout on every
connection. Application retries allow at most two attempts after the initial attempt and a
three-second total database retry budget, always with the original transport and domain keys.
Admission to the maximum-four-writer semaphore consumes the remaining attempt budget. Admission
timeout follows the same documented retry-exhaustion contract, and the SQLite busy timeout is set
only after admission from the actual remaining budget.
No network or Discord wait occurs in a transaction. Mutations use conditional updates or
equivalent guarded persistence that reports insufficient/stale state without a lost update.

Every externally retriable mutation has a scoped transport key, request fingerprint, and
serialized application outcome or stable result reference. A completed key returns its prior
outcome; the same key with different input is an error. Independently, each consumable domain
entitlement has a unique key or guarded revision. Both defenses are exercised in concurrency
tests with distinct transport IDs.

Concurrent `/join` calls rely on unique Discord-player and player-wallet constraints plus a
conflict-safe repository operation in one transaction. They converge on one result. SQLite
repositories read existing identity under the owning
unit of work's `BEGIN IMMEDIATE` writer transaction before inserting; writer serialization
closes the lookup/insert race. Conflicting aggregate inserts abort at the database boundary. The player repository's explicit
`created` result is carried into wallet creation and cross-checked against unit-of-work creation
state. A retry that observes an existing player may return its existing complete wallet but may
not create a missing one. `/balance` performs no insert.

The move to PostgreSQL may replace guarded updates with `SELECT ... FOR UPDATE` or stronger
database features inside the adapter. It must not change visible money, inventory, or
idempotency semantics.

## Production SQLite startup safety

The first persistence/composition slice must enforce the `operations.md` contract before any
mutating application service can be composed:

- one bot process holds the deployment's exclusive process lock; backup readers are not
  mutation writers;
- the absolute database path resolves to a regular existing file on the approved persistent
  local data volume, and production connection setup must not create an empty file;
- `foreign_keys=ON`, `synchronous=FULL`, and `busy_timeout=1000` are applied and verified per
  connection, while persistent `journal_mode=WAL` is verified;
- the database has exactly the Alembic head expected by the running release, bounded transport
  checks pass, the exact sentinel table/index/trigger schema contract is intact, and every
  persisted account/player aggregate is complete; and
- the deployment-owned mutation switch is explicitly enabled and every production-enable
  prerequisite is satisfied.

A missing database/Alembic table, a behind revision, or an ahead/unknown/multiple head is not an
automatic migration opportunity: startup logs a schema-readiness failure and exits non-zero.
Deployment runs reviewed migrations separately with mutations disabled. Integrity, PRAGMA,
filesystem, or process-lock failure also exits and invokes the incident procedure. This
fail-closed behavior prevents economic mutation against a silently created, stale, or unsafe
database.

The implemented runtime canonicalizes the configured path and approved root, rejects symlink
traversal, files outside/directories below that root, and database files with hard-link aliases.
On the accepted Linux deployment, a fixed kernel-owned abstract Unix socket represents the single
Butterbot process independently of mutable filesystem names and survives lock-path or data-root
unlink/recreation attacks. The pathname lock remains only a non-production development fallback.
Production mutation enablement also requires a recorded Linux mount `major:minor` identity, the
reviewed administrator UID and Butterbot service-group GID, and an effective ext4/XFS filesystem.
The approved root must have that owner/group and exact mode `1770`; the database must have that
owner/group and exact mode `0660`; the service must own neither, must lack effective capabilities,
and must not be able to replace the root through its parent. After taking ownership the runtime revalidates database and root
device/inode identity, opens SQLite with URI `mode=rw`, and revalidates both the configured file
identity at every writer admission and `PRAGMA database_list` identity at every connection
checkout and again at the final transaction boundary immediately before commit. The unavoidable
last-check-to-commit filesystem window is closed by the production ownership/permission contract
in `operations.md`, not by claiming pathname checks eliminate filesystem TOCTOU. A post-commit
confirmation detects a breached assumption or makes inability to establish that required
condition fail closed, disables further mutation, and preserves the already durable commit outcome
for recovery. Later callback or resource-cleanup failure is operationally separate and cannot turn
that committed business result into a failure. It then checks WAL, the exact single Alembic head,
absence of committed incomplete transport claims, and aggregate completeness. Exhaustive
`quick_check`, `foreign_key_check`, permanent identity/integer shape, and canonical retained-outcome
verification run through the stopped-service streaming verifier rather than adding history-sized
work to startup. Missing/corrupt state, path/volume identity
failure, unsafe storage/PRAGMA, or unavailable ownership aborts composition before Discord
construction. Normal startup never calls Alembic.

A 60-second runtime sampler emits bounded `database.storage` events for main/WAL/SHM sizes,
free space, passive checkpoint results, and daily growth. A failed identity, filesystem,
checkpoint, or free-space check makes the instance-scoped storage state unsafe so central
mutation eligibility fails closed until a later healthy sample or restart. Actual safety state is
tracked separately from the last successfully emitted mutation-state event. Sampling and
telemetry exceptions do not replace the primary storage/identity failure or terminate the
periodic monitor. State changes append ordered pending transition events; failures retain the
queue, recovery cannot overwrite an earlier unsafe event, and deduplication resumes after the
queue drains successfully.

## Ledger and history retention

Committed monetary ledger entries, complete item movement audit, action facts, prestige
history, trade history, and administrator corrections are append-only and retained for the
life of the economy unless a legal/privacy policy requires a designed anonymization process.
Player deletion should pseudonymize identity where required without breaking conservation or
audit history. Operational logs may have shorter retention. Transport outcomes follow the
Operations-owned namespace policy above; domain one-use state outlives every period in which its
entitlement must remain consumed.

Balance projections and read models are rebuildable from authoritative history where the
design claims they are. Reconciliation checks compare postings with account balances and
economic supply by reason; they report or freeze affected mutations but never auto-edit
committed ledger rows.

## Migration policy

- The first production economy revision is authorized only after the Final Phase 0 Gate Review;
  Slice 0.4 creates no migration.
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
were the highest tested passing level at 499.925 transactions/second; eight failed p99. Until a
deployment-host rerun replaces these planning values, use one process, at most four in-flight
writers, 249.96 transactions/second as the provisional PostgreSQL-start rate, and 349.95 as the
provisional migration-completion rate. These are warning thresholds, not capacity promises.

Before the first public durable mutation, the identical accepted run must pass on the selected
production VM and the exact local database volume under normal production host agents. Every
open-loop repeat and correctness diagnostic must meet the existing gate; the development result
cannot be substituted for it, and saturation cannot weaken it. Host/storage/runtime changes and
a replacement projected peak require the reruns listed in `operations.md`.

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

The accepted initial policy is a verified SQLite online backup every 15 minutes to encrypted,
retention-protected off-host storage, with 48 hours of 15-minute points, 35 daily points, and 12
monthly points. Each backup is independently opened and integrity/foreign-key/schema/checksum
verified; weekly automated restores and a full pre-public restore drill test the path. The
targets are a 15-minute RPO and two-hour RTO to verified service with mutations disabled.

During suspected corruption, the deployment operator disables all mutations or stops the bot,
preserves the original database plus WAL/SHM and logs, and investigates only copies. Recovery
restores to a new path and verifies integrity, foreign keys, exact schema, and application
reconciliation before disabled startup. History is repaired only with a reviewed forward
migration or compensating transaction, never untracked manual SQL. Ownership, procedure,
retention, verification, and production-enable criteria are normative in `operations.md`.


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

## Replacement protection at revision 20260914_0003

The head rejects conflicting INSERTs into the three aggregate tables before SQLite can
perform REPLACE conflict deletion. All PK/identity uniqueness conflicts abort, including
conflicting UPSERT and INSERT OR IGNORE. Legal balance/version/lifecycle changes use UPDATE;
no-op identity UPDATEs remain allowed. This does not depend on recursive_triggers. Repository
create-if-absent operations look up existing rows while the owning BEGIN IMMEDIATE transaction
holds writer ownership. Do not call these SQLite adapters outside that transaction boundary.

The upgrade records hidden missing wallets/projections left by older replacement paths.
It never creates missing financial state. Such databases upgrade but fail readiness and need
an independently reviewed recovery. Both previous revisions remain historically unchanged.

## Slice 1.3 schema

Current head `20260922_0004` adds `safety_bootstrap`, `safety_capabilities`,
`safety_restrictions`, `safety_proposals`, `safety_proposal_targets`, and
`safety_access_audit`. The frozen release manifest includes every new table/index/trigger.
UUID/integer checks, proposal state/approval checks, immutable audit/receipt guards and
replacement rejection are migration-owned. Existing economy/player/transport data is preserved.
No grant ledger entries or new wallets are created by this migration. Apply migrations with the
service stopped; old disposable sessions remain historical and are not upgraded by the launcher.


### 2026-09-24: Proposal scope sealing (20260924_0005)

New proposals insert pending facts, all targets and an immutable verified scope seal in one
transaction. Sealed membership rejects target append, including SQLite conflict variants with
recursive triggers disabled. Status transitions require a verified seal and exact target count.
Seal update/delete/replacement is forbidden; a seal failure rolls back the whole submission.

Existing proposal facts, targets, statuses and audits remain unchanged. Their observed scope is
sealed as unverified because prior approved intent cannot safely be reconstructed. Submit a new
proposal for further approval; private previews expose verification status. Historical receipt
replay can return historical approved/applied status without new effects. Future grant execution
must verify current scope inside its transaction and never trust a cached result.

Prior migrations are unchanged. Restart disposable development to allocate new storage; this
source change does not migrate running sessions. Grants remain unimplemented. Native Linux is
still deferred and formal release acceptance remains FAIL.
