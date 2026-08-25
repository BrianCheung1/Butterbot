# Decisions

Use this file as a lightweight decision log until its volume justifies individual records.
For each accepted decision, record the date, context, choice, consequences, and superseded
decision if any.

## Accepted foundations

### 2026-08-25 — Initial technical baseline

- Python 3.13 and asynchronous `discord.py`
- SQLite initially, with PostgreSQL migration kept viable
- Async SQLAlchemy for persistence and Alembic for migrations
- pytest, Ruff, and strict Pyright as quality tools
- Business rules independent of Discord presentation
- Application services own explicit transaction boundaries

These choices establish direction without specifying a domain model or deployment topology.

## Unresolved decisions

- Player and economy scope: global, guild-specific, or hybrid
- First playable loop and feature order
- Balance representation and audit/ledger model
- Identifier, timestamp, locking, and retry conventions
- Configuration, deployment, hosting, and CI platform
- Background task scheduling and durability
- Command style and Discord interaction lifecycle
- Seasonal reset and long-term content policy
- Observability, moderation, abuse response, and data-retention requirements

