# Independent economy design review resolution

Date: 2026-08-25

This record evaluates the independent review against Butterbot's intended architecture. It is
not an instruction log: each finding is accepted, modified, or rejected based on correctness,
scope, and the cost of the proposed remedy.

## Preserved foundations

The review explicitly endorsed, and this resolution preserves, inward dependency direction;
presentation-free domain/application rules; one application-owned transaction per use case;
repositories that never commit; integer money and quantities; balanced immutable monetary
postings plus current projections; injected time/randomness; hybrid item ownership; delayed
trading/marketplace; bounded additive economic modifiers; explicit profession-specific
prestige; distinct farming semantics; vertical slices and integration gates; backend-specific
locking behind stable application semantics; and simulation plus production telemetry.

## Critical finding

### C1 — Schema-defining decisions remained unapproved: accepted

The finding is valid. “Proposed” global identity, account, item, identifier, and time choices
could not safely support a first migration. `decisions.md` now accepts a global player/economy,
wallet-only first account model, explicit chart/supply rules, UUIDv4 identifiers, integer
Discord snowflakes, epoch-millisecond instants, explicit `/join`, pure private `/balance`, dual
duplicate protection, central restrictions, and the hybrid item model. The bank is removed
from the first schema. Phase 0 still requires empirical balance/load evidence and operational
inputs before the Alembic baseline; those are measurements/configuration, not ambiguous schema
ownership.

## High findings

### H1 — Missing chart of accounts and supply formulas: accepted

The review identified a direct reconciliation flaw. `economy-design.md` now defines posting
sign, normal polarity and constraints for wallet, escrow, issuance, retirement, and future
operational custody; all accounts keep projections. It gives exact definitions for minted,
destroyed, total outstanding, escrowed, restricted, circulating, player wealth, and available
balance. Summing every account is explicitly invalid as a supply report.

### H2 — Bank had no approved purpose: accepted with scope modification

The initial bank is removed rather than given arbitrary rules merely to satisfy an eventual
feature list. This avoids a second balance, limit bypasses, and first-schema complexity. The
recommendation is not interpreted as deleting the bank forever: Roadmap Slice 3.5 requires a
purposeful bank ADR and treats its account kind as an additive feature.

### H3 — Repeatable faucets preceded a scalable recurring sink: accepted

The sequencing problem is valid. Phase 0 must select an activity-scaled sink in the balance
model; Slice 2.5 implements it; NPC selling moves to Slice 2.6 and cannot become public first.
The architecture does not prematurely mandate durability—the selected sink may instead be
supplies, repeat crafting demand, or an access cost if simulation shows a better player choice.

### H4 — No numerical/content envelope for long progression: partially accepted

The first playable loop cannot responsibly launch without cohort pacing, expected values,
stockpiles, multiplier budgets, and daily/weekly choices. These are now Phase 0 balance-model
inputs and a Phase 2 public-release gate. The stronger implication that a complete years-long
catalog must block `/join` or a private `/balance` query is rejected: those commands establish
identity/read plumbing and do not grant repeatable value. Exact later content is refined before
its faucet ships.

### H5 — Alternate-account and automation defenses arrived too late: partially accepted

Transfer gates, account-age/progression requirements, rolling P2P limits, funnel/counterparty
telemetry, sanctions, alerts, and manual review now gate transfers and valuable faucets.
Initial onboarding grants no transferable coins. The design deliberately does not claim
one-Discord-account-per-human, add invasive device fingerprinting, or track provenance through
individual fungible coins. Source and flow aggregates provide useful signals without turning
the ledger into costly coin tracing.

### H6 — Transport idempotency was confused with business uniqueness: accepted

This is a fundamental correctness finding. Every mutation now requires transport idempotency
plus a domain entitlement key or expected revision. Examples and database constraints are
explicit, and test gates require attempts with distinct interaction IDs against the same
business fact.

### H7 — Goal progress transaction semantics contradicted each other: accepted

The design now chooses one contract. The originating use case applies required costs, rewards,
XP, and one-use state before commit and appends an immutable action fact in that transaction.
Goals/analytics consume committed facts eventually with unique `(consumer_key, fact_id)`
receipts. Claims are separate business-unique mutations. This is durable without coupling
mining to every future goal or introducing a message broker prematurely.

### H8 — Canonical item availability came after dependent systems: accepted

Slice 2.1 now owns beneficial ownership, custody, durable reservations, equipment assignment,
binding, locks, available stack quantity, state revisions, and a transition matrix. Equipment
remains inventory custody rather than a contradictory second location. Trade later extends
this model with escrow purposes.

### H9 — SQLite capacity was qualitative: accepted with staged evidence

Database settings, retry budget, latency/retry acceptance envelope, load multipliers, and
measurable PostgreSQL triggers are now explicit. Phase 0 benchmarks disposable player/ledger
writes before the baseline migration. A second gate benchmarks the actual full mining
transaction before public gameplay. A full mining transaction cannot honestly be benchmarked
before its schema/use case exists, so the review's goal is split into an early architecture
spike and a representative pre-release gate.

### H10 — Player-facing coin-only trade duplicated transfers: accepted

The coin-only offer slice is removed. Coin escrow remains an internal settlement primitive;
the first public trade is item-for-coin and routes all coin movement through the same P2P
eligibility, limit, fee, restriction, and suspicious-flow policy as transfers.

### H11 — Economic restriction ownership was ambiguous: accepted

A safety/access boundary now owns durable restrictions and capabilities. Mutating use cases
declare currency, item, reward, progression, and trade capabilities and check centrally inside
their transaction. Full and narrow restriction behavior, correction bypass, safe escrow
release, and reads are defined rather than left to feature-local interpretation.

## Medium findings

| Finding | Resolution |
| --- | --- |
| M1 content identity versus balance history | Accepted for Slice 2.1. Fungible holdings merge by stable key; operations record applied versions; new behavior identity requires a new key. |
| M2 curve/mastery/prestige exploitation | Immediate rule: no undefined post-cap XP. Curve migration, respec, epochs, retained assets, stockpiles, and reward caps gate mastery/prestige slices. |
| M3 RNG tails | Required random progression receives a deterministic fallback before the rare-drop/collection slice; pure cosmetics may remain unbounded. |
| M4 item movement authority | Current state is authoritative; the immutable journal is complete audit/reconciliation for every persistent delta and state transition. Established in Slice 2.1. |
| M5 administrator security | Accepted before grants: durable capabilities, ceilings, two-person approval, campaign uniqueness, alerts, freeze/correction drill. Numeric policy remains a Phase 1.3 input. |
| M6 reporting pressure | Accepted for reporting: incremental indexed projections, query budgets, snapshot rebuilds, and a PostgreSQL trigger. |
| M7 `/balance` privacy/creation | Accepted: explicit `/join`; pure ephemeral self-only `/balance`; audited capability for support lookup. |
| M8 RewardBundle authority | Accepted: bundles remain inert data and each component is validated against originating policy, accounts, restrictions, and content budget. |

The later-stage parts of M2, M3, and M6 are roadmap gates rather than premature framework or
schema work.

## Low findings incorporated because they affect early correctness

- **L1:** The initial ledger stores committed transactions only. Pending workflow state belongs
  to proposals, offers, or jobs, not a speculative ledger status.
- **L2:** Reason codes and fact/stat/content keys use validated namespaced registries. Tags aid
  content selection and cannot execute economic rules.

## Rejected recommendations or interpretations

No Critical or High finding is rejected in full. The following over-broad interpretations are
rejected:

- H2 does not justify removing the bank permanently; it just cannot enter the first schema
  without a purpose.
- H4 does not require final multi-year content numbers before identity and private read slices.
- H5 does not justify invasive identity linkage or coin-by-coin provenance.
- H9 does not pretend to benchmark the final mining transaction before it exists; it requires
  an early disposable storage spike and a later representative pre-release benchmark.

## Readiness conclusion

The architecture now has explicit first-schema semantics, but the repository is not yet ready
to jump directly to `/balance`: Phase 0 must record the balance envelope, disposable SQLite
load result, operational inputs, and then create/verify the baseline persistence slice. Once
Phase 0 is complete, the exact next implementation slice is **Slice 1.1: explicit `/join`**;
**Slice 1.2: pure private `/balance`** follows it.
