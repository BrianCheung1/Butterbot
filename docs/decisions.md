# Decisions

Use this file as the lightweight decision log until its volume justifies individual ADR files.
Accepted choices may be changed only by a later recorded decision with an explicit migration
and compatibility consequence.

## Accepted foundations

### 2026-08-25 — Technical baseline

- Python 3.13 and asynchronous `discord.py`
- SQLite initially, with PostgreSQL migration kept viable
- Async SQLAlchemy for persistence and Alembic for migrations
- pytest, Ruff, and strict Pyright as quality tools
- Business rules independent of Discord presentation
- Application services own one explicit transaction per complete use case; repositories never
  commit
- Time and randomness are injected at business-logic boundaries

### 2026-08-25 — Global player and economy scope

**Context:** The first schema cannot safely defer whether a wallet belongs to a Discord user or
a user-in-guild.

**Decision:** One global player exists per Discord user. Guilds are interaction venues and may
scope presentation, events, or leaderboard views, but do not own currency, items, or
progression. Leaving a guild does not fork or delete progress.

**Consequence:** The player table has a global unique Discord snowflake. A future guild economy
would be a new explicit product mode, not a reinterpretation of existing wallets.

### 2026-08-25 — Identifier and time representation

**Decision:** Application-generated UUIDv4 values identify durable entities and transactions;
SQLAlchemy maps Python UUIDs to canonical fixed text on SQLite and native UUID on PostgreSQL.
Discord snowflakes use non-negative signed 64-bit integers. Persistent instants use signed
64-bit Unix epoch milliseconds; domain/application time remains aware UTC.

**Consequence:** Identity never depends on insertion order, username, or guild membership, and
time comparisons have identical semantics on SQLite and PostgreSQL. History ordering uses
`(instant_ms, uuid)`.

### 2026-08-25 — Initial currency, accounts, and accounting

**Context:** Pre-creating a bank without a game purpose doubles policy and bypass surfaces.

**Decision:** Begin with one currency whose stable domain key and initial display name are
`coin`/“coins,” one stored unit per displayed coin, and one wallet per joined player. Do not
create bank accounts in the initial schema. Use committed immutable double-entry transactions,
named issuance/retirement counter-accounts, and transactionally maintained account-balance
projections. Posting polarity, account constraints, player wealth, total/circulating/escrowed/
restricted supply, minting, and destruction use the formulas in `economy-design.md`.

**Consequence:** `/balance` has one unambiguous player value initially. A bank remains planned
but requires its own purpose and wealth/limit semantics before an additive schema slice.

### 2026-08-25 — Explicit join and private balance query

**Decision:** `/join` is the sole initial player/wallet-creation mutation. Competing joins
converge through transport idempotency plus unique Discord/player-wallet constraints.
`/balance` is a pure, self-only query and responds ephemerally by default; it never creates
state. Support inspection requires a durable capability and access audit.

**Consequence:** Reads have no surprising side effects, and wealth is not exposed publicly by
default.

### 2026-08-25 — Two layers of duplicate protection

**Decision:** Every mutation uses both a transport idempotency key/request fingerprint and a
domain one-use key or guarded expected revision. Discord interaction identity never replaces
business uniqueness. Examples include claim period, campaign target, consumed quote, action
opportunity, trade version, and prestige epoch.

**Consequence:** Tests must attempt the same business action with different transport IDs.
Schema slices add the narrow domain constraint they need rather than one generic lock table.

### 2026-08-25 — Shared transport-idempotency ownership

**Context:** Transport replay is not an economic rule: `/join`, later inventory/progression
mutations, administrator workflows, and non-Discord jobs need the same request-replay semantics.
Assigning its persistence to Economy would make other domains depend on an unrelated game
boundary, while treating it as database-only infrastructure would put application behavior in
the adapter.

**Decision:** Transport idempotency is a shared application-wide facility owned logically by the
Operations/application-support boundary. The application layer owns the claim/replay/
fingerprint-conflict semantics and coordinates them inside the mutating use case's unit of work.
Operations owns the persistence model, repository port, retention policy, cleanup, and storage
metrics. Infrastructure implements that repository for SQLAlchemy; Economy, Players, Inventory,
Progression, and future domains neither own nor write the table directly.

The logical key is unique by `(namespace, transport_key)`. A namespace is a stable, lowercase
dotted application-operation name such as `players.join` or `economy.daily_claim`; it is not
changed for a deployment or balance/content version. The request fingerprint covers the actor
and canonical semantic inputs, excluding presentation-only or volatile data. Storage may use a
collision-resistant key digest, but callers and logs treat the original key as opaque and logs
never include the raw key or fingerprint.

The application inserts the request claim, executes or rejects the domain use case, records a
stable replay outcome/reference, and commits them together. A crash or unexpected failure rolls
back the claim with the use case, so no committed pending record exists. Same key and fingerprint
returns the recorded result; same key with a different fingerprint is a conflict. Queries do not
create transport-idempotency records.

Operations assigns every namespace a retention period at least as long as its maximum legitimate
redelivery window plus investigation margin. Initial Discord mutation namespaces retain completed
outcomes for seven days. Longer-lived job/webhook namespaces must declare a longer period before
use. Operations performs incremental cleanup only after `retain_until`, monitors table growth,
and never treats cleanup as permission to repeat a domain entitlement.

Transport idempotency remains independent of domain/business uniqueness. Each owning domain
persists its own one-use key, unique constraint, or expected revision for as long as that
entitlement must remain consumed; expiry of a transport record cannot remove it.

**Consequence:** Non-Economy mutations reuse one facility without importing Economy. Slice 1.0
may create only the generic Operations-owned request/outcome persistence, application port/
coordinator, SQLAlchemy repository implementation, retention metadata/cleanup contract, metrics,
and tests needed by the first mutating slices. It must not add Economy-specific request columns,
a generic business-uniqueness table, gameplay commands, or domain entitlements.

### 2026-08-25 — Action facts and eventually consistent goals

**Decision:** Originating use cases atomically apply required costs/rewards/XP and append an
immutable versioned action fact. Quests, achievements, analytics, and read models consume facts
eventually and uniquely by `(consumer_key, fact_id)`. Reward claims are separate business-
unique use cases. Initially consumers poll the shared database; no message broker is assumed.

**Consequence:** A committed action cannot be lost to a crashed consumer, replay cannot award
twice, and adding goals does not couple profession rules to every consumer.

### 2026-08-25 — Central safety/access policy and administrator control model

**Decision:** A safety/access boundary owns global, player, account, inventory, trade, reward,
and progression restrictions plus durable administrator capabilities. Every mutating use case
declares and checks required capabilities inside its transaction. Full economic freeze blocks
all discretionary value/progression changes in both directions while preserving reads and safe
release/correction paths.

Administrative grants have per-operation/rolling ceilings; above-threshold grants and all bulk
campaigns require a second distinct approver. `(campaign, target)` is unique. Discord roles are
presentation hints, not durable authority.

**Consequence:** The ownership and use-case contracts are fixed before the first schema, but
capability/proposal tables are added with Slice 1.3 when they first have behavior. Numeric
ceilings and bootstrap operator identities remain deployment policy due before that slice.

### 2026-08-25 — Initial SQLite operating envelope

**Decision:** Use a single bot/worker process with SQLite foreign keys, WAL,
`synchronous=FULL`, 1,000 ms busy timeout, no network waits in transactions, and at most two
application retries within a three-second budget. Phase 0 and pre-mining load gates use the
thresholds in `database.md`; crossing them starts PostgreSQL work before failure.

**Consequence:** Multiple bot writers are not supported on SQLite. Performance settings may be
changed only with recorded durability/load evidence.

### 2026-08-25 — Disposable SQLite capacity result

**Context:** The Phase 0 experiment measured a benchmark-only candidate player/wallet and
ledger/idempotency write mix. It did not create an Alembic migration or model the final mining
transaction. The accepted projected launch peak is 17 mutation transactions/second, making the
required open-loop offered rate 34 transactions/second.

**Decision:** Retain WAL, `synchronous=FULL`, 1,000 ms busy timeout, one process, and at most two
busy retries inside three seconds. Use 25/75 ms retry backoff and reserve 200 ms of the final
deadline for scheduling overhead. Budget 50 ms from writer-lock acquisition through commit.
Accept the open-loop result: three fresh-database repeats, each with a 10-second warm-up and
30-second measurement window, offered and completed 34.0 transactions/second. The worst p95/p99
were 17.601/18.595 ms; no operation retried, failed, accumulated as backlog, or violated an
invariant. Guarded-debit and idempotency diagnostics also passed.

Retain closed-loop saturation only as a contention diagnostic. On this development host, four
writers passed at 499.925 transactions/second and eight failed p99. Use 249.96 TPS (50%) as the
provisional PostgreSQL-start rate and 349.95 TPS (70%) as the provisional migration-completion
rate, subject to replacement by deployment-host and full-transaction runs.

**Consequence:** Eight writers failed the saturation p99 gate, so adding writers is not a scaling
strategy. Slice 0.3 passes for the accepted projected peak and does not trigger PostgreSQL. The
complete gameplay transaction and the selected deployment host must still be benchmarked before
public economic mutations. Details and raw evidence are in `sqlite-capacity.md` and
`evidence/sqlite-capacity-2026-08-31.json`.

### 2026-08-25 — Hybrid item ownership and availability

**Decision:** Fungible stackable items use integer holdings keyed by stable item identity;
stateful equipment/unique objects use instances. Beneficial ownership, custody, durable
reservation, equipment assignment, binding, and locks are orthogonal explicit state. Current
state is authoritative and every persistent quantity or state transition has an immutable
movement audit. Balance versions apply to operations, not separate fungible stacks.

**Consequence:** The canonical availability model is designed and tested in Slice 2.1 before
selling, crafting, equipment, collection, or trading. Trading extends it with escrow rather
than replacing it.

### 2026-08-25 — Progression and first loop

- Separate account level, profession level, mastery, achievements/collections, and prestige.
- Use mining as the reference profession and the first gather/sell/improve loop.
- Favor horizontal mastery and profession-specific prestige over uncapped global yield power.
- Do not accumulate undefined post-cap XP.
- Any progression-required random drop has a deterministic fallback.
- Treat seasons as rotating content by default, not automatic permanent-progress resets.

### 2026-08-25 — Phase 0 numerical envelope and first recurring sink

**Context:** Repeatable NPC selling requires a credible multi-horizon source/sink and progression
envelope plus a recurring sink that scales with profitable activity. A finite shop or cosmetic
catalog alone does not satisfy that gate.

**Decision:** Accept `phase0-v1` in `docs/economy-simulation.md` as the architecture envelope.
Its single TOML configuration models casual, regular, dedicated, optimized/hardcore, returning,
and alternate-account behavior at one day through three years. The initial acceptable bands
include a 15% aggregate permanent-yield cap, a 30-action full-reward allowance with 40% overflow
EV, 45–71% recurring source absorption, and a mixed-cohort six-month-plus net-supply target of
roughly 15–30% of cumulative minting.

Select non-destructive tool charges as the Slice 2.5 sink. Each profitable action consumes a
transparent charge; zero charges disable the equipment bonus rather than destroy the tool or
block the base action. Refills retire coins and must be public, affordable, and measured before
repeatable NPC selling becomes public. The current 6-coin action cost, 15-coin daily reward,
source EV, curve, and milestone prices are provisional inputs within the envelope, not approved
production content.

**Consequence:** Every later source, sink, progression curve, material loop, and permanent
modifier is simulated against the same cohorts and horizons and reports the measurements listed
in `docs/economy-simulation.md`. Changing an envelope bound or selected sink requires a versioned
model and replacement decision. Slice 2.5 still owns the gameplay implementation and validation;
this decision adds no command or schema.

### 2026-08-25 — First-schema state ownership and interim join eligibility

**Context:** Earlier game-design wording placed account XP and restriction state on the core
player record even though the architecture assigns those concerns to Progression and
Safety/access. Following that wording would silently pull later-slice columns or tables into the
first production baseline designed during Phase 0.

**Decision:** Players owns only global Discord identity, creation time, and minimal lifecycle
state. Economy owns wallets and monetary state. Progression exclusively owns account and
profession XP/levels. Safety/access exclusively owns restrictions, freezes, durable
capabilities, approvals, and access audit. The first production baseline contains no progression
or safety/access state.

Before Slice 1.3, `/join` evaluates only a narrow application-level global eligibility policy.
It may be rejected when mutations are globally disabled or startup/schema readiness is unsafe;
there is no player-specific durable restriction yet. Discord roles are not authority, and join
does not create placeholder restriction or progression rows. Slice 1.1 tests this boundary with
an injected fake; Slice 1.3 supplies its durable central-policy adapter.

**Consequence:** The first migration can remain minimal without weakening the long-term ownership
model, and later progression/safety migrations are additive rather than reinterpretations of a
player row.

### 2026-08-25 — Projected launch mutation peak for the Phase 0 SQLite gate

**Context:** The capacity experiment could not satisfy its twice-peak requirement without an
accepted launch traffic assumption. The Phase 0 economy model already uses 1,000 modeled active
players and a 50%/30%/15%/5% cohort mix, but it did not translate that activity into a peak write
arrival rate.

**Decision:** Accept **17 mutation transactions/second** as the Phase 0 projected launch peak and
**34 transactions/second** as the required twice-peak offered rate. This is a reviewable planning
input, not a production promise. Its derivation is:

- 1,000 launch active players, matching the aggregate Phase 0 supply worksheet;
- 100 simultaneous peak sessions, assuming 10% of those active players overlap during the
  busiest window;
- one submitted command per session per 10 seconds at peak, which places the model's weighted
  13.63 daily commands in a roughly 2 minute 16 second concentrated session inside the product's
  one-to-five-minute useful-session target;
- a 95.30% mutation share: 9.71 profession actions, 2.43 conversion/spending operations, 0.74
  daily claims, and 0.11 weekly-objective claims divided by 13.63 total modeled commands;
- 9.53 normal interactive mutations/second (`100 × 0.9528 ÷ 10`);
- an additive onboarding burst of 100 joins over 60 seconds, or 1.67 mutations/second; and
- a 1.5 burst factor for arrival clustering and model error, producing 16.80, rounded up to 17.

The open-loop benchmark must offer 34 transactions/second after warm-up for every measured run.
The assumption is replaced, not silently tuned, when launch population, session telemetry, or
hosting plans provide better evidence.

**Consequence:** SQLite passes Slice 0.3 only if every repeated twice-peak run meets the existing
p95/p99, retry, final-lock, and invariant gates. PostgreSQL work begins if the measured result or
any independent trigger in `database.md` fires.

### 2026-08-25 — Initial deployment, recovery, and operational authority

**Context:** The development-host SQLite result could not by itself make a future production
economy safe. A first migration needs a concrete deployment shape, fail-closed database
readiness, recoverability targets, and an operator boundary before real state exists.

**Decision:** The initial deployment is one `systemd`-managed bot process on one long-lived
Linux VM, using persistent local SSD-backed ext4/XFS storage for SQLite and encrypted,
retention-protected off-host object storage for backups. There is no second economic writer,
shared/network database volume, or ephemeral database filesystem. Production keeps WAL,
`synchronous=FULL`, foreign keys, the 1,000 ms busy timeout, and the accepted bounded retry
policy. Startup opens an existing database, verifies integrity, foreign keys, pragmas, and the
exact expected Alembic revision, and exits rather than creating, migrating, or serving against
missing/behind/ahead/incompatible state.

Backups run every 15 minutes through SQLite's online backup API, keep 15-minute points for 48
hours, daily points for 35 days, and monthly points for 12 months, and are independently opened,
checked, checksummed, and restored in drills. The initial objectives are a 15-minute RPO and a
two-hour RTO to verified service with mutations disabled.

Deployment authority comes from audited host/cloud/secret/backup access, not Discord roles.
Before Slice 1.3, the strictly parsed deployment setting
`BUTTERBOT_ECONOMY_MUTATIONS_ENABLED` defaults to false and gates every durable mutation without
creating player restriction rows. Slice 1.3 will consume a reviewed explicit Discord-snowflake
bootstrap list once to create durable audited capabilities; guild roles remain non-authoritative.
Structured application/database/startup/backup logs provide the initial metrics contract and a
small alert sink; no large monitoring platform is selected.

The accepted 17 TPS projection and 34 TPS open-loop gate are unchanged. The identical accepted
benchmark must pass on the selected production host and database volume before public durable
mutations, and must be repeated after material host/runtime/storage changes.

**Consequence:** Slice 0.4 resolves the operational design input without provisioning speculative
infrastructure or creating the first migration. Actual host/backup/log/alert provisioning,
runtime enforcement, a restore drill, and deployment-host evidence become measurable deployment
or public-enable prerequisites in `operations.md`. A second writer, unsafe filesystem, unmet
recovery objective, failed host benchmark, or weakened SQLite setting invalidates this initial
operating model and keeps mutations disabled while PostgreSQL or host remediation is evaluated.

### 2026-08-25 — Slice 1.0 production persistence baseline

**Context:** The Final Phase 0 Gate Review authorized the first production migration. Slice 1.0
needed to make the accepted player/wallet/ledger and Operations contracts concrete without
pulling `/join` or later gameplay into the foundation.

**Decision:** Alembic revision `20260825_0001` is the first production head. It creates only the
global player identity table; Economy accounts, guarded balance projections, committed ledger
transactions and non-zero postings; and Operations transport requests/outcomes. SQLAlchemy's
portable UUID and integer types implement the accepted identifier/time representation. Account
ownership and polarity, wallet uniqueness, posting non-zero, Discord snowflake, foreign-key,
and transport namespace/key constraints are database-backed. No rows mint or seed value.

Application unit-of-work exit is the sole commit boundary. All concrete repositories share that
session and never commit. SQLite mutation units begin with `BEGIN IMMEDIATE`; busy/locked retry
recreates the whole unit with the accepted attempt, backoff, and deadline contract. Player and
wallet repositories use conflict-safe inserts so concurrent future join orchestration can
converge, but Slice 1.0 adds no join use case or command.

Operations stores a claim without an outcome only inside the owning uncommitted transaction.
The unit of work rejects commit if that claim is unfinished. Success and typed rejection commit
as stable outcomes with a namespace retention period; unexpected failure rolls back all state.
Ledger correlation does not foreign-key permanent history to an expiring transport row.

Startup validates an absolute existing regular database file, storage floor, exclusive process
lock, integrity, foreign keys, required pragmas, and exactly revision `20260825_0001` before the
Discord layer is constructed. The strictly parsed global mutation adapter still defaults to
disabled. Composition is explicit Python construction in `bootstrap.py`; no service locator or
dependency-injection framework is introduced.

**Consequence:** Slice 1.1 can add the explicit join application use case over stable ports and
one transaction without changing persistence ownership. Backup/restore provisioning,
deployment-host evidence, and all other public-enable prerequisites remain external blockers;
the presence of this baseline alone does not authorize public mutation.

### 2026-08-26 — Slice 1.0 independent-review runtime remediation

**Context:** Independent review retained the authorized schema/ownership design but demonstrated
that timed-out shutdown could release the process lock while a transaction owner task remained
alive, and that sibling pathname locks could be bypassed through aliases. It also identified
production-volume, migration-target, persistence-backstop, telemetry-accuracy, and operational
test gaps. No production database has been released from the first revision.

**Decision:** The runtime stops unit-of-work admission when shutdown begins, captures active and
waiting owners, and retains that captured set through shutdown. Explicit active, committing,
committed, rollback, and failure phases ensure the timeout path cancels only work whose commit has
not begun. All captured owners are awaited. An owner that exceeds bounded cancellation cleanup
causes fail-stop without engine disposal or ownership release. No other task operates a live
SQLAlchemy session during application work; a single shielded completion helper exclusively owns
commit, rollback, and close after the application body exits. Shutdown cleanup is
cancellation-safe.

The configured database and approved data root are canonicalized. Symlink traversal, nested or
outside-root paths, and multiply linked database files fail closed. On the accepted single Linux
VM, one fixed abstract Unix-domain socket supplies kernel-lifetime process ownership, so mutable
lock path or root names cannot bypass it. The database and root device/inode are recorded and
revalidated at writer admission; checked-out SQLite connections are matched to that approved
identity through `PRAGMA database_list`. Production enablement requires the recorded Linux mount
identity and ext4/XFS. A resilient storage/WAL sampler emits critical unsafe observations and
deduplicated mutation-safety transitions.

Because revision `20260825_0001` remains unreleased and has never been externally consumed, its
Operations table is tightened in place with SQLite shape, length, and embedded-NUL checks.
Readiness rejects a committed incomplete claim. Applied,
typed-rejection, and cleanup success telemetry is deferred until commit; busy exhaustion has a
dedicated critical event. Application retry orchestration passes only generic attempt/budget
context, while the concrete SQLite unit of work chooses its busy timeout. Explicit Alembic URLs
take precedence over ambient `BUTTERBOT_DATABASE_PATH`.

**Consequence:** The baseline revision identifier and authorized table set remain unchanged.
Existing Phase 0 evidence and gameplay scope remain unchanged. Slice 1.0 requires another
independent review and is not accepted by implementation alone.

### 2026-08-26 — Slice 1.0 failed-gate completion and storage hardening

**Context:** The repeat independent gate demonstrated cancellation after SQLite durability but
before `session.commit()` returned, pathname replacement during an already-active transaction,
malformed committed transport payloads, SQLite REAL storage in exact-integer columns, monitor-first
shutdown blocking transaction drain, and permanently lost mutation-state transitions after a
telemetry exception. Revision `20260825_0001` is still unreleased and unconsumed.

**Decision:** A unit of work treats final identity validation, commit, callbacks, rollback, and
resource close as explicit completion. Cancellation before completion begins is followed through
to confirmed rollback and then propagated. Once completion begins, one shielded helper owns the
session operation until its result is definitive. Confirmed commit advances the phase, runs every
deferred callback exactly once, completes cleanup, and returns the stable application result even
if owner cancellation arrived during that interval. This deliberately suppresses that cancellation
instead of reporting durable success as cancellation. Callback failures, including a callback's
`CancelledError`, are logged without skipping later callbacks or changing the durable result.

SQLite infrastructure revalidates the configured database/root and the connected main-database
identity at the final boundary before commit. This check does not eliminate the final filesystem
TOCTOU. A post-commit confirmation marks runtime safety false if that assumption was breached while
preserving callbacks and the committed result. Production therefore requires an unprivileged,
capability-free service that owns neither the administrator-owned main database nor sticky approved
root, can write both through its service group, and cannot write the root's parent. The fixed
abstract socket remains the process-ownership primitive, and every possible writer must share one
Linux network namespace; separate `PrivateNetwork` or container network namespaces are
incompatible.

Because the baseline is unreleased, tighten revision `20260825_0001` in place rather than add a
second revision. SQLite-only checks now require canonical UUID text, integer storage classes for
every Slice 1.0 exact identifier/timestamp/version/amount/posting, and valid top-level JSON objects
for completed outcomes. Application boundaries enforce signed-64-bit input and checked arithmetic.
Readiness rejects malformed committed transport or baseline storage, and replay wraps parser
failure as a persistence-contract error.

Storage-monitor shutdown and captured-owner drain start concurrently and are independently
bounded. Either failure retains engine and process ownership and reports `ShutdownIncomplete`.
The monitor tracks actual safety separately from the last successfully emitted transition; failed
telemetry is retried without replacing the primary storage failure, and deduplication begins only
after successful emission.

**Consequence:** These changes close the reported implementation gaps without adding a command or
gameplay structure. Linux permission/identity and namespace adversarial tests remain mandatory on
the native Linux gate host. Slice 1.0 remains `IN REVIEW` until another independent review.

### 2026-08-27 — Slice 1.0 canonical outcomes and terminal cleanup semantics

**Context:** The next independent gate found that syntactically valid JSON could still replay with
different types or ambiguous values, generic post-commit confirmation failure could leave runtime
mutation safety unchanged, resource cleanup could rewrite a confirmed commit as caller-visible
failure or skip lifecycle unregister, and shutdown retry could lose the original owner capture or
orphan a timed-out monitor-close task.

**Decision:** Transport outcome persistence accepts only the concrete JSON value model that can be
detached, encoded with finite numbers, and replayed without type changes. Repository writes store
that canonical form; startup and replay reject duplicate keys, non-finite decoded numbers, and any
non-canonical stored representation. This is application/startup validation in addition to the
baseline SQLite JSON-object backstop and adds no table or column.

Once session commit returns successfully, post-commit confirmation, callbacks, resource cleanup,
lifecycle bookkeeping, runtime safety, and operational reporting remain separate outcomes. Any
post-commit confirmation failure marks runtime mutation safety false but cannot change the committed
business result. Commit callbacks remain exactly-once. Cleanup attempts all resources, reports a
failure, marks runtime safety false, and always unregisters the unit of work without converting a
confirmed commit into failure or replacing an earlier body/completion error.

Shutdown retains its first captured owner set across retries and reuses a still-running monitor-
close task. Engine disposal and process-ownership release occur only after that retained state is
complete; a failed disposal retains ownership and reports `ShutdownIncomplete`.

**Consequence:** The persistence baseline and revision identifier remain unchanged. No `/join`,
gameplay, progression, inventory, banking, business-entitlement, or command-specific structure is
introduced. Slice 1.0 still requires another independent gate review.

### 2026-08-27 — Slice 1.0 retained cleanup, telemetry, storage, and admission remediation

**Context:** The latest independent gate showed that a failed resource close could leave a usable
connection after the unit of work discarded its references and unregistered, allowing shutdown to
release process ownership. It also found that operational telemetry could replace application
outcomes, Linux production validation did not enforce the reviewed owner/group/mode contract,
mutation-state recovery could overwrite a pending unsafe event, and writer admission did not
consume the transaction attempt budget.

**Decision:** A unit of work clears each session/connection reference only after that resource's
close succeeds. Failed resources leave active-owner tracking only by entering a runtime-owned
unresolved set. Shutdown retries the retained objects within its cleanup bound and fails stopped
with engine and process ownership intact on failure or timeout; later retries continue from the
same set. No successor can own the database until every old resource is unusable.

Every operational telemetry invocation has a narrow non-throwing boundary. Mutation-safety state
changes append ordered pending events that drain only on successful emission. Writer-semaphore
admission consumes the remaining attempt budget and SQLite busy timeout is computed after
admission. Production storage configuration names the reviewed administrator UID and Butterbot
service-group GID; Linux startup requires exact root/database ownership, group, modes
`1770`/`0660`, no parent replacement access, a non-root service identity, and zero effective
capabilities.

**Consequence:** No schema or migration changes are required. The initial revision and Slice 1.0
scope remain unchanged. Native Linux execution is still required to verify the ownership,
permission, capability, filesystem, mount, and namespace contracts. Slice 1.0 remains subject to
another independent gate review.

### 2026-08-31 — Slice 1.0 bounded readiness, aggregate integrity, and graceful stop

**Context:** The Slice 1.0 gate found that production SIGTERM did not enter the explicit runtime
shutdown path, startup scanned all retained/permanent history, incomplete account/player aggregates
could be committed or silently repaired, release identity was not supplied by composition, and the
checked capacity evidence assertions did not enforce every acceptance dimension.

**Decision:** POSIX SIGTERM closes Discord and then executes the existing bounded database drain,
cleanup, disposal, and process-ownership release path. Startup is bounded with respect to retained
transport and permanent ledger/posting history: it keeps exact schema/PRAGMA, indexed incomplete-
claim, and aggregate-completeness checks. Exhaustive SQLite integrity/foreign-key, stored-shape, and
canonical-history checks move to a stopped-service streaming verifier. Unit-of-work commit refuses
players without wallets and accounts without projections; an existing account missing its
projection is corruption, never a request to recreate zero. The unreleased baseline constrains
permanent audit identity, composition requires an immutable release identifier, and `/ping` emits
the documented command-completion event. Capacity evidence and the benchmark exit code now enforce
all repeat, twice-peak, configuration, backlog/completion, and correctness gates.

**Consequence:** Native Linux subprocess verification of SIGTERM during active, waiting, and
committing transactions remains mandatory before an independent Slice 1.0 gate can pass. The
PostgreSQL migration-portability decision remains deferred to the PostgreSQL adoption gate. Refill
participation and zero-charge economy sensitivity remain deferred to Slice 2.5/public NPC selling;
neither is reopened by this remediation.

### 2026-09-01 — Authoritative aggregate sentinel and permanent-reference contract

**Context:** Independent Slice 1.0 review showed that join retry could recreate a deleted wallet,
Alembic head did not prove the sentinel triggers still existed, an active sentinel row could be
deleted directly, whitespace-only permanent references crossed both validation boundaries, and
mocked Linux ownership/capability tests were being treated as production proof.

**Decision:** Wallet creation requires the explicit player-created result from the same unit of
work and cross-checks it against tracked creation state. Existing incomplete aggregates raise a
fail-closed persistence invariant. SQLite startup fingerprints the sentinel and all three
aggregate tables its predicates depend on, and verifies the sentinel index plus exact normalized
maintenance/protection triggers. Active sentinel deletion and every
sentinel update are rejected by database triggers; legitimate repair clears rows only after the
underlying aggregate is complete. Permanent opaque references are untrimmed visible ASCII without
whitespace or controls at both application and SQLite boundaries. The separate
`native_linux_kernel` gate provisions and exercises real identities, permissions, mountinfo,
capabilities, namespace state, abstract-socket ownership, replacement behavior, and SIGTERM; mock-
driven unit tests are excluded from its report. The existing shutdown stages remain sequentially
bounded at approximately 17 seconds for database shutdown, within `TimeoutStopSec=30s`.

**Consequence:** The unreleased Slice 1.0 baseline is tightened in place. Startup remains bounded
with respect to historical business rows, while the stopped-service streaming verifier remains the
independent exhaustive path. Slice 1.1 and unrelated architecture remain unopened.

## Remaining unresolved decisions

These do not alter the approved initial player/wallet/ledger identity, but each gates its named
slice:

- Validation of the provisional Phase 0 action cadence, cohort mix, daily amount, source/sink EV
  and variance, stockpile targets, and progression bands against play tests and production
  telemetry; changes require a new model version
- Replacement of the accepted 17 TPS projected launch peak when measured launch/session evidence
  becomes available; a changed peak requires a new twice-peak benchmark result
- Actual provider/VM instance, off-host backup/log/alert services, and named primary/alternate
  role holders must be recorded before production deployment; these implement the accepted
  `operations.md` contract rather than reopen its topology, RPO/RTO, or authority decisions
- Administrator monetary ceilings and alert destinations before the grant slice
- Bank gameplay purpose, capacity/protection/fee/interest policy, and treatment by all wealth,
  limit, affordability, leaderboard, and sanction rules before a bank slice
- Transfer account-age/progression gates, numerical rolling limits, fee decision, sanctions,
  privacy, alert thresholds, and manual-review/appeal owner before transfers
- Daily claim period/grace behavior and target share of ordinary income
- Exact shipped level curves, content tiers, target cohort playtimes, and account-versus-
  profession XP sources before public profession rewards
- Tool-charge capacity, refill bundle/price, base-tool behavior, and implementation validation
  before repeatable NPC selling; permanent breakage remains unapproved
- Rarity names, binding rules by item, inventory limits, durability/repair selection, and
  permanent-breakage policy before affected item/equipment content
- Mastery curve migration, respecialization accounting, and future node/excess-XP policy before
  mastery
- Prestige epochs/cooldowns, retained-asset eligibility, reset/cost/reward caps, and any
  account-wide prestige before prestige
- Trade fee/tax, source-aware rolling policy, visibility, manipulation response, and whether a
  marketplace is justified beyond direct item-for-coin trade
- Catch-up strength, limited/legacy content, and whether a future season can reset durable
  progression
- Retention/anonymization periods for action facts, access audits, economic/item history,
  operational logs, and deleted-player identity; transport-idempotency retention is governed by
  the accepted namespace policy above
- Background scheduling/durability beyond the initial database fact consumer


### 2026-09-14 — Release manifest and immutable aggregate identity

The baseline embeds its historical trigger DDL independently of runtime modules; a frozen
snapshot proves its schema. New schema changes belong to revision `20260914_0002`.
SQLite rejects aggregate identity/ownership changes before they bypass sentinels.
Readiness fingerprints the complete release schema without scanning history. Native
capability coverage is mandatory. Windows cannot supply outstanding native evidence;
Slice 1.1 remains unopened.

Before future commands persist input-derived stable outcome payloads, define and enforce
explicit serialized-byte, nesting-depth, and collection-size limits. This remediation
does not expand transport outcomes. Optional capacity evidence validator hardening is
deferred; recorded evidence is unchanged.

### 2026-09-14 — Replacement protection and complete native gate accounting

Revision `20260914_0003` adds BEFORE INSERT collision guards to players, accounts and
balance projections. All aggregate uniqueness collisions abort before SQLite REPLACE can
implicitly delete a row, independently of recursive_triggers. This intentionally includes
conflicting INSERT OR IGNORE and UPSERT statements; use UPDATE for legal non-identity
changes. Existing no-op UPDATE assignments remain allowed. Player/wallet retries read an
existing row under the unit of work's BEGIN IMMEDIATE writer transaction before inserting,
so concurrent requests still converge without colliding inserts. The migration reconstructs
missing completeness sentinels from older holes, never accounts, balances or ownership.
The two historical revisions remain unchanged.

Readiness filters the literal reserved `sqlite_` prefix with GLOB, including legal near-prefix
application objects in the release manifest comparison. Startup remains bounded by schema
metadata and indexed sentinels.

The native runner freezes all 16 required case identities, including each SIGTERM phase,
checks JUnit counts and outcomes, rejects missing/duplicate/unexpected cases, and removes
inherited pytest selection/plugin configuration. It loads pytest-asyncio explicitly. Only
the exact namespace case may skip, with the exact approved reason following an identified
C-locale util-linux EPERM/EACCES denial before the validation child starts. Child failures,
unknown utility failures, and missing tooling fail. Raw JUnit, stdout/stderr, layout evidence,
dependency versions and before/after source hashes are retained beside the report. Source
changes during execution fail the gate; Windows/WSL preflight cannot pass.

Native Linux evidence for the repaired candidate is still required. No host was provisioned
by these local changes; Slice 1.0 remains IN REVIEW and Slice 1.1 remains blocked.

### 2026-09-16 — Defer Linux execution and permit provisional local join development

**Context:** The user explicitly chose to defer Linux and continue locally after discussing
the dependency and rework risk. Slice 1.0 code remediation and Windows checks passed, but
native release acceptance is still absent.

**Decision:** Permit provisional Slice 1.1 implementation and local tests before Slice 1.0
PASS. This is a narrow development-order exception, not release acceptance or authorization
for later slices or public mutation. Preserve all native gate requirements; run them against
the final candidate before release acceptance or production use. The original candidate
075252ea9a1419cc431f3466902953309ec34b91 and its bundle remain historical and unchanged.
Keep normal composition's production storage checks and disabled mutation default. Exercise
allowed joins only in disposable local tests with an injected eligibility policy.

`players.join` is the stable seven-day transport namespace. The application service owns
one transaction containing the request claim, player, zero-balance wallet/projection, and
outcome. Distinct interactions converge through existing aggregate constraints. New requests
evaluate global eligibility inside the transaction; denials commit only typed-rejection
transport bookkeeping. Replays return their original outcome even after eligibility changes,
without creating or repairing player/wallet state. Pseudonymized players are not reactivated.
No player restrictions, ledger issuance, or new schema are introduced.

Join outcomes have a fixed code and exactly an empty JSON object payload (two UTF-8 bytes,
one root object, zero members, no nested values); input-derived IDs, names, balances, or other
payload data are never persisted in the outcome. Replay decoding rejects other codes/kinds or
nonempty payloads. This avoids expanding the generic outcome contract; explicit general
byte/depth/member limits remain required before a later feature persists input-derived payloads.
Discord defers and responds ephemerally, and performs no network work within the transaction.

**Consequence:** Slice 1.1 can be tested locally but remains provisional. Native failures may
require foundation and join rework. Neither Slice 1.0 nor Slice 1.1 is declared PASS, and the
next slice is not automatically authorized.

### 2026-09-16 — Isolated interactive Discord join development

**Context:** The user requested interactive `/join` testing while Linux acceptance remains
deferred. Normal startup intentionally cannot enable Windows mutations against a configured
database.

**Decision:** Add an explicit `python -m butterbot.discord_app.development` entry point,
separate from normal composition. Require a dedicated development token, test guild ID, and
tester user ID. Do not fall back to the normal token or reuse it when configured. Register only
the explicit ping/join extensions as guild commands; never synchronize global commands. Check
both the server and tester at the command-tree boundary, including denying direct messages.

Each launch creates a new directory under the checkout's ignored `data/discord-development`
and applies the unchanged migrations with an explicit URL before opening the normal database
runtime. There is no supplied database path and no reuse of existing storage. Reject redirected
storage roots. Retain disposable files for diagnosis after shutdown; subsequent launches always
start empty. This explicit test launcher is the sole exception to normal startup's no-migration
rule and enabled-mutation production-path requirement. Normal settings/composition are unchanged.

Use the real join service, transactions, process ownership, schema checks, storage monitor, and
runtime-safety eligibility. No currency is created and no other mutation service is composed.
Logs identify development sessions and tokens are excluded from configuration representations.

**Consequence:** The authorized tester can exercise join creation/retrieval in Discord without
production data or a Linux host. The launcher's guild/user checks are a development access limit,
not the future durable administrator capability policy. This remains provisional local testing;
all native Linux, independent acceptance, and public-enable gates remain required.

2026-09-17 clarification: interactive development additionally requires a single channel ID.
The command-tree check requires exact guild, user, and channel matches; other channels and
threads cannot execute the application. Guild command registration is unchanged. This limits
execution, not Discord's command-picker visibility. The local server setting remains the
previously selected server; the newly supplied identifier is a channel, not a replacement guild.

2026-09-17 independent review: the Discord base class installs a text `help` command whose
mention-based dispatch does not use the application-command scope check. Disable default help
in the development bot so its only commands are the explicitly registered, scoped slash commands.
This closes an unintended public-response path outside the configured channel/user; no join
mutation bypass was demonstrated. Production composition is unchanged.
