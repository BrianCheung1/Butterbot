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

## Remaining unresolved decisions

These do not alter the approved initial player/wallet/ledger identity, but each gates its named
slice:

- Phase 0 balance-envelope numbers: action cadence, initial daily amount, progression bands,
  source/sink expected values, first activity-scaled recurring sink, stockpile targets, and
  launch cohort assumptions
- Measured SQLite sustainable write rate and projected peak; the thresholds and configuration
  are accepted, but the empirical result must be recorded before the first migration
- Deployment/CI/hosting, backup owner, recovery objectives, observability stack, and bootstrap
  administrator Discord identities
- Administrator monetary ceilings and alert destinations before the grant slice
- Bank gameplay purpose, capacity/protection/fee/interest policy, and treatment by all wealth,
  limit, affordability, leaderboard, and sanction rules before a bank slice
- Transfer account-age/progression gates, numerical rolling limits, fee decision, sanctions,
  privacy, alert thresholds, and manual-review/appeal owner before transfers
- Daily claim period/grace behavior and target share of ordinary income
- Exact level curves, content tiers, target cohort playtimes, and account-versus-profession XP
  sources before public profession rewards
- Initial recurring sink selection and implementation before repeatable NPC selling
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
