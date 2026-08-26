# Game design

## Product promise

Butterbot is a persistent, cooperative-first Discord economy game in which a useful action
fits into a short chat session while collections, professions, equipment, achievements, and
prestige provide goals measured in months or years. Players should always be able to answer:

- what they can do now;
- what they are working toward;
- why a reward was granted; and
- what trade-off they made by spending or consuming something.

The game is not intended to reward being online continuously. Consistent casual play should
make visible progress, while highly engaged players gain breadth, optimization opportunities,
trade knowledge, collection progress, and prestige rather than uncapped exponential power.

## Overall gameplay loop

The core loop is:

1. **Choose an activity.** Gather through a profession, complete a quest, trade, or maintain
   a collection.
2. **Resolve a bounded action.** Spend time, a tool use, a consumable, or an opportunity and
   receive a fully explained outcome. Randomness changes the outcome, not whether the command
   safely completes.
3. **Convert the outcome.** Keep materials, sell them, trade them, craft with them, or donate
   them to a collection.
4. **Improve capability.** Gain account or profession XP, upgrade equipment, unlock recipes
   and locations, or specialize through mastery.
5. **Pursue a longer goal.** Complete a collection, achievement, equipment set, difficult
   recipe, mastery track, or prestige objective.
6. **Re-enter with more choices.** New options should broaden strategy without making old
   content worthless.

Mining should be the reference profession for the first playable loop because its outputs
exercise inventory, item rarity, selling, equipment, random drops, and profession progression
without needing a simulation of crops or timed catches. Fishing and farming should reuse
shared concepts only after mining proves which concepts are genuinely common.

## Session and horizon design

| Horizon | Player experience | Typical goals |
| --- | --- | --- |
| One to five minutes | Claim, gather, inspect, sell, equip | A useful result in one interaction |
| One day | A small set of choices with optional repeat play | Daily reward, quest, recipe input |
| One to four weeks | A coherent build or content tier | Profession milestone, equipment set |
| Several months | Specialization and completion | Mastery branch, collection, prestige prep |
| Multiple years | Status, breadth, replay, new content | Prestige ranks, rare cosmetics, legacy records |

Daily rewards are a welcome-back bonus, not the main source of wealth or a streak obligation.
Missing a day must not erase an accumulated streak. Repeated actions may use explicit soft
caps or diminishing returns when balance requires them, but the base design does not impose
a universal energy system.

## Player model

A player is global to the Butterbot economy and is keyed to one Discord user identity. Guilds
are interaction venues, not separate copies of the player or currency. Leaving one guild does
not fork or delete progression.

The core player record owns identity and lifecycle facts only:

- internal player identifier and unique Discord user identifier;
- creation time and the minimal lifecycle state needed to distinguish an active identity from a
  later pseudonymized/deleted identity;
- optional last-known display metadata used only as a cache; and
- settings that affect presentation, never economic rules.

Wallets and balances belong to Economy. Account XP/level and all profession state belong to
Progression. Restrictions, freezes, durable capabilities, and access audit belong to
Safety/access. Inventory, equipment, achievements, and collections likewise remain separate
owned records or aggregates. The first production baseline therefore does not add XP columns or
restriction/capability columns to the player table and does not create progression or
safety/access tables.

A Discord username is mutable and is never a key. Guild membership is not required to retain
progress. Derived player statistics are calculated from progression, profession/mastery
unlocks, equipment, and temporary effects; a mutable "total power" field is not a source of
truth.

## Interaction of systems

The intended value flow is:

```text
profession action / quest / event
        |          |        |
        +------ rewards ----+
                   |
          items + XP + coins
            |      |      |
    collection   levels  wallet
       |           |       |
    status      unlocks     +--> shops / fees / crafting sinks
       |           |       |
       +---- crafting/equipment ----> stronger or broader activity choices
                         |
                    player trade
```

No feature writes another feature's state directly. A use case such as crafting coordinates
inventory consumption, output creation, currency cost, XP, and history in one application
transaction. Cross-system rewards are explicit reward bundles interpreted by an application
service, not callbacks hidden inside models.

## Gameplay system rules

### Shops and selling

NPC shops provide predictable acquisition and sinks. Stock, eligibility, price, purchase
limits, and effective dates are data-driven and versioned. NPC buyback is deliberately lower
than expected acquisition value and may be limited by item or period; it must not create a
risk-free crafting or shop arbitrage loop. A quoted price is either honored once with a short
expiry or the player is asked to accept the current price.

### Crafting

A recipe names exact inputs, currency costs, prerequisites, outputs, and any random outcome
table. Inputs are reserved and consumed atomically with outputs. Early recipes should be
deterministic. Random quality or failure belongs only in later content with disclosed odds,
bounded loss, and an injected random source.

### Quests and random events

Quests are objectives over immutable committed action facts, not Discord message counts.
Progress consumers are replay-safe, and reward claims have their own business one-use keys in
addition to transport idempotency. Random events are bonuses or choices with disclosed
categories; they cannot debit value or destroy items without an explicit player decision.
Event definitions have active windows and version identifiers so historical rewards remain
explainable.

### Trading

Direct trade eventually uses offer, accept, cancel, and expire states with assets held in
escrow. Acceptance revalidates both parties and transfers all assets atomically. There is no
trust-based multi-command exchange. Bound, equipped, locked, or otherwise unavailable items
cannot enter an offer. Trade history is retained for support and abuse analysis.

### Leaderboards

Leaderboards are read models, not economic authorities. Prefer categories and time windows
that celebrate different play styles: wealth, profession level, collection completion,
achievements, and prestige. Avoid a single composite power score. Privacy/moderation states
may suppress display without deleting progress.

## Long-term content principles

- New tiers consume outputs from older tiers where sensible, preserving demand for early
  materials.
- Horizontal unlocks, specialization, collection, and cosmetics carry more late-game weight
  than compounding yield multipliers.
- Permanent multipliers are additive, small, capped, and budgeted across systems.
- Catch-up helps players reach active social content but does not counterfeit scarce legacy
  achievements.
- Rotating content may change available goals and recipes, but the baseline proposal does not
  delete permanent progression or balances at a season boundary.
- Every repeatable reward loop has a corresponding consumption path, telemetry plan, abuse
  analysis, and safe tuning lever.

## Feature design checklist

Before implementation, each feature proposal must state its inputs, outputs, cadence,
eligibility, cooldown or limit, expected value and variance, failure behavior, idempotency
key, transaction boundary, cross-system effects, abuse cases, telemetry, and treatment of
older content.
