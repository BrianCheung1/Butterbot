# Butterbot development roadmap

## How to use this roadmap

Each slice is an end-to-end outcome with domain rules, an application use case, persistence
and migration where required, Discord presentation, telemetry, and tests. **Spine** slices
establish contracts consumed by later work and land sequentially. Parallel work starts only
after its named contract is stable; one owner serializes Alembic revisions.

Reference gameplay remains non-production until its integration gate passes. A private read
command does not require a complete years-long content catalog, but repeatable rewards require
an approved numerical envelope, abuse controls, a scalable recurring sink, and load evidence.

## Phase 0 — First-schema readiness

No gameplay migration is created before Slices 0.1–0.3 are accepted. Experimental schemas used
by the load spike are disposable and never become Alembic history.

### Slice 0.1: Ratify the first-schema contract — Spine

Review the accepted ADRs in `docs/decisions.md`: global player scope; wallet-only account
taxonomy; chart of accounts and supply formulas; UUID/snowflake/epoch-millisecond
representation; `/join` versus pure `/balance`; transport plus business uniqueness; central
restrictions; administrator approval shape; and SQLite operating mode. Record any replacement
decision before schema work. Exit criterion: no open choice can change initial player, wallet,
ledger, idempotency, restriction/capability, or audit identity.

### Slice 0.2: Initial balance envelope and simulator — depends on 0.1, Spine

Build a design worksheet/simulator—not gameplay—for casual, regular, optimized, returning, and
alternate-account cohorts. Record actions/day, commands and elapsed time per milestone,
source/sink expected value and variance, content/unlock bands, multiplier budget, expected coin
and item stockpiles, daily-reward share, and candidate activity-scaled recurring sinks. Select
the first sink required before NPC selling. Exact later-game content may remain provisional;
the first loop must fit a credible extensible daily/weekly/monthly envelope.

### Slice 0.3: Disposable SQLite capacity experiment — depends on 0.1, Spine

Benchmark candidate player/wallet creation and representative ledger/idempotency writes at
twice the projected launch peak from 0.2. Validate `foreign_keys=ON`, WAL,
`synchronous=FULL`, 1,000 ms busy timeout, retry budget, guarded updates, and rollback. Record
measured sustainable rate, latency/retry results, hardware, and whether the accepted PostgreSQL
trigger already fires. This experiment does not create a production migration.

### Slice 0.4: Persistence and composition foundation — depends on 0.1–0.3, Spine

Create the deliberately designed minimal Alembic baseline, async engine/unit of work,
schema-readiness check, database lifecycle, and backup/restore instructions. Include only the
player/wallet, committed-ledger/projection, and transport-idempotency structure required by the
first money slices; safety/access tables arrive with Slice 1.3. Verify clean upgrade,
constraints, rollback, concurrent account creation support, and portable types. No command
creates economic value.

### Phase 0 gate

Phase 0 is complete only when the ADR, numerical envelope, load result, and baseline migration
are reviewed together. If the load result triggers PostgreSQL, change the backend before
public economic mutations instead of weakening durability or retry guarantees.

## Phase 1 — Identity, private balance, and trustworthy money

### Slice 1.1: Explicit `/join` — depends on Phase 0, Spine

A Discord user explicitly creates or retrieves one global player and wallet. The interaction
ID protects transport replay; unique Discord-player and player-wallet constraints protect the
business fact. Competing first use converges on one result. Test restriction behavior,
rollback, privacy, and no privileged intents.

### Slice 1.2: Pure private `/balance` — depends on 1.1, Spine

A joined player views their wallet ephemerally. The query never creates state; an unjoined user
is invited to `/join`. There is no public other-player wealth command. Support inspection uses
a durable capability and access audit. Test zero balance, unjoined, frozen, and missing/deleted
identity behavior.

### Slice 1.3: Administrator capability, proposal, and freeze workflow — depends on 1.1, Spine

Add the safety/access migration; bootstrap approved operator identities; assign durable
capabilities; inspect a player; propose an operation; require a second distinct approver above
the configured threshold or for bulk work; and apply/release central restrictions. Approve
numeric ceilings and alert destinations before completion. Test Discord-role bypass attempts,
self-approval rejection, capability revocation, audit immutability, and full-freeze coverage.

### Slice 1.4: Audited grant — depends on 1.3, Spine

An authorized operator grants coins using `issuance.admin`, a reason, transport key, and unique
`(campaign, target)` or proposal identity. This proves posting polarity, balance projection,
supply formulas, approval execution, reconciliation, correction readiness, and duplicate
protection using different interaction IDs. There is no balance setter.

### Slice 1.5: Player history and compensating correction — depends on 1.4, Spine

A player pages through safe wallet history; an authorized operator performs a bounded debit or
compensating correction. Test deterministic ordering, hidden operator metadata, normal account
polarity, insufficient funds, freeze bypass audit, replay, and supply reconciliation.

### Slice 1.6: Daily claim — depends on 1.4; parallel with 1.5 after ledger contract

A player inspects and claims the approved modest daily reward. Enforce unique
`(player, claim_period)` separately from interaction idempotency. Test exact UTC boundaries,
concurrent claims with distinct transport IDs, replay after response timeout, restriction
scopes, and the approved grace rule.

### Slice 1.7: Wallet transfer with abuse controls — depends on 1.5, Spine for P2P value

Approve and implement account-age/progression gates, inbound/outbound rolling limits,
sanctions/manual review, alert thresholds, and optional fee decision. Transfer debit, credit,
limits, restrictions, history, and business uniqueness atomically through the shared P2P
value-movement policy. Test funnels, repeated counterparties, competing spends, overflow,
freeze scopes, and same business intent with multiple interactions.

### Phase 1 integration gate

Reconcile all test ledgers, projections, and supply formulas; run concurrent join, grant,
claim, spend, and transfer tests; exercise a full mutation freeze and correction drill; verify
source/sink/P2P telemetry. No gameplay faucet consumes an unreliable ledger.

## Phase 2 — Items and the first controlled value loop

### Slice 2.1: Catalog, canonical availability, and inventory view — depends on 1.1, Spine

Load a minimal validated catalog and show an empty inventory. Implement beneficial ownership,
custody, binding, locks, equipment assignment, guarded state revisions, fungible reservation
quantities, and the instance transition matrix before any item mutation feature. Add an audited
operator grant to exercise complete movement journaling and reconciliation. Tests cover stable
identity versus balance version, concurrent reservations, overbooking, every transition, and
transport plus purpose uniqueness.

### Slice 2.2: Account and mining progression foundation — depends on 1.1; parallel with 2.1

Show a profile with account level and mining at zero XP. Prove integer XP, versioned level
derivation, stable statistic keys, cap behavior with no hidden post-cap accumulation, and pure
domain code. No repeatable XP source exists yet.

### Slice 2.3: One NPC shop purchase — depends on 1.5 and 2.1, Spine for commerce

Inspect a versioned quote and buy one stackable item. Consume the quote exactly once independent
of interaction ID; retire coins and add inventory atomically. Test quote expiry/version,
purchase limits, restrictions, insufficient funds, rollback, concurrent purchases, and catalog
price-cycle checks.

### Slice 2.4: One non-production mining action — depends on 2.1 and 2.2, Spine for professions

Perform one bounded action that awards a basic material and mining XP, and atomically records
cooldown/opportunity revision, complete item movement, immutable action fact, and outcome.
Validate every inert reward component against the mining source policy and content budget.
Test forced random boundaries, separate transport IDs against one opportunity, restrictions,
and consumer replay. Keep the command development-only until the phase gate.

### Slice 2.5: Activity-scaled recurring sink — depends on 0.2, 2.3, and 2.4, Spine

Implement the recurring sink chosen by the Phase 0 model—such as explicit supplies, repair/
charges, repeat crafting input, or access cost. It must offer understandable value, scale with
profitable activity, avoid permanent item loss, and remain useful for established players.
Test its business uniqueness, expected demand, affordability, stockpile behavior, and
interaction with casual and optimized mining.

### Slice 2.6: NPC sale of mined material — depends on 1.5, 2.4, and 2.5, Spine

Sell an explicit available quantity. Remove items and issue coins atomically using the applied
catalog version. Test reservation races, buyback limits, restriction scopes, bounds, distinct
transport IDs, and deterministic shop/crafting/sell arbitrage paths.

### Slice 2.7: Representative full-write load gate — depends on 2.4–2.6

Benchmark the real action transaction—inventory, XP, opportunity, item audit, action fact,
idempotency, restriction checks, and telemetry—at twice projected peak using the accepted
database thresholds. Begin/move to PostgreSQL if a trigger fires.

### Phase 2 integration gate

Simulate and play-test join, mine, sink, sell, and buy across approved cohorts. Validate
currency and item invariants, source/sink ratio, stockpiles, unlock spacing, useful daily and
weekly choices, alt sensitivity, explainable outcomes, and full telemetry. Only then may the
first repeatable gameplay loop become public.

## Phase 3 — Equipment, crafting, reporting, and deferred bank

After Phase 2 contracts stabilize, Slices 3.1–3.4 and reporting can proceed in parallel, with
one owner for item/economy invariants and migrations.

### Slice 3.1: Equipment modifiers and derived stats

Add a tool slot and bounded modifier using the Phase 2 availability model. Equip/swap/bind
atomically; derive total stats. If Slice 2.5 selected repair/charges, extend rather than replace
that state. Test modifier order/caps, unavailable assets, rebalance behavior, and movement
journal completeness.

### Slice 3.2: Deterministic crafting

Craft one item from exact available materials and coins. Reservations, consumption, sink
posting, output, movement facts, and result are atomic. Test competing crafts, rollback,
content references, restrictions, and positive-value cycles.

### Slice 3.3: Mining tiers and rare drops

Add a second meaningful choice/tier and a rare reward. Simulate expected value/variance and
multiplier budgets. Any progression-required random reward includes fragments, pity progress,
exchange, crafting, or another deterministic fallback; unbounded RNG is cosmetic only.

### Slice 3.4: Incremental economy reporting

Build indexed, rebuildable projections for supply formulas, source/sink flow, percentiles,
stockpiles, retry/contention, restrictions, and reconciliation. Enforce query budgets; heavy
rebuilds run from a safe snapshot. Reporting pressure is a PostgreSQL trigger, not permission
to block gameplay writes.

### Slice 3.5: Purposeful bank — depends on a new bank ADR

Approve the bank's player choice and exact capacity, protection, fee/interest, transfer,
affordability, wealth, leaderboard, escrow, restriction, and supply semantics. Then add the
account kind and deposit/withdraw use case atomically. If the ADR cannot justify the extra
surface, keep the feature deferred rather than creating a second balance for aesthetics.

## Phase 4 — Goals and breadth

The following may proceed in parallel after action-fact and item/progression contracts are
stable. Shared fact schemas and Alembic order remain serialized.

### Slice 4.1: One quest

Consume committed action facts with unique `(consumer_key, fact_id)` progress, then claim the
reward once in a separate use case. Test crash/replay, expiry, backfill, restrictions, and
reward budget.

### Slice 4.2: One achievement

Award one explicit milestone exactly once from facts and display it. Prove criteria versioning,
safe backfill, and no duplicate reward.

### Slice 4.3: One consuming collection

Donate an available material atomically to a permanent tier. Prove item sink behavior,
movement audit, legacy completion after catalog additions, and deterministic fallback for any
required random item.

### Slice 4.4: Mining mastery choice

First approve curve migration, respec accounting, point caps, and future-node/excess-XP rules.
Then implement one specialization with bounded derived effects and no silent retroactive
points.

### Slice 4.5: Category leaderboards

Display deterministic, privacy-aware wealth, profession, collection, and achievement
projections. They never write gameplay state or run unbounded live-ledger queries.

### Phase 4 integration gate

One fact cannot advance a consumer twice, claims cannot award twice, backfills reproduce
results, and read models rebuild without changing authoritative gameplay state.

## Phase 5 — Safe player trading

### Slice 5.1: Extend availability with trade escrow — depends on 2.1 and 4.3, Spine

Add trade reservation/custody purposes and state transitions to the existing model. Finalize
tradable/bound/equipped/locked rules and support inspection before assets move between players.

### Slice 5.2: Item-for-coin direct trade — depends on 1.7 and 5.1, Spine

Offer, accept, cancel, and expire one item/quantity for coins. Coin escrow is an internal
primitive, not a player-facing coin-only transfer substitute. Settlement routes through the
same P2P restrictions, rolling limits, fees, and suspicious-flow policy as transfers. Test
state revisions, both-party idempotency, asset races, freeze/cancel behavior, and escrow
reconciliation.

### Slice 5.3: Richer direct trade — depends on 5.2

Extend the proven offer only as player evidence requires: multiple items or barter. Preserve
atomic all-or-nothing settlement and shared P2P controls.

### Slice 5.4: Marketplace/listings — depends on 5.2; optional later

Only after direct-trade evidence supports it, approve price visibility, tax/listing fees,
expiry, manipulation response, and reporting capacity. Do not build an auction house
speculatively.

## Phase 6 — Additional professions and live content

Fishing, farming, and event work can proceed in parallel with Phases 4–5 once their individual
dependencies are stable.

### Slice 6.1: Fishing reference slice — depends on Phase 3 profession contracts

Implement one location, catch table, profession XP, and profession-specific choice. Reuse only
the common contract mining proved.

### Slice 6.2: Farming reference slice — depends on durable scheduling decision

Implement plant and harvest for one crop with durable UTC epoch-millisecond state and atomic,
business-unique harvest. Farming owns its time-state semantics and does not block fishing.

### Slice 6.3: Random event — depends on action facts and reward validation

Implement one bounded choice/bonus event with versioned odds, domain one-use identity, and no
involuntary loss.

### Slice 6.4: Rotating content — depends on shops and quests

Add effective-dated shops/quests with deterministic eligibility and no requirement that a job
run at the exact boundary.

## Phase 7 — Endgame and replay

### Slice 7.1: Prestige ADR and preview — Spine

Approve curve migration, epoch/cooldown, reset/retention, high-tier retained assets, stockpiles,
respec state, and capped repeat rewards. Preview exact effects without mutation and validate
months-scale simulations.

### Slice 7.2: Mining prestige execution — depends on 7.1, Spine

Execute the previewed profession reset atomically using a unique prestige epoch, preserve the
legacy record, safely unequip ineligible items, and replay the same result.

### Slice 7.3: Prestige challenge and cosmetic goal — depends on 7.2

Add one replay-altering challenge and non-economic legacy reward. Measure whether prestige
creates choice rather than obligatory compounding value.

### Slice 7.4: Seasons, only if approved

Seasons begin as rotating goals and leaderboards. Any durable reset is a separate product,
migration, communication, and retention decision.

## Dependency and parallel-work summary

The mandatory initial spine is:

```text
0.1 ADR -> 0.2 balance model -> 0.3 load spike -> 0.4 persistence
  -> 1.1 /join -> 1.2 /balance -> 1.3 admin/safety -> 1.4 grant -> 1.5 ledger controls
  -> 2.1 availability + 2.2 progression -> 2.4 mining -> 2.5 recurring sink -> 2.6 selling
  -> Phase 2 simulation/load gate -> public gameplay
```

Safe parallel lanes are:

- history and daily after the ledger contract; transfers only after safety/abuse policy;
- item catalog/availability and progression after player identity;
- equipment, crafting, expanded mining, reporting, and bank ADR after their Phase 2 owners;
- quests, achievements, collections, mastery, and leaderboards after action facts;
- fishing, farming, and live content after the first profession contract.

Do not parallelize work that is still defining account semantics, business uniqueness, item
availability, action-fact delivery, reward authority, modifier order, restriction scope, or
Alembic head order.

## Quality gate for every implementation slice

Run `ruff check .`, `ruff format --check .`, strict `pyright`, and `pytest`. Add pure rule tests,
real-SQLite service tests, migration-path tests, Discord adapter tests, and concurrent tests
using both repeated and distinct transport IDs. Update design, balance evidence, and decisions
with the same change.
