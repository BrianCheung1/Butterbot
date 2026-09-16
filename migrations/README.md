# Migrations

Alembic owns all schema evolution. Revision `20260825_0001` is the deliberately minimal Slice
1.0 baseline authorized after the explicit Final Phase 0 Gate Review. It creates only Players
identity, Economy wallet/committed-ledger/projection structures, and Operations-owned generic
transport-idempotency plus bounded aggregate-integrity sentinel tables. It creates no gameplay, progression, inventory, banking, or
safety/access state.

No production database has been released from this baseline. Before its repeat independent
review, the same initial revision was tightened in place with SQLite transport identity,
embedded-NUL, stable-shape, fingerprint, outcome-code, valid JSON-object outcome, canonical UUID,
permanent audit-identity and exact-integer storage checks, plus isolated SQLite triggers that
maintain the account/player completeness sentinel. The in-place edit follows the existing policy only because this
baseline remains unreleased and unconsumed. Application validation remains in place. Startup
rejects committed incomplete transport rows and incomplete aggregates; exhaustive history and
canonical-storage checks run in the stopped-service streaming verifier.

Migrations are an explicit operator/developer action. Normal application startup opens only an
existing database in read/write mode, never runs Alembic, and requires the exact release head.

Migration policy and unresolved database choices live in
[`docs/database.md`](../docs/database.md) and [`docs/decisions.md`](../docs/decisions.md).


## September 2026 gate remediation

Release head is `20260914_0003`; `20260825_0001` remains the frozen historical
baseline. Upgrade explicitly with mutations stopped. The new revision prevents changes
to player UUID/Discord identity, account UUID/owner/kind/currency/system identity, and
projection account UUID/kind. No-op identity assignments remain legal.

Readiness and the stopped-service verifier compare all application tables, explicit
indexes, and triggers against a release-bound, case-sensitive schema manifest, including
ledger/transport constraints and retention indexes. Work is bounded by schema object
count. Implicit uniqueness indexes are covered by owning table SQL. Unexpected application
schema objects also fail closed.

Native Linux evidence must come from the exact reviewed candidate on the provisioned
Linux host. Capability coverage must be collected and pass using real nonzero effective
capabilities. Failure, skip, or absence fails the runner. Only the exact network-namespace
test may skip for documented host denial of namespace creation; missing unshare is not
an allowed skip. Existing UID/GID/mode, mounts, abstract socket, sticky replacement,
links, namespaces, and active/waiting/committing/fail-stop SIGTERM tests remain required.

Revision `20260914_0003` adds conflicting-insert guards independently of recursive_triggers.
It reconstructs only missing sentinel rows from older replacement holes; no economic repair
is performed. Readiness refuses remaining incomplete aggregates. Revisions 0001 and 0002
are unchanged. Downgrade drops the three new guards and preserves financial and sentinel data.
