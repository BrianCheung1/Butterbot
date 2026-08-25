# Progression

## Progression layers

Butterbot uses distinct progression layers because each answers a different player question:

| Layer | Question answered | Earned from | Primary rewards |
| --- | --- | --- | --- |
| Account XP and level | How broadly experienced am I? | First completions, varied play, quests, milestones | Feature access, profile status, modest utility |
| Profession XP and level | How capable am I in this activity? | Successful profession actions and objectives | Locations, resources, recipes, profession stats |
| Mastery | How did I specialize after competence? | Post-cap or milestone profession play | Sidegrades, controlled specialization, cosmetics |
| Achievements | What notable feats have I completed? | One-time explicit criteria | Status, cosmetics, bounded rewards |
| Collections | What permanent sets have I assembled? | Donating or registering items | Completion, lore, recipes, cosmetics |
| Prestige | What have I voluntarily replayed at a higher order? | Endgame requirements and an explicit reset | Legacy rank, new constraints/options, status |

Account level must not be an uncapped multiplier on all rewards. It represents breadth and
access. Most activity power comes from profession level and equipment, each within a declared
bonus budget.

## XP and levels

- XP values and level thresholds are non-negative integers. A level is derived from lifetime
  XP using a monotonic, versioned curve; stored level is only a checked projection if retained
  for query speed.
- XP is never spent as currency. Unlocks refer to level or explicit milestones.
- A single action may grant account and profession XP, but each grant has a reason and cap.
- Repetition of the easiest action should not remain optimal forever. Higher tiers improve
  rewards, while varied objectives provide account XP.
- Curves use hand-audited milestone bands rather than an opaque formula treated as permanent.
  Simulation must test time-to-level for casual, regular, and optimized cohorts before values
  ship.
- Progress is not lost through ordinary failure, inactivity, balance patches, or leaving a
  Discord guild.

No exact curve or level cap is approved in this design. Content counts and target playtime are
needed before numerical thresholds can be responsible.

## Profession model

A profession is a stable definition with a key, display metadata, level curve, action set,
unlock table, reward tables, and content version. Player profession state contains XP plus
only genuinely stateful facts such as cooldown/opportunity state and selected mastery; level,
eligible actions, and total modifiers are derived.

Every profession action follows the same conceptual pipeline:

1. validate player and profession prerequisites;
2. select an action/location/tier;
3. calculate costs and eligible reward table from a versioned snapshot;
4. resolve with injected clock and random source;
5. atomically apply immediate item/currency rewards, costs, XP, limits, one-use state, and an
   immutable action fact; and
6. return a structured outcome for Discord presentation and economic telemetry.

Reusable concepts may include action eligibility, reward bundles, weighted drop tables,
cooldowns, tools, profession XP, mastery modifiers, and content versions. Profession-specific
rules remain specific:

- **Mining** selects a location or rock tier and produces ores, stone, and rare finds. It is
  the reference profession and should prove the shared action contract.
- **Fishing** may later add location, bait, catch tables, and choice/timing flavor. It should
  not be forced into mining terminology merely to reuse code.
- **Farming** introduces planted plots and durable time-based state. Its scheduling and harvest
  transaction are materially different from an instant gather action.

This is a reusable pattern, not a generic profession engine to build in advance. Extract a
shared abstraction only when the second implementation demonstrates stable common behavior.

## Player statistics and equipment effects

Statistics have stable semantic keys and declared units, such as integer points or basis
points. Effective values are derived from separately inspectable components:

```text
effective statistic = base + progression unlocks + equipment + temporary effects
```

Multiplicative stacking is avoided. Where a percentage is necessary, modifiers add within a
category, each category has a cap, and one documented order of operations applies. Reward
calculation records the content and modifier versions so surprising outcomes can be
explained. Stats should affect choices such as access, drop-table weighting, quality, or
convenience; no single stat should dominate every profession.

## Mastery philosophy

Mastery begins near or at a profession's normal cap and extends it horizontally. It should:

- ask the player to choose among useful specializations rather than fill every node quickly;
- grant sidegrades, new recipes/actions, targeted efficiency, collection goals, and cosmetics;
- allow a clearly priced respecialization if choices are not permanent;
- cap all economic modifiers and publish their stacking rules; and
- remain extensible by adding branches without invalidating earned points.

Mastery is not a second infinite XP bar with exponential yield. Until an explicit mastery
curve/version policy ships, XP at the normal profession cap does not accumulate hidden
post-cap credit. Future nodes never retroactively convert undocumented excess activity into
points. Reversibility, respec costs/accounting, and treatment at a new curve version are gated
decisions in the mastery roadmap slice.

## Prestige philosophy

Prestige is an optional late-game replay contract, never an automatic seasonal wipe. A player
sees an exact preview of requirements, reset scope, retained state, and rewards, then confirms
through an idempotent transaction.

The recommended baseline is profession-specific prestige: reset that profession's normal XP,
level, and selected temporary unlocks while retaining the player identity, wallet, owned
items, account progression, achievements, collections, cosmetics, and an immutable legacy
record. Prestige rewards primarily status, cosmetics, alternative rules, and capped mastery
capacity. It must not create a permanent compounding faucet that makes non-prestige players
economically irrelevant.

Items whose equip requirements are no longer met become safely unequipped, never destroyed.
Before implementation, its gated ADR must cover curve migration, epoch/cooldown, reset and
retention, retained high-tier asset eligibility, respec state, stockpiled inputs, and capped
repeat rewards. The preview uses a business-unique prestige epoch. Exact costs and whether any
account-wide prestige exists remain later product decisions.

## Achievements and collections

Achievements have immutable keys and explicit, testable criteria over committed action facts.
Quest, achievement, and collection-observation progress uses the durable eventual-consumer
contract in `architecture.md`, with unique `(consumer_key, fact_id)` processing. Their reward
claims are separate business-unique transactions. Immediate rewards and XP belonging to the
originating action remain in that action's transaction. Secret achievements may hide criteria
from players but not from audit tooling.

Collections are permanent registration/donation tracks keyed by item definition, category,
or curated set. A collection operation states whether it consumes the item; consumption is
the preferred design when the collection is intended as an item sink. Completion rewards are
claimed once. Newly added collection entries do not silently revoke a completed legacy tier;
new tiers or versions preserve the earlier accomplishment.

## Catch-up and late game

- New and returning players may receive bounded boosts to early progression, guided quests,
  or easier access to older materials, based on stable rules rather than wealth confiscation.
- Catch-up ends before the newest aspirational tier and never grants legacy-limited status.
- Late-game goals emphasize perfecting builds, collections, rare recipes, mastery branches,
  prestige challenges, cosmetics, and leaderboard categories.
- Content extensions add milestone bands and horizontal goals. Existing XP is not devalued by
  changing its historical meaning without a migration and explicit decision.
- Any random reward required for a recipe, collection, unlock, or prestige condition has a
  deterministic completion path such as fragments, pity progress, exchange, crafting, or a
  cumulative milestone. Unbounded RNG is reserved for optional prestige/cosmetic outcomes.

## Balance validation

Before approving a progression curve, specify target time horizons, active/passive split,
milestones, unlock dependencies, caps and soft caps, catch-up rules, prestige effects, and a
full multiplier budget. Simulate new, casual, established, returning, and optimized players,
then version the chosen curve and reward tables.
