# Economy design

## Principles

- Treat every creation, transfer, and destruction of value as auditable.
- Use integer units; define display formatting separately from stored value.
- Change all sides of a transfer atomically and reject partial completion.
- Design sources and sinks together, with explicit rate and population assumptions.
- Prefer bounded, observable adjustments over irreversible global tuning changes.
- Consider automation, alternate accounts, collusion, and concurrency in every reward loop.

## Required analysis for an economic feature

Document faucets, sinks, stockpiles, transferability, limits, cooldowns, expected value,
variance, progression prerequisites, and metrics. Include a rollback or remediation plan for
incorrect rewards.

## Open questions

- Will balances be represented only by current totals, by an immutable ledger, or both?
- Is currency global or guild-scoped, and will multiple currencies exist?
- What transfer fees, taxes, listing costs, upkeep, or decay are appropriate sinks?
- Which items are tradable, bindable, consumable, durable, or recoverable?
- What inflation and wealth-concentration targets define a healthy economy?

