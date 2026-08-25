# Database

## Initial direction

SQLite is the initial database. Application access will use SQLAlchemy's async API with
`aiosqlite`; Alembic will version schema changes. This keeps SQL and transaction behavior
visible while leaving a practical route to PostgreSQL.

Application services own transactions. Repository operations participate in the caller's
transaction and do not silently commit. Constraints enforce invariants where practical, and
foreign-key enforcement must be enabled for SQLite connections. Currency and exact resource
counts use integers.

## Migration policy

- Every schema change receives a reviewed Alembic revision.
- Test upgrades from a supported prior schema against a real temporary database.
- Prefer additive, staged migrations for data-bearing or compatibility-sensitive changes.
- Treat applied revisions as immutable; fixes get new revisions.
- Plan explicit backup and restore checks before production data exists.
- Avoid relying on SQLite-only semantics without documenting a PostgreSQL alternative.

## Open questions

- What is the first schema and aggregate boundary?
- Should economic history use double-entry ledger records, domain events, audit rows, or a
  combination?
- Which identifiers and timestamp representations best support PostgreSQL migration?
- What isolation, locking, retry, and idempotency rules apply to competing writes?
- How long are audit, event, and seasonal records retained?
- When does PostgreSQL migration become necessary, and how will it be rehearsed?

