# Architecture

## Current repository state

The repository currently contains only the `butterbot.discord_app` bootstrap, environment
configuration, a `ButterBot` subclass, and the presentation-only `/ping` cog. Its tests cover
startup extension loading, default intents, configuration validation, and the ping response.
There is no gameplay domain, application service, persistence implementation, or Alembic
environment yet. The structure below is the target introduced slice by slice, not a claim
about code that already exists.

## Intended shape

Butterbot uses a small layered architecture organized around vertical features. Layers are
dependency boundaries, not a requirement to create an interface for every class.

```text
Discord cogs/views  --->  application use cases  --->  domain rules
       |                         |
       |                         +---> repository/unit-of-work ports
       |                                      ^
       +-- composition root                    |
                                      SQLAlchemy adapters

startup/config ---> composition root ---> Discord + database + services
```

Dependencies point inward:

- **Domain** imports only the standard library and other domain modules. It defines value
  objects, entities, policies, calculations, invariants, and typed outcomes. It has no Discord,
  SQLAlchemy, environment, or wall-clock access.
- **Application** imports domain code and declares/uses narrow persistence, clock, random,
  content-catalog, authorization, and mutation-eligibility ports. Each public method represents
  a complete use case and owns its transaction, retry-idempotency, and business-uniqueness
  boundary.
- **Infrastructure** implements ports with async SQLAlchemy, SQLite/PostgreSQL-specific setup,
  content loaders, system clocks, random generators, logging, and operational integrations.
- **Discord application** parses interactions, defers/responds, invokes one application use
  case, maps typed results/errors to embeds or messages, and performs presentation-only
  permission checks. It never contains game formulas or coordinates repositories.
- **Composition/startup** constructs the database engine, unit of work, catalogs, services,
  and cogs; validates configuration and schema readiness; and disposes resources on shutdown.

Neither domain nor application code imports `discord.py`. SQLAlchemy models and sessions do
not leak into domain APIs or Discord cogs. Infrastructure may depend on application port
definitions and domain types; the inward layers never import infrastructure implementations.

## Use-case and transaction boundaries

A mutating use case is the unit of consistency. Examples include join, claim daily, transfer
coins, buy an item, complete one mining action, craft a recipe, equip an item, and accept a
trade. Each mutation:

1. accepts immutable primitive/value-object input plus actor, transport-idempotency, and
   domain-uniqueness context;
2. opens one unit of work;
3. loads only the aggregates it needs and evaluates central mutation eligibility inside the
   transaction;
4. guards the domain entitlement or expected aggregate revision independently of the transport
   key;
5. evaluates pure domain policy with injected time/randomness/content snapshots;
6. persists all state, ledger/audit records, any applicable durable action fact, and the
   recorded outcome;
7. commits once; and
8. returns a presentation-neutral result.

Queries such as `/balance` use read-only application services and presentation-neutral return
types. They do not claim mutation idempotency/domain keys, append facts, or create missing
state.

Repository methods flush when necessary but never commit, begin nested independent business
transactions, or call Discord. Multi-step state changes never rely on compensation as their
normal consistency mechanism. Durable out-of-process side effects, if introduced later, use
an outbox record written in the same transaction.

## Feature ownership

| Boundary | Owns | May expose |
| --- | --- | --- |
| Players | Global identity and lifecycle | Player identity/status |
| Safety/access | Global/player/account/inventory/trade/reward restrictions and durable capabilities | Mutation eligibility and authorization decisions |
| Economy | Monetary accounts, ledger, balances, limits, daily claim state | Debit/credit/transfer operations and history |
| Inventory/items | Holdings, instances, movement audit, equipment assignment | Reserve/add/remove/equip operations |
| Progression | Account/profession XP, mastery, prestige records | Eligibility and XP/milestone operations |
| Content | Versioned item, profession, drop, recipe, shop, quest definitions | Validated immutable snapshots |
| Commerce | NPC purchase/sale and eventually trade/escrow workflows | Quotes and atomic exchange operations |
| Goals | Quest, achievement, collection state and fact-consumption cursors | Progress/claim operations |
| Reporting | Leaderboards, economy summaries, support views | Read-only projections |

These are logical ownership boundaries and may initially share one database and transaction.
They are not microservices. A coordinating application service can call multiple domain
policies/repositories within its unit of work; one feature must not update another feature's
tables through ad hoc SQL.

### First-schema ownership boundary

The Phase 0 baseline keeps these ownership lines literal rather than placing future state on a
convenient player row:

- Players owns the global Discord identity, creation time, and minimal lifecycle state only.
- Economy owns the one initial wallet, monetary accounts, committed ledger, projections, and
  transport-idempotency persistence needed by the first money slices.
- Progression owns account XP/level as well as profession XP/state. No XP or level column belongs
  to the Phase 0 player record, and progression tables begin only with their named later slice.
- Safety/access owns restrictions, freezes, durable administrator capabilities, approvals, and
  access audit. Those tables begin with Slice 1.3, not the Phase 0 baseline.

Before Slice 1.3, `/join` has no player-specific durable restriction record to consult. Its
application contract still depends on a narrow join-eligibility policy: the production adapter
can reject all joins when mutations are globally disabled or startup/schema readiness is not
satisfied, while Slice 1.1 tests the allowed and globally-disabled outcomes with a fake. It must
not infer authority from Discord roles, create placeholder restriction rows, or add progression
state. After Slice 1.3, the same application boundary is backed by the durable central policy.

## Cross-system contracts

Common contracts should remain few and concrete:

- `Money`/coin amount and account identifiers for monetary changes;
- item references and integer quantities for inventory changes;
- `RewardBundle`/`CostBundle` values containing explicit coin, item, and XP components;
- actor, namespaced reason, correlation, transport idempotency, and domain uniqueness context;
- injected `Clock` and random source at the business-logic boundary; and
- a validated, versioned content snapshot used for one operation.

Bundles are inert typed data, never executable authority. The originating use case validates
every component against its allowed source/sink account, content budget, restriction scopes,
and owning domain policy before application orchestration applies it. A generic bundle cannot
grant an arbitrary currency, item, or profession XP merely because content requested it.

## Immutable action facts and goal consistency

Each qualifying gameplay use case writes an immutable, namespaced **action fact** in the same
database transaction as the state it describes. A fact has a stable UUID, fact type and schema
version, actor/player, committed-domain references, content version, UTC time, and the minimum
payload needed by known consumers. Facts describe committed truth; they do not execute rules.

Effects required for the originating command to be correct—its costs, immediate rewards, XP,
cooldown, and one-use state—are orchestrated before that transaction commits. Quests,
achievements, analytics, and rebuildable projections consume committed action facts after the
originating transaction. Their progress is intentionally eventually consistent. Each consumer
updates its state and records unique `(consumer_key, fact_id)` consumption in one transaction;
replay is safe and a crash cannot lose the durable fact. Reward claiming remains a separate
business-unique use case.

Initially, consumers poll the shared database by deterministic fact cursor; no broker or
generic event framework is required. If asynchronous delivery later leaves the process, an
outbox transports the same facts. Adding a goal must not require editing the mining or commerce
domain rule merely to call a new goal handler.

## Discord adapter rules

- Prefer application commands and Discord's default non-privileged intents unless a concrete
  feature needs otherwise.
- A cog owns command wording, input conversion, Discord authorization UX, deferral, embeds,
  pagination, and error presentation only.
- Use the Discord interaction ID, plus a stable operation suffix when necessary, as transport
  idempotency for a mutation. Application input also carries the use case's business one-use
  key or expected state revision; the adapter ID never substitutes for it.
- Defer before slow I/O and do not hold a database transaction while waiting for a follow-up
  click or modal submission. Each submitted interaction is a new use case.
- Domain/application exceptions are finite typed failures; cogs do not inspect database error
  strings.
- Discord member/role checks are advisory presentation checks. Durable administration
  capability is resolved by an application authorization port and recorded with the action.
- `/join` is the explicit player/account creation mutation. `/balance` is an ephemeral self-only
  pure query initially and never creates durable state.

## Time, randomness, and configuration

Domain services receive an aware UTC instant and a random interface or deterministic draw
sequence. They do not call `datetime.now()`, `random`, or Discord timestamps directly. Random
tables are versioned and tests can force boundary outcomes.

Secrets and deployment settings come from validated startup configuration. Game balance is
not mixed with secrets or arbitrary environment variables. Content and balance configuration
is schema-validated, versioned, reviewed, and captured by identifier on economic outcomes.

## Operational principles

- Structured logs include correlation, use-case, player/account references, content version,
  duration, and outcome without tokens or unnecessary personal data.
- Metrics cover use-case latency/failures, database contention/retries, idempotent replays,
  ledger reconciliation, and economic flows by reason.
- Startup verifies database connectivity and expected migration revision before accepting
  mutating commands. Shutdown stops new work, completes bounded in-flight work, and disposes
  the engine.
- Background jobs start in-process only if duplicate-safe and reconstructable from durable
  state. Time-critical or high-volume work requires a later durable worker decision.
- Economic mutations can be globally disabled or restricted during an incident while safe
  read operations remain available.
- Every mutating use case declares required currency, item, reward, progression, or trade
  capabilities and checks the central safety/access policy inside its transaction. Feature
  modules do not interpret a shared “frozen” flag independently.

## Package direction when implementation begins

The first vertical slices may introduce a concrete structure similar to:

```text
src/butterbot/
  domain/                 # pure rules grouped by feature
  application/            # use cases and ports grouped by feature
  infrastructure/         # SQLAlchemy, content, clock/random implementations
  discord_app/            # bot, cogs, views, presentation mapping
  bootstrap.py            # composition root
```

This is a direction, not a request to scaffold empty packages. Add a module when a slice owns
real behavior. Shared modules are extracted after at least two features demonstrate a stable
common concept.
