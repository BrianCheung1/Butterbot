# Slice 1.5 independent local acceptance — finalized 2026-10-05

SLICE 1.5: PASS

This decision concerns **provisional local acceptance only**, under the user's authorization to
continue after Slice 1.4 and explicit deferral of Linux validation. Native production/release
acceptance remains FAIL. This report does not authorize production, migrate the running
development session, or grant correction capabilities to a live operator.

## Candidate binding

Reviewed source digest:
`bafa67d5a9e19e5a9c4e43cc9da1ba37a9e158439c0da8642c24d699bb3eaa16`.
The complete per-file manifest and working-tree binding are in `slice-1-5-candidate.json`.
This is a dirty working-tree candidate based on `9dd825d957385a49eab43ed4f0dadb3af1f3267b`;
HEAD alone does not identify the implementation. The reviewer independently checked every one
of the 113 manifest file hashes against disk, including again on 2026-10-05 before finalizing
this verdict. Documentation is bound separately by Git.

The independent focused run used source digest
`4d3dc9aa56b624b4e5a1cced9ee67247d78b51ff1b635f92d6f7e14852aaa665`.
Before downgrade remediation, the reviewer compared manifests: only four existing test files changed
(`test_aggregate_replacement.py`, `test_composition.py`, `test_database_runtime.py`, and
`test_release_gate_remediation.py`) to update stale expected schema-head strings from 0007
to 0008, producing intermediate digest
`069259d16fedc323271984317deb89406200e45d160bc56d29e1240e8116ca33`.
Subsequent downgrade remediation changed migration 0008 and its regression coverage as described
below. The coordinating agent verified the remediated digest remained unchanged across the full run.

## Review and regression evidence

The reviewer examined the roadmap/testing/decision contracts; correction domain/service,
repository and transaction composition; private history snapshot/query/adapter; durable
capabilities and replay flow; and migration 0008 validation and immutable-history triggers.
No application or migration code was edited by the reviewer. Fresh reviewer probes were
subsequently promoted to the tracked `tests/test_correction_adversarial.py` at the coordinator's
request and independently passed Ruff, formatting and strict Pyright.

Pre-remediation independent focused regression: **183 passed**, one existing discord.py deprecation,
in 35.89 seconds. Selection includes correction/adversarial/migration/history/adapter tests
and grant, safety, safety-command and restricted-development regressions. Evidence:
`.gate-local/slice15-independent-final.log` and `.xml`.

After remediation, the reviewer reran correction, adversarial, migration, history and adapter
regressions: **66 passed**, no warnings, in 18.28 seconds. Evidence:
`.gate-local/slice15-independent-remediated.log` and `.xml`. The reviewer also independently
compared the entire downgraded schema against the actual frozen Git `9dd825d` release manifest:
all **72 schema objects matched**. Evidence: `.gate-local/slice15-independent-downgrade-after.log`.

The coordinating agent's final mandatory full verification passed:

- Ruff check and format check (146 files); strict Pyright: zero errors/warnings; Git diff check.
- Full pytest: **905 passed, 32 skipped**, one existing discord.py deprecation, 108.79 seconds.
  Evidence: `.gate-local/slice15-full-remediated.log` and `.xml`.
- Previously applied migrations 0001 through 0007 remain unchanged.

The earlier full run's four stale schema-head expectation failures are retained in
`.gate-local/slice15-full.log` and `.xml` (900 passed, 32 skipped). They were corrected before
the final full run; no failure was silently omitted from the final selection.

## Fresh adversarial results

Nine reviewer-authored cases passed against real disposable SQLite files:

- Incoming posting UPSERT with `ON CONFLICT ... DO UPDATE` cannot move a posting into a sealed
  correction transaction.
- Incoming ledger `UPDATE OR REPLACE` cannot replace a sealed correction by primary identity
  or unique correlation identity.
- `INSERT OR REPLACE` cannot replace the permanent correction receipt.
- Each SQL attack was checked with foreign keys enabled and recursive triggers both off and on
  (eight cases), with unchanged monetary state reconciled afterward.
- Competing corrections of two distinct original grants cannot exceed the execution-time rolling
  ceiling. A new request one millisecond before the exact cutoff remains limited; at the cutoff
  it succeeds. Ledger/projection/supply reconciliation passes after both corrections.

Initial standalone probe evidence remains in `.gate-local/slice15-independent-probes.log` and
`.xml`; the equivalent tracked cases are included in the 183-test independent run and final full
suite. This review also verified regression coverage for authority revocation before replay,
global disable and freeze behavior, explicit bypass audit, insufficient funds and arithmetic
bounds, partial-write rollback/cancellation, concurrent business duplicates, transport retention,
data-bearing 0007 upgrade preservation, and post-commit alert/Discord response loss.

## Resolved downgrade finding

After the mandatory run, the coordinator raised downgrade compatibility for independent review.
The earlier candidate had a confirmed Medium finding: 0008 renamed `safety_capabilities_next`
to `safety_capabilities`, changing SQLite's stored table SQL quoting, and restored constraints in a different order from
the frozen 0007 schema. The schema normalizer only collapses whitespace. Thus a permitted
downgrade reported revision 0007 but failed that release's exact schema-readiness fingerprint.
Downgrade/re-upgrade tests missed this because the new head was compatible with itself.
The reviewer reproduced the failure in `.gate-local/slice15-independent-downgrade-before.log`;
the initial PASS draft was withdrawn and the intermediate candidate received local FAIL.

The remediated downgrade explicitly recreates the original unquoted table name with frozen
constraint ordering and preserves existing capability rows through a temporary backup.
A whole-schema roundtrip regression now checks exact prior SQL and capability preservation.
Independent comparison to the frozen 72-object manifest and the 66-test regression run above
confirm the fix. The final 905-test full run passes. This finding is closed; the final local
PASS applies only to the remediated digest, not the previously failed candidate.

## Findings and scope limits

No unresolved local Blocking or High finding was identified. Corrections retire coins without
changing original issuance or grant history; guarded projections, receipt, audit and transport
outcome share one transaction. The amount is capped by the original grant, current approval
threshold and per-operation limit. Current correction authority is required even before replay;
runtime mutation disable cannot be bypassed. Freeze bypass needs separate durable authority and
is recorded and audited. Migration/bootstrap confer neither new correction capability.

The documented narrow scope is accepted: one partial debit consumes the whole permanent
original-grant/wallet correction identity, and correction rolling totals are independent of grant
issuance totals. Larger, bulk and policy-changing corrections are unsupported. Expanding these
rules requires another reviewed decision rather than using repeated requests to evade them.

History is self-only, privately deferred, read-only and bounded to five entries per page. Its
timestamp/UUID keyset ordering is deterministic and does not expose operator identities, reasons,
system accounts or other-player lookup. Each page has a read snapshot; pagination across requests
is not a persistent snapshot, as documented. Unsealed legacy monetary history is not certified
or repaired and gets no invented resulting balance.

The running Slice 1.4 development bot/database was not touched by this reviewer. Existing
server/user/channel restrictions remain required. All 32 Windows skips remain non-evidence for
Linux guarantees; native kernel/storage/signal validation, deployment-host operational gates and
independent release acceptance remain required before production. `/give` usability work remains
deferred per the user. Local acceptance does not itself approve new live capabilities or public use.
