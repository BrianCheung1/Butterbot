# Slice 1.4 provisional local gate — 2026-09-27

**Release verdict: FAIL. Local status: PASS (independent acceptance addendum below).**

## Independent acceptance addendum

The continuation independently accepted commit `9dd825d` for provisional local use. See
`slice-1-4-independent-acceptance.md`: 187 independent regression tests and four fresh adversarial
probes passed; all 103 candidate source hashes matched. The coordinator reran mandatory checks:
827 passed, 32 skipped, one known warning; Ruff, formatting, Pyright and diff checks passed.
The historical pending-review narrative below describes the original implementation handoff.
Native production acceptance remains deferred and FAIL. Activation evidence is recorded separately
in `slice-1-4-development-activation.md`.

Implementation and required local verification are complete. Final independent local acceptance
is pending because the reviewer reached its usage limit before issuing a verdict. Native Linux
acceptance remains absent and user-deferred. No live grant activation, production authorization,
or dependent slice progression is claimed.

## Candidate binding

Base commit: `c0c859c9cc5d423b292fd2b537baa48d3d0f2745`.
Final tested source digest: `0e3328135bea721f6cc6a7364aafb2193fa749fc91c6cf8f51e230cc28f9d5c8`.
Per-file hashes and observed working-tree state: `slice-1-4-candidate.json`. HEAD alone does not
identify this initially dirty candidate. Source digest matched before and after final verification.
Documentation is outside the runner source digest; the enclosing Git commit binds it separately.

## Behavior

`/admin_execute_grant` lets the original proposer execute their verified approved proposal once.
Current global eligibility, durable capability, approval policy and approver authority, target
state, freezes, expiry and execution-time monetary ceilings are checked transactionally.
Wallet credits and issuance.admin debits, balanced postings, immutable before/after target
receipts, unique proposal execution, audit and transport outcome commit atomically.
Transport cleanup and distinct Discord interaction IDs cannot mint the same proposal again.
The private proposal preview displays execution state. There is no balance setter or implicit
issuance on approval. Existing operator, guild, user, channel, ceilings and alert policy are unchanged.

## Observed verification

- Full final pytest: **827 passed, 32 skipped, 1 warning**, 94.75 seconds.
- Ruff check: passed. Format check: 131 files already formatted. Pyright: zero errors/warnings.
- Fresh Alembic upgrade through 0007 and schema check: passed; no new upgrade operations.
- Git diff check: passed. Previously committed migrations and existing schema fingerprints
  are unchanged (Git checkout CRLF conversion was accounted for).
- Real SQLite tests cover concurrent business duplicates, retention replay, execution-time
  rolling cutoff and competition, authority/approval/freeze/expiry rechecks, missing/corrupt
  targets without repair, integer/version overflow, data-bearing migrations, rollback and
  cancellation after partial projections, retry, and post-commit alert/response loss.
- Reconciliation compares posting sums to each projection, balanced transaction totals, and
  issuance-derived minted supply to wallets. This is test evidence, not a deployment reconciliation.

Raw stdout/stderr and JUnit: `.gate-local/slice14-full-final.log` and
`.gate-local/slice14-full-final.xml`. Static results: `.gate-local/slice14-ruff-final2.log`,
`slice14-format-final2.log`, `slice14-pyright-final2.log`. Fresh migration log:
`.gate-local/slice14-fresh-migration-final.log`. Source snapshots use
`.gate-local/slice14-source-final-{before,after}.json`.

## Findings, failures and independent evidence

The builder and independent reviewer reproduced an incoming UPDATE/UPDATE OR REPLACE bypass
of sealed monetary history in 0006. New forward migration 0007 guards destination transaction
identity and correlation, preserving applied 0006. Recursive-trigger on/off, foreign-key-on,
ordinary append and replacement regression tests now pass. Failed probes are retained in
`.gate-local/slice14-update-replace-before.log` and
`.gate-local/slice14-independent-posting-bypass.txt`.

The first full run had one stale command-registration expectation: 826 passed, 32 skipped,
one failed. The assertion now includes admin_execute_grant. The original failed node and traceback
remain in `.gate-local/slice14-full.log` and its JUnit. Initial lint/type/build diagnostics were
also retained and corrected. No test stall occurred in the final run.

The independent reviewer ran **178 tests successfully**, with the existing Discord deprecation
and a cache-permission warning, then performed fresh cancellation and FK-on incoming-update
probes. Source digest matched before and after those probes:
`c708c4054a8a6d09907d2491341780ef8248d55af0244f5b02d09d679393f51f`.
Only tests/test_bot.py changed afterward to correct the command expectation; application and
migration source did not change. Evidence is `.gate-local/slice14-independent-final-tests.txt`,
`slice14-independent-final-junit.xml`, and `slice14-independent-final-probes.txt`.
An earlier independent run encountered 44 setup errors while migration/readiness edits were
concurrent; those tracebacks and JUnit are retained as `slice14-independent-initial-*`.
Successful independent tests do not substitute for the missing final independent verdict.

## Remaining gates and non-blocking limitations

Obtain final independent local acceptance for the final candidate before live development activation
or Slice 1.5. Native Linux evidence, all required native cases and artifacts, host operational gates,
and independent release acceptance remain necessary before production. The 32 Windows skips do not
satisfy those requirements. No provisioned Linux host was requested because the user deferred Linux.

Existing legacy monetary history is not certified or repaired by these upgrades. Guards seal
executed grants, not arbitrary old unsealed ledger records. The offline row-shape verifier is not
a full monetary reconciler. A separate campaign workflow is absent; separate proposal IDs represent
separate intent. Local structured alerts and the previously noted command-outcome logging severity
issue remain development limitations. The one full-suite warning is a discord.py deprecation.
Only one approved live tester exists, so two-person live exercises remain unavailable without an
explicit scope change. No live grant was issued or running session migrated during this work.
