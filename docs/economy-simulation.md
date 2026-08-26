# Phase 0 economy and progression envelope

Status: accepted architecture envelope, model version `phase0-v1`, 2026-08-25.

This model is design evidence for later gameplay slices. It does not approve exact shipped
rewards, prices, cooldowns, or level curves, and it implements no Discord command or gameplay
mutation. Its purpose is to make future balance proposals fit a coherent numerical range before
they can issue value publicly.

## Reproducing the worksheet

All assumptions live in `balance/phase0_economy.toml`. The pure simulator is
`butterbot.simulation.economy`; it uses exact rational arithmetic for expected values and has no
Discord or persistence dependency. Regenerate the tracked worksheets from the repository root:

```powershell
.venv\Scripts\python.exe -m butterbot.simulation
```

The command writes:

- `balance/phase0_projection.csv`: every primary cohort at every required horizon;
- `balance/phase0_source_sink.csv`: daily source/sink EV and configured variance;
- `balance/phase0_milestones.csv`: elapsed days and commands to each major unlock;
- `balance/phase0_sensitivities.csv`: returning-player and alternate-account cases at every
  configured horizon; and
- `balance/phase0_supply_pressure.csv`: aggregate results for 1,000 active players using the
  configurable launch cohort mix.

Fractional coins, XP, actions, commands, and item units are population-level expectations.
Actual game postings, XP grants, and quantities remain integers. A tracked-output test fails if
the TOML, simulator, and CSV files disagree.

## Model assumptions

### Cohorts and activity

An active day is a day on which the player performs the configured profession actions. Calendar
daily averages include inactive days. Commands include one command per action, claims, estimated
conversion/spending commands, and one inspection command per active day.

| Cohort | Active days/week | Actions/active day | Actions/calendar day | Commands/calendar day | Economic yield bonus | Launch mix |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Casual | 4 | 4 | 2.29 | 4.00 | 0% | 50% |
| Regular | 6 | 10 | 8.57 | 12.43 | 3% | 30% |
| Dedicated | 7 | 25 | 25.00 | 33.25 | 8% | 15% |
| Optimized/hardcore | 7 | 45 | 45.00 | 58.25 | 15% cap | 5% |

The first 30 actions on an active day receive full expected rewards. Further actions receive
40% expected rewards. The soft cap applies to economic output and profession XP, not command
eligibility. It keeps a short session valuable without turning unlimited activity into unlimited
power. Economic yield bonuses are additive and capped at 15% across all future permanent
sources; a feature must consume part of this shared budget rather than adding another cap.

The model includes two non-primary sensitivities:

- a returning regular receives 25% extra profession XP for their first 14 active days back, but
  no currency or item-yield boost; and
- an alternate account claims daily and performs one action every day, with no objective reward
  or aspirational spending.

### Sources, items, XP, and commands

One fully rewarded action has these provisional expected values:

- 3 material units generated;
- 70% of material output sold to an NPC at 10 coins per unit;
- 2 direct coins of additional EV;
- 23 coins total active-source EV before the cohort's bounded multiplier;
- 10 profession XP and 2 account XP; and
- source variance of 144 coin-squared, or a 12-coin standard deviation.

The daily claim is 15 coins. Weekly-objective EV is 60 coins and 25 account XP multiplied by
the cohort's configured completion probability. The daily claim contributes 13.1% of casual
income, 5.7% of regular income, 2.3% of dedicated income, and 1.5% of optimized income. It is a
welcome-back reward rather than the main faucet.

Players sell 70% of expected material output. Of the retained 30%, the baseline crafting and
collection demand consumes 80%. The resulting material stockpile is 6% of gross generated
material. This is deliberately a pressure target for future recipes, not an inventory cap.

### Sinks and selected pre-selling sink

The selected Slice 2.5 sink is **non-destructive tool charges**:

- every profession action consumes one transparent charge costing 6 coins to replace;
- charge demand scales with actual actions, including activity beyond the reward soft cap;
- zero charges disable the equipment bonus but do not destroy the tool or block the base action;
- refills are an explicit purchase and retire coins under a dedicated reason; and
- the price, bundle size, applied content version, charges consumed, refill rate, and no-charge
  action rate must be measurable.

This sink can be implemented and exercised in development before repeatable NPC selling is
public. Public selling remains gated until charges are available, affordable, understandable,
and included in the full Phase 2 loop. The six-coin assumption alone removes 21–28% of active
source EV across the primary cohorts. It avoids permanent item loss and remains useful to an
established player because demand follows profitable activity.

Other envelope demand is 4 crafting coins and 2 NPC-supply coins per economic action, plus up
to 4 aspirational-project coins scaled by cohort participation. Recommended purchases at major
bands cost 300, 1,500, 5,000, 15,000, 30,000, and 50,000 coins. These are capacity probes, not
approved catalog prices. Recurring sink variance is provisionally 25 coin-squared per economic
action; milestone timing is not included in that variance.

Recurring sink EV is 45.4% of casual source EV, 54.6% of regular, 61.0% of dedicated, and 70.1%
of optimized source EV. A projection always funds recurring demand first, then reached
milestone demand, and never spends more than expected income. Unfunded demand is reported rather
than producing a negative wallet.

## Results

Each cell below is `expected coin stockpile / profession XP / latest major unlock`. Full income,
spending, source/sink standard deviation, item stockpile, account XP, actions, and commands are
in `phase0_projection.csv`.

| Cohort | 1 day | 1 week | 1 month | 3 months | 6 months | 1 year | 3 years |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Casual | 36 / 23 / starter | 250 / 160 / starter | 771 / 686 / tool | 2,950 / 2,080 / tool | 4,700 / 4,160 / tier 2 | 11,236 / 8,343 / tier 2 | 17,307 / 25,029 / specialist |
| Regular | 102 / 86 / starter | 411 / 600 / tool | 2,747 / 2,571 / tool | 7,443 / 7,800 / tier 2 | 11,686 / 15,600 / deep mine | 15,274 / 31,286 / specialist | 59,421 / 93,857 / mastery-ready |
| Dedicated | 252 / 250 / starter | 1,461 / 1,750 / tool | 5,747 / 7,500 / tier 2 | 16,093 / 22,750 / deep mine | 23,986 / 45,500 / specialist | 40,024 / 91,250 / mastery-ready | 173,671 / 273,750 / prestige prep |
| Optimized/hardcore | 292 / 360 / starter | 1,742 / 2,520 / tool | 1,953 / 10,800 / deep mine | 4,751 / 32,760 / specialist | 1,302 / 65,520 / mastery-ready | 4,697 / 131,400 / prestige prep | 217,690 / 394,200 / prestige prep |

The optimized stockpile contracts at months 6–12 because newly reached aspirational purchases
absorb almost all available flow. It remains non-negative and all reached demand is fundable,
but this is a play-test warning: required unlock costs must not make optimal play feel like a
mandatory zero-balance treadmill. By year three, all primary cohorts retain no more than nine
months of their current gross inflow.

Material stockpiles at year three are about 451 casual, 1,740 regular, 5,322 dedicated, and
8,160 optimized base-material units. This equals about 66 days of gross material output for
each cohort. If actual holdings exceed that band, older-material recipes, collections, or sale
fractions need adjustment before adding more drops.

### Major unlock spacing

| Unlock (XP) | Casual | Regular | Dedicated | Optimized/hardcore |
| --- | ---: | ---: | ---: | ---: |
| First tool choice (500) | 21.9 days | 5.8 days | 2.0 days | 1.4 days |
| Second tier (3,000) | 131 days | 35 days | 12 days | 8.3 days |
| Deep mine (10,000) | 438 days | 117 days | 40 days | 27.8 days |
| Specialist (25,000) | 1,094 days | 292 days | 100 days | 69 days |
| Mastery-ready (60,000) | 2,625 days | 700 days | 240 days | 167 days |
| Prestige preparation (120,000) | 5,250 days | 1,400 days | 480 days | 333 days |

The curve intentionally does not promise every vertical milestone to every cohort within three
years. Casual and regular players need breadth, collections, and horizontal goals between
bands; dedicated players reach prestige preparation in roughly 16 months; an optimized player
can reach it in roughly 11 months but receives no uncapped post-cap economic multiplier.

### Aggregate currency pressure

For the configurable 50%/30%/15%/5% launch mix, 1,000 continuously active modeled players mint
89.5 million and destroy 73.1 million coins by one year, leaving 18.4% as net new supply. At
three years they mint 268.6 million, destroy 205.2 million, and retain 63.4 million, or 23.6%
of minted value. The percentage rises after the finite milestone catalog is purchased; repeatable
late-game projects must therefore arrive before finite demand is exhausted.

The alternate-account sensitivity retains 780 coins after one month and 7,690 after one year;
daily rewards form 39.5% of its income. Ten such accounts scale that stockpile linearly. This
does not prove abuse, but it confirms that daily coins, transfer gates, rolling limits, funnel
telemetry, and valuable-faucet release order cannot be evaluated independently.

Both sensitivity cohorts are emitted at every primary one-day-through-three-year horizon so the
accepted decision and tracked worksheet cover the same range. The returning case has 59,421
coins and 94,207 profession XP at three years; the alternate case has 21,670 coins and 10,950 XP.

The returning sensitivity gains about 350 additional profession XP in the first month and no
extra coins. That is the intended catch-up shape: shorten old progression without creating a
new transferable faucet.

## Acceptable envelope for future features

A future faucet, sink, curve, item table, or permanent modifier stays inside Phase 0 only if its
simulation shows all of the following for relevant cohorts:

- daily rewards remain 5–20% of casual income, no more than 10% of regular income, and no more
  than 5% of dedicated/optimized income;
- combined permanent economic yield bonuses remain at or below 15%; overflow after the first
  30 actions/day receives no more than 40% reward EV unless this decision is explicitly revised;
- recurring sink demand absorbs 45–71% of gross source EV without preventing useful casual play;
- for the launch mix, net new supply stays roughly 15–30% of cumulative minting after the first
  six months, with reason-attributed evidence explaining excursions;
- expected wallets never go negative, reached milestone demand is fundable, and three-year coin
  stockpiles stay below nine months of the cohort's current gross inflow;
- base-material stockpiles stay below roughly 90 days of gross output by year three;
- the first meaningful unlock lands within one to four weeks for casual play, while the normal
  vertical cap remains months away for dedicated/optimized play;
- required random progression has a deterministic completion path and is simulated separately
  for tail risk; and
- a new source reports EV, variance, multiplier interaction, abuse sensitivity, stockpile effect,
  and a recurring consumption path before public release.

These are review ranges, not automatic dynamic-pricing rules. Crossing one is a prompt to
inspect player value and assumptions, not permission to silently tax wealth or personalize
prices.

## What production agents must measure

Every economic feature agent must compare its proposal and later telemetry against this model
version and report, by source/sink reason and observable cohort proxy:

- active days, actions and commands per active/calendar day, session length, soft-cap pressure,
  and no-reward/no-charge actions;
- gross minting, destruction, net issuance, source/sink ratio, source/sink variance, velocity,
  and daily-reward share;
- p50/p90/p99 wallet and item stockpiles, concentration, affordability, purchase delay, and
  unfunded demand;
- profession/account XP per day, elapsed time and commands between unlocks, cap arrival, and
  returning-player catch-up usage;
- tool-charge consumption, refill conversion, bundle size, effective cost per profitable action,
  zero-charge behavior, and abandonment after a refill prompt;
- item generation, NPC-sale fraction, crafting/collection consumption, and old-material days of
  supply;
- yield-modifier ownership and the aggregate applied bonus, not just each feature's local bonus;
  and
- alternate-account claim/action patterns, P2P funnels, repeated counterparties, and rolling-limit
  pressure without claiming that telemetry proves common ownership.

Balance changes are prospective, versioned, and re-simulated at every required horizon. A
feature cannot redefine the cohort assumptions in its own module merely to pass its gate.

## Unresolved balance decisions

- Actual action duration, cooldowns, Discord interaction burden, and launch cohort mix need
  measured play-test evidence.
- The material drop distribution, sale fraction, variance/correlation, rare-drop fallback, and
  NPC buyback caps remain content decisions.
- Tool charge capacity, refill bundle size, whether base tools consume charges, and exact refill
  price require UX tests. The selected invariant is non-destructive failure with an always-usable
  base action.
- The exact daily claim period/grace rule and whether 15 coins remains the shipped amount gate
  Slice 1.6.
- Exact curve thresholds, unlock content, and purchase prices remain versioned proposals before
  public profession rewards; the values here are bounds and capacity probes.
- Repeatable mastery, prestige, cosmetic, collection, and community-project demand must replace
  finite milestone demand before mature cohorts exhaust it.
- Transfer gates, rolling limits, sanctions, and review ownership remain required before the
  alternate-account stockpile can move between players.
- Real source/sink and player-retention covariance is unknown; the model treats configured daily
  action EV and variance as independent and does not predict market prices.
