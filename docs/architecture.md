# Architecture

## Current repository state

Slice 1.0 now provides the first Alembic baseline, async SQLAlchemy/SQLite runtime, explicit unit
of work, schema readiness and process-lock checks, Operations transport-idempotency coordinator
and repository, global mutation eligibility adapter, structured operational telemetry, and a
composition root. Provisional Slice 1.1 adds an application-owned join transaction and a private
`/join` adapter alongside `/ping`. Provisional Slice 1.2 adds the private, self-only `/balance`
query with a deferred transaction snapshot and no writes. There is no economic-value creation, progression,
inventory, or banking. Provisional Slice 1.3 adds durable capabilities, audited inspection,
proposals and central full freezes. Local safety policy is approved; native acceptance remains pending.

The package direction below remains incremental: only the concrete boundaries needed by Slice
1.0 and local Slice 1.1 exist, and later feature packages are not pre-scaffolded.

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
  boundary. A shared Operations/application-support coordinator owns transport claim/replay and
  fingerprint-conflict behavior; domain services retain their own business-uniqueness rules.
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

The Slice 1.0 SQLAlchemy unit of work acquires SQLite's writer lock at its application boundary,
constructs all repositories over one async session, verifies that no transport claim remains
unfinished, and commits once on successful exit. Exceptions roll the session back. The retry
runner recreates the complete unit of work only for busy/locked errors, with the accepted
25/75 ms backoff, at most two retries, and a three-second generic database budget. Its
application-facing factory receives only attempt/budget context; the concrete SQLite factory
alone selects the per-attempt busy timeout. Waiting for one of the four writer slots consumes the
same remaining attempt budget; timeout is a retry-budget outcome, and SQLite's busy timeout is
recomputed after admission from the budget actually left. The unit of work also owns synchronous post-commit
callbacks used for commit-accurate operational events; rollback discards them. Immediately before
commit, SQLite infrastructure revalidates both the configured pathname identity and the open
connection's `PRAGMA database_list` identity. It confirms identity again after durable commit;
a breach or inability to complete the required post-commit confirmation marks mutation safety
false without changing the successful commit result. Transaction completion then runs in one shielded
helper task so cancellation cannot interrupt commit, rollback, or resource cleanup. Cancellation
observed before completion begins causes a confirmed rollback and is propagated. Once completion
begins, the owner waits for a definitive commit/rollback result; a confirmed commit runs every
post-commit callback exactly once and returns the already-produced application result, suppressing
that cancellation so durable success is never reported as cancellation. Callback failures are
logged and do not skip later callbacks or change the committed result. Once commit is confirmed,
later session/connection cleanup failure is reported separately, makes runtime mutation safety
false, and cannot rewrite the committed result. A session or connection reference is cleared only
after its own close succeeds. Failed resources move from active-owner tracking to a runtime-owned
unresolved set; shutdown retries that exact set and cannot dispose the engine or release process
ownership until every retained resource is unusable.

Runtime lifecycle ownership maps every active unit of work to its owning asyncio task. Shutdown
stops admission before asynchronous cleanup begins and retains the captured owners even after a
unit of work exits. Transaction phases distinguish active work from commit already in progress.
At drain expiry the lifecycle requests rollback and cancels only owners whose commits have not
begun; it awaits all captured owners without operating their sessions from another task. If an
owner exceeds the bounded cleanup window, shutdown fails stopped with engine and process
ownership intact. The original owner capture and any still-running monitor-close task survive a
shutdown retry; a retry cannot replace them with a smaller capture or duplicate cleanup. Disposal
and ownership release follow only after every captured owner and required monitor-close task
finishes and the retained unresolved-resource set drains successfully. A failed or timed-out
resource retry fails stopped and remains available to a later shutdown retry. Shutdown cleanup
itself is shielded from caller cancellation. Storage-monitor
shutdown and transaction drain begin concurrently; either component failing or exceeding its
bound, or engine disposal failing, retains process ownership and surfaces `ShutdownIncomplete`.

Operational telemetry is observational. Each sink call has its own non-throwing boundary, so a
sink failure cannot replace replay/conflict/rejection results, retry behavior, commit/rollback, or
cleanup semantics. Mutation-safety transitions are queued independently of current safety state
and drained in order; a failed unsafe emission followed by recovery still emits unsafe then safe
before normal state-change deduplication resumes.

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
| Operations/application support | Transport-idempotency outcomes, action facts, cross-cutting operational audit | Request replay/retention and operational contracts |
| Reporting | Leaderboards, economy summaries, support views | Read-only projections |

These are logical ownership boundaries and may initially share one database and transaction.
They are not microservices. A coordinating application service can call multiple domain
policies/repositories within its unit of work; one feature must not update another feature's
tables through ad hoc SQL.

### First-schema ownership boundary

The first production baseline authorized after Phase 0 keeps these ownership lines literal
rather than placing future state on a convenient player row:

- Players owns the global Discord identity, creation time, and minimal lifecycle state only.
- Economy owns the one initial wallet, monetary accounts, committed ledger, and projections.
- Operations/application support owns the shared transport-idempotency persistence and
  repository used by `/join` and all future mutating domains. The application coordinator uses
  it inside the caller's unit of work; Economy does not write it through an Economy repository.
- Progression owns account XP/level as well as profession XP/state. No XP or level column belongs
  to the Phase 0 player record, and progression tables begin only with their named later slice.
- Safety/access owns restrictions, freezes, durable administrator capabilities, approvals, and
  access audit. Those tables begin with Slice 1.3, not the first baseline.

Before Slice 1.3, `/join` has no player-specific durable restriction record to consult. Its
application contract still depends on a narrow join-eligibility policy: the production adapter
can reject all joins when mutations are globally disabled or startup/schema readiness is not
satisfied, while Slice 1.1 tests the allowed and globally-disabled outcomes with a fake. It must
not infer authority from Discord roles, create placeholder restriction rows, or add progression
state. After Slice 1.3, the same application boundary is backed by the durable central policy.

The join service uses the transaction runner and `players.join` transport namespace. A new
eligible request creates or retrieves the player and complete zero-initialized wallet; returning
joins preserve balances and do not repair missing state. Existing non-active identities are not
reactivated. Typed rejections persist only Operations bookkeeping. Replays return the recorded
fixed outcome without reexecuting eligibility or aggregate mutation. Outcome payloads are exactly
empty objects. Discord defers privately before invoking the service and sends the private result
only after transaction completion; response failure cannot roll back a committed join.

The separate interactive development entry point constructs this same service over a fresh
disposable database. A dedicated development bot restricts command execution to one tester and
one guild before invoking the service. Normal configuration/composition remains fail-closed;
the development launcher never consumes a production database path or synchronizes global commands.

### Shared transport idempotency

Transport idempotency is application execution support, not Discord presentation, game-domain
policy, or database-only behavior. A transport adapter supplies an opaque request key. The
application coordinator selects the stable use-case namespace, fingerprints actor plus canonical
semantic input, claims the request through the Operations repository in the use case's unit of
work, and records the stable applied or typed-rejection outcome before commit. Infrastructure
implements the repository and cleanup mechanism; it does not decide replay semantics.

The logical uniqueness key is `(namespace, transport_key)`. Namespaces are stable lowercase
dotted operation names and do not change with releases or balance versions. Same key and
fingerprint replays the recorded result; a different fingerprint conflicts. Completed initial
Discord mutation outcomes are retained for seven days, with longer namespace-specific periods
required for transports that can legitimately redeliver later. Operations owns incremental
expiry, storage metrics, and the retention registry. Queries create no records.

This facility can be reused by Players, Economy, Inventory, Progression, Safety/access, and
future domains. It never replaces their business one-use key or expected revision: the owning
domain persists that protection independently and for the entitlement's required lifetime.

The Operations table permits an outcome-less row only while its owning database transaction is
open. The SQLAlchemy unit of work refuses to commit such a row. Successful and typed-rejection
outcomes are canonical JSON objects with stable codes. Application persistence accepts only the
exact JSON value model it can replay without type changes, rejects non-finite numbers, and stores a
detached canonical form. The offline verifier and replay reject duplicate keys, non-finite decoded values, and
non-canonical or otherwise malformed stored representations. Unexpected failures roll back the claim.
Permanent ledger/audit rows may retain an opaque request reference but do not foreign-key their
lifetime to the seven-day transport record.

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

- The production topology and operational acceptance gates are defined in `operations.md`:
  one Linux host, one bot process/economic writer, persistent local SQLite storage, off-host
  backups, and no shared or ephemeral database volume.
- Structured logs include correlation, use-case, player/account references, content version,
  duration, and outcome without tokens or unnecessary personal data.
- Metrics cover use-case latency/failures, database contention/retries, idempotent replays,
  ledger reconciliation, and economic flows by reason.
- Production startup opens an existing database without creating or migrating it and verifies
  required SQLite pragmas, the exclusive process lock, the exact expected migration revision,
  bounded transport state, and the indexed aggregate-completeness sentinel before connecting the
  normal command surface. Exhaustive integrity, foreign-key, and history/canonical checks run in
  the stopped-service streaming verifier. Missing, behind,
  ahead, unknown, or incompatible schema state exits non-zero.
- The deployment-owned global mutation setting defaults to disabled. Until Slice 1.3 it is the
  application-level policy for all durable mutations, including `/join`; it is not a Discord
  role and creates no player restriction rows. Enabling requires schema/runtime readiness,
  backup/restore readiness, alerting, and accepted deployment-host benchmark evidence.
- Shutdown stops new unit-of-work admission, gives captured owners a bounded ten-second drain,
  cancels only pre-commit owners so their own contexts roll back, and awaits commit-racing owners.
  A stuck owner fails stopped with process ownership retained. Restart repeats every readiness
  check and preserves WAL sidecars as database state.
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
