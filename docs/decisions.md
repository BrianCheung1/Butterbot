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
writers passed at 499.505 transactions/second and eight failed p99. Use 249.75 TPS (50%) as the
provisional PostgreSQL-start rate and 349.65 TPS (70%) as the provisional migration-completion
rate, subject to replacement by deployment-host and full-transaction runs.

**Consequence:** Eight writers failed the saturation p99 gate, so adding writers is not a scaling
strategy. Slice 0.3 passes for the accepted projected peak and does not trigger PostgreSQL. The
complete gameplay transaction and the selected deployment host must still be benchmarked before
public economic mutations. Details and raw evidence are in `sqlite-capacity.md` and
`evidence/sqlite-capacity-2026-08-25.json`.

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
- Retention/anonymization periods for action facts, idempotency outcomes, access audits,
  economic/item history, operational logs, and deleted-player identity
- Background scheduling/durability beyond the initial database fact consumer
