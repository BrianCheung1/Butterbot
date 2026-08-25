# Items and inventory

## Item model

An **item definition** describes a type of item; an **item holding** or **item instance**
describes player-owned state. Definitions use stable, human-readable keys that are never
reassigned. Display names may change without changing identity.

Every definition declares:

- kind: material, consumable, equipment, quest, collectible, cosmetic, or another approved
  closed category;
- rarity: a presentation and content-distribution tier, not an automatic power multiplier;
- stackability and maximum stack/quantity rules;
- trade, bind, sell, discard, consume, equip, and collection eligibility;
- optional base NPC values, equip slot, stat modifiers, use effects, or durability policy;
- content version and availability window where relevant; and
- tags used for curated recipes, drops, and collections.

Definitions are versioned game content loaded through an application-facing catalog. Stable
item identity and balance history are distinct: holdings use only the stable definition key,
while each operation records the catalog/balance version it applied. Fungible quantities from
different balance versions merge because they are the same item. Existing stockpiles use the
current rule when later sold, consumed, or crafted; a short-lived accepted quote pins its own
version. If old and new goods must retain different behavior, they receive different stable
item keys instead of hidden versioned stacks.

Tunable definitions may start as reviewed repository data; moving them to database-managed
content later must preserve validation, versioning, and historical explainability. Balance
changes are prospective and announced. A content migration is required only when ownership
state itself changes, not whenever a price or drop weight changes.

Rarity labels should communicate acquisition frequency and prestige. Recommended initial
tiers are common, uncommon, rare, epic, and legendary, but the names and count require human
approval. Code compares explicit rarity ranks only where a rule truly needs ordering; it does
not infer price, power, or tradeability from rarity.

## Hybrid ownership model

Stackable, fungible goods use holdings keyed by owner and item definition with an integer
quantity. Equipment and any object with unique state use individual instances with an opaque
identifier, definition key, owner, binding/custody state, durability/charges if applicable,
and creation provenance. An instance pins a historical behavior version only for an explicitly
approved legacy/immutable-item rule; current definitions apply by default.

An item should not become an instance merely because it is rare. Instance identity is
justified by mutable per-object state, uniqueness, or a need for provenance. This hybrid
avoids millions of identical ore rows without preventing future equipment state.

## Ownership, custody, reservation, and availability

Each player has one global inventory. Inventory is an ownership boundary, not a Discord UI
page. **Beneficial ownership**, **custody**, **reservation**, **equipment assignment**, and
**binding** are separate concepts:

- beneficial owner answers whose asset it is;
- custody is `inventory` or an explicit feature escrow/custodian;
- reservations prevent a quantity or instance from being used by another operation;
- equipment is an assignment while custody remains `inventory`; and
- binding limits permitted future owners but does not move the item.

Canonical invariants are:

- quantities are non-negative integers and zero-quantity holdings are absent;
- one fungible holding exists per player and definition;
- a fungible holding's available quantity is `total - active durable reservations`, never
  negative; reservation rows have stable purpose IDs and cannot overbook;
- each instance has exactly one beneficial owner and one custody state;
- each durable reservation/escrow purpose is business-unique and has an expected revision;
- equipped, reserved, locked, or escrow-custody assets are unavailable to sale, crafting,
  donation, discard, or another reservation;
- bound assets cannot change beneficial owner, even when otherwise available;
- removal verifies availability inside the transaction and never partially succeeds; and
- multi-item exchanges apply all removals and additions atomically.

| State | Custody | Equipped | Reserved/locked | Available operations |
| --- | --- | --- | --- | --- |
| Available | Inventory | No | No | Consume, sell, donate, equip, or reserve if definition allows |
| Equipped | Inventory | Yes | No | Unequip or approved equipment use only |
| Reserved | Inventory | No | Yes | Complete or cancel the owning workflow only |
| Escrowed | Escrow | No | Purpose-owned | Settle, expire, or cancel the owning workflow only |
| Locked | Either | No | Administrative/system lock | Explicit corrective/release workflow only |

State transitions use guarded revisions inside the owning use case. Phase 2.1 establishes this
model before sale, equipment, crafting, or collection code. Trading later adds escrow purposes
and settlement transitions; it does not invent a second availability model.

The initial inventory should use stack/quantity limits only where they create a meaningful
choice or protect operations. A universal small slot cap would make Discord inventory
management tedious and is not proposed. Query pagination and display grouping are adapter
concerns, not inventory rules.

Current holdings/instances are authoritative state. A complete immutable movement journal is
the audit and reconciliation trail: it records every creation, destruction, quantity delta,
beneficial-owner or custody change, durable reservation/release, equipment transition,
binding/lock change, and administrative correction with before/after references, reason,
actor, transaction correlation, business key, content version, and UTC time. Ephemeral
in-transaction calculations that never persist need no separate movement. A mismatch freezes
affected item mutations; the journal is not silently edited to fit current state. Currency
uses the monetary ledger, never the item journal.

## Equipment

Equipment is a view of owned instances assigned to stable slot keys. Equipping validates
ownership, item kind, slot compatibility, binding, profession/level requirements, and player
status. Swapping and any bind-on-equip transition are atomic. An equipped item remains in the
player's inventory but is unavailable for trade, sale, crafting, collection donation, or
discard.

Effective stats are derived from the current definition plus instance state and the progression
rules in `progression.md`. Persist the equipment assignment, not duplicated aggregate stats.
An explicitly version-pinned legacy instance is the exception and must display that fact.

Durability is not required for the first equipment slice. If adopted, normal use reduces an
integer charge count, zero durability disables bonuses rather than destroys the item, and
repair is a transparent currency/material sink. Permanent item breakage requires a separate
human-approved decision.

## Item operations

Buying, selling, crafting, consuming, equipping, donating, and trading are application use
cases. Each coordinates inventory with its other aggregates in one transaction and carries a
transport idempotency key plus a business purpose/revision that prevents double-use. Item
effects return typed domain changes; definitions do not execute database writes or Discord
callbacks.

Administrative item grants/removals require operator identity, reason, provenance, and the
same audit discipline as currency administration. Removing an unavailable or equipped asset
fails unless a dedicated correction workflow explicitly describes the state repair.

## Content safety checks

Before an item or recipe ships, validate stable keys, references, quantities, integer bounds,
trade/bind combinations, equip slots, stat caps, drop availability, NPC prices, collection
behavior, and crafting graph cycles. Repository tests should load the complete content catalog
and reject missing references or any deterministic positive-value arbitrage path.
