# Economy design

## Economic objectives and initial scope

Butterbot begins with one global soft currency, called **coins**, at one stored unit per
displayed coin. Additional currencies require a separate purpose that cannot be served by an
item, reputation, progress counter, or bound token.

The initial account model contains one wallet per joined player and no bank account. A bank is
still an intended player feature, but it will not create empty rows or policy ambiguity before
its benefit, restrictions, limits, and treatment by wealth rules are approved. Adding it later
is an additive account kind and application use case, not a reason to weaken the initial
ledger.

## Money representation

- Store postings and account projections as signed 64-bit integers. Player/custody balances
  are constrained to non-negative values.
- Floating-point and binary fractions are forbidden for money. Formatting is presentation
  logic.
- Arithmetic checks bounds before persistence. Overflow, underflow, zero-value postings, and a
  negative custody balance reject the whole operation.
- Rates use integer basis points or explicit integer ratios with a documented rounding rule.
  The default is round down; minimum fees must be explicit.
- Item quantities are also integers but use different domain types and cannot enter the money
  ledger.

The immutable committed ledger is the audit truth. Every monetary account also has a current
balance projection updated in the same transaction for fast guarded mutations. Reconciliation
compares the projection with postings; a mismatch freezes affected mutations and triggers an
incident workflow rather than rewriting committed history.

## Chart of accounts and posting convention

A positive posting increases an account's projected balance and a negative posting decreases
it. Every committed transaction has at least two non-zero postings whose signed amounts sum
to zero.

| Account class | Initial use | Normal balance | Constraint |
| --- | --- | --- | --- |
| Player wallet | Coins beneficially owned and available to a player | Positive | `>= 0`; exactly one per joined player |
| Escrow custody | Coins reserved for an accepted future workflow | Positive | `>= 0`; absent until escrow exists |
| System issuance | Counter-account for a named faucet/reason | Negative | `<= 0`; never spendable |
| System retirement | Counter-account for a named sink/reason | Positive | `>= 0`; never spendable |
| Operational custody | Temporary system custody that remains in supply | Positive | `>= 0`; requires a feature ADR before use |

System accounts are namespaced by stable reason, such as `issuance.daily` or
`retirement.shop_purchase`; they are not a general administrator wallet. All account classes
maintain balance projections. Corrections preserve normal polarity by using dedicated
issuance/retirement correction accounts rather than reversing a source or sink account past
its allowed sign.

Examples:

```text
mint X:       issuance.daily -X, player.wallet +X
destroy X:    player.wallet -X, retirement.shop_purchase +X
transfer X:   sender.wallet -X, recipient.wallet +X
reserve X:    player.wallet -X, escrow.trade +X
```

The initial schema persists only committed ledger transactions. Pending approval, trade, and
job lifecycles belong to their own workflow records; ledger `status` is not added until an
accounting use case genuinely requires it.

## Supply and wealth definitions

Reports use these formulas; summing every ledger account is never a supply calculation because
balanced accounting always sums to zero.

- **Cumulative minted value** = the negated sum of all issuance-account balances.
- **Cumulative destroyed value** = the sum of all retirement-account balances.
- **Total outstanding supply** = minted value minus destroyed value. It must equal the sum of
  all positive custody accounts: player wallets, escrow, and any approved operational custody.
- **Escrowed supply** = sum of escrow-custody balances.
- **Restricted supply** = beneficial player wealth whose relevant mutation capability is
  currently frozen. Restrictions do not destroy coins.
- **Circulating supply** = total outstanding supply minus escrowed supply, restricted supply,
  and operational custody unavailable to players.
- **Player wealth** = that player's wallet plus currency held for their benefit in escrow.
  The initial value is just wallet balance because escrow is not yet present.
- **Available balance** = the player's wallet balance that passes restriction and guarded-spend
  checks. It is not a separate stored balance.

If a bank is introduced, its ADR must classify bank balances in each formula and state whether
fees, limits, affordability, leaderboards, grants, and sanctions use available balance or total
player wealth. No feature may invent a local meaning of “balance” or “wealth.”

## Ledger transaction record

A committed monetary transaction has an immutable UUID, transaction kind, committed UTC
instant, actor, namespaced reason code, request correlation, transport idempotency key, domain
uniqueness reference, optional originating Discord interaction, content/balance version where
relevant, and postings. The public transaction history is a safe projection that shows time,
kind, counterparty where appropriate, signed player amount, resulting balance, reason, and a
stable reference while hiding internal accounts and sensitive operator metadata.

Stable reason codes come from a validated namespaced registry owned by the economy boundary.
Content tags may select data but never implicitly choose a source account or execute a rule.

## Transaction and uniqueness rules

All commands and jobs that change value follow these invariants:

1. The application service opens one database transaction for the complete use case.
2. It claims a **transport idempotency key** and request fingerprint. Replaying the same request
   returns the recorded result; reusing a key for different input fails.
3. It also enforces **business uniqueness** inside the transaction through a unique domain key
   or expected state revision. A different interaction cannot consume the same entitlement.
4. It evaluates the central mutation-eligibility policy and validates limits, balances,
   content eligibility, integer bounds, and any item/progression state.
5. It records balanced postings, balance projections, domain one-use state, audits, and related
   item/progression changes atomically.
6. It commits once and returns a presentation-neutral result. A Discord response failure does
   not authorize a new economic identity for the same entitlement.
7. Transient SQLite contention may retry within the approved time/attempt budget using the same
   transport and domain keys. Rule failures are never retried.

Examples of domain uniqueness are `(player, daily_period)`, `(campaign, target)`, one-time
onboarding eligibility, a consumed quote UUID, an expected trade version, a profession
opportunity/cooldown revision, and a prestige epoch. Discord interaction IDs alone are never
sufficient protection against double-spend.

Repositories never commit. No cog, scheduled job, content definition, reward bundle, or
administrator utility writes balances directly.

## Join and balance semantics

- `/join` is an explicit mutation. It creates one global player and wallet atomically using the
  Discord user ID as the domain uniqueness key plus the interaction ID for retry idempotency.
  Competing joins converge on one player/wallet and return the existing successful result.
- `/balance` is a pure query. It never creates a player or account. An unjoined user receives a
  presentation-level invitation to join.
- Self-balance responses are ephemeral by default. Public wealth lookup is not part of the
  initial command. Support inspection uses a durable capability and produces an access audit.
- Reads remain available during an economic mutation freeze unless a privacy or support
  restriction explicitly blocks them.

## Central mutation-eligibility policy

The safety/access boundary owns durable restrictions; individual feature tables do not invent
their own freeze flags. Every value-changing application use case declares the capabilities it
needs and evaluates them inside its transaction:

- currency debit or receipt;
- item removal or receipt;
- system reward receipt;
- progression gain;
- trade/escrow participation; and
- administrator correction bypass.

Restrictions may be global, player-wide, monetary-account, inventory, trade, or reward scope.
A full player economic freeze blocks discretionary currency/item changes, profession rewards,
XP, claims, NPC commerce, transfers, crafting, and trade in both directions. Reads and safe
escrow cancellation/release remain possible. An authorized correction may bypass a freeze only
with an explicit reason and audit. Narrow restrictions must name their allowed and blocked
capabilities; “frozen” never has feature-local semantics.

## Transfers and abuse controls

- Transfer amount is positive, sender differs from recipient, and both are eligible joined
  players.
- Debit, credit, fee if approved, rolling-limit usage, business uniqueness, and both histories
  are atomic.
- Transfer settlement and future trade settlement use the same player-to-player value-movement
  policy for restrictions, eligibility, limits, and suspicious-flow telemetry.
- Transfer availability is gated by minimum account age and approved progression rather than
  Discord identity alone. Per-operation and rolling inbound/outbound limits are mandatory.
- Telemetry measures system rewards received, P2P inflow/outflow, repeated counterparties,
  funnel patterns, coordinated accounts, and limit pressure. It feeds alerts and manual review;
  it does not claim to prove that one Discord account equals one human.
- Sanctions and appeal/manual-review rules must be approved before transfers ship.

Butterbot does not attempt invasive device fingerprinting or coin-by-coin provenance. Coins
remain fungible. Initial onboarding therefore grants no transferable coins; it may grant bound
starter items or progression access. Valuable repeatable faucets do not ship before the abuse
controls above have operational owners.

## Daily rewards

- Eligibility uses an injected UTC clock and a unique `(player, claim_period)` entitlement,
  not transport idempotency or local calendar parsing.
- Claim state, reward issuance, ledger transaction, and recorded result commit together.
- The approved balance envelope sets the base reward relative to normal play. It does not
  compound without bound.
- A grace-based consistency track may add capped non-currency or small rewards; missing a day
  never destroys prior progress.

## Economy administration

Administrative use cases are typed and capability-gated: inspect, grant, bounded remove,
freeze/unfreeze, approve, and correct. Durable capabilities are independent of Discord guild
roles; role checks may improve presentation but are not economic authorization.

Every operation records operator, target, reason, amount, transport key, business key, and
before/after reference. Per-operation and rolling grant ceilings are required. A grant above
the approved threshold, any bulk campaign, or a policy-changing correction requires approval
from a second distinct authorized operator before execution. The requester cannot approve
their own action. Bulk work supports a dry run and enforces `(campaign, target)` uniqueness.
Alerts cover threshold use, repeated targets, unusual operator activity, and freeze bypasses.
Committed history is corrected with compensating transactions, never edited.

Exact monetary ceilings and bootstrap operators are deployment policy that must be approved
before the administrator-grant slice, but the first schema/application contract must support
capabilities, proposal/approval identity, and immutable audit.

## Currency sources

Each source has a separate issuance reason and telemetry:

| Source | Role | Primary controls |
| --- | --- | --- |
| Daily reward | Welcome-back cadence | Business-period uniqueness, modest amount, approved balance envelope |
| Profession/NPC-sale rewards | Main active faucet | Expected-value table, action limits, sink pairing, abuse telemetry |
| Quests | Directed play and catch-up | Limited availability, objective fact, reward budget |
| Rare coin rewards | Excitement | Low frequency, bounded payout, deterministic fallback if progression-required |
| Achievements/collections | Milestone celebration | One-time domain key, mainly item/status rewards at high tiers |
| Administrative grant | Recovery/event operations | Durable capability, ceilings, approval, campaign uniqueness, audit |

Player transfers and player trades redistribute value and are not sources. Selling an item to
another player is not a source; selling to an NPC is.

## Currency sinks and faucet release gate

Sinks buy useful choice, convenience, expression, risk management, or progress rather than
punish ordinary participation.

| Sink | Cadence | Design purpose |
| --- | --- | --- |
| NPC item/tool/consumable purchases | Frequent | Baseline access and activity-scaled demand |
| Crafting and recipe costs | Frequent to medium | Scale coin demand with item production |
| Tool repair or charge renewal | Frequent if selected | Activity-scaled maintenance with non-destructive failure |
| Equipment upgrades | Medium | Optimization and material co-sink |
| Trading/listing fees | Later, only if approved | Activity-linked drain and anti-spam control |
| Collection donations | Medium | Voluntary completion/status sink |
| Cosmetics and profile upgrades | Medium to aspirational | Non-power stockpile sink |
| Prestige projects | Rare, aspirational | Late-game stockpile sink with explicit retained value |
| Event/community projects | Periodic | Population-scaled optional sink |

Escrow and player-to-player movement are not sinks. Item destruction is only a currency sink
when coins are also retired.

Before repeatable NPC selling becomes publicly available, the approved balance model must
select at least one desirable recurring sink whose expected demand scales with profession
activity. That sink must be implemented, measured, and included in the Phase 2 source/sink and
stockpile simulation. Durability is one option, not a predetermined answer. A finite starter
shop or optional cosmetic alone does not satisfy this gate.

## Inflation protections and balance envelope

- Track total, circulating, escrowed, and restricted supply using the formulas above; minted
  and destroyed flow by reason; balance percentiles; concentration; velocity; affordability;
  item stockpiles; and cohort progression time.
- Define an initial source/sink and progression envelope before public faucets, then revise
  targets from observed cohorts. Never react to a single day or silently personalize prices.
- Version reward/price tables with effective times and capture the applied version on outcomes.
- Cap or diminish the highest-rate faucets while keeping short casual sessions useful.
- Keep permanent yield bonuses small, additive, capped, and fully budgeted.
- Preserve old-material demand through consumption, collections, and recipes.
- Test shop/crafting graphs for deterministic positive-value cycles.
- Prefer prospective tuning and compensating transactions. Revoking fairly earned value
  requires explicit incident approval.

The initial balance worksheet covers casual, regular, and optimized cohorts; actions per day;
commands and elapsed time per milestone; source/sink expected value and variance; content tiers
and unlock spacing; multiplier budgets; expected coin/item stockpiles; and alternate-account
sensitivity. Reference gameplay slices remain non-production until their daily and weekly
choices, recurring sink, and cohort simulations pass their integration gate. A full years-long
content catalog is not required before `/join` or `/balance`, but the first playable loop must
fit a credible extensible envelope before launch.

No automated dynamic pricing, wealth tax, bank interest, or additional currency is part of the
initial design.

## Economic release checklist

For every feature, document its source/sink classification, chart accounts, business one-use
key, transferability, stockpiles, limits, expected value/variance, progression prerequisites,
multiplier interaction, restriction capabilities, abuse model, metrics, content version,
tuning owner, and remediation plan. A release is incomplete without reporting that attributes
its flows and a test proving transport replay plus domain double-use cannot duplicate value.
