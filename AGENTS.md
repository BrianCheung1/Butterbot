# Agent guide

## Scope

Butterbot is a Python 3.13, asynchronous `discord.py` economy game intended to support
long-lived progression. Read the relevant files in `docs/` before changing behavior.

## Engineering rules

- Keep game rules independent of Discord commands, views, and embeds.
- Put multi-step state changes behind explicit service-level transaction boundaries.
- Keep database-specific behavior isolated; SQLite is the first backend, PostgreSQL is a
  future target.
- Add an Alembic migration for every schema change. Never edit an applied migration.
- Use integer amounts for currencies and other exactly counted resources.
- Make randomness and time injectable at business-logic boundaries when introduced.
- Prefer a small, concrete design over speculative interfaces or generic frameworks.
- Record consequential decisions and unresolved questions in `docs/decisions.md`.

## Verification

Run `ruff check .`, `ruff format --check .`, `pyright`, and `pytest`. Tests should emphasize
business rules, transaction rollback, concurrency-sensitive behavior, and migration paths.
Never commit tokens, local databases, generated caches, or `.env`.

