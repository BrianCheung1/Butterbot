# Migrations

Alembic will own all schema evolution. Its environment and first revision should be created
with the first intentionally designed schema after the explicit Final Phase 0 Gate Review, not
guessed during project initialization. Slice 0.4 creates no migration.

Migration policy and unresolved database choices live in
[`docs/database.md`](../docs/database.md) and [`docs/decisions.md`](../docs/decisions.md).
