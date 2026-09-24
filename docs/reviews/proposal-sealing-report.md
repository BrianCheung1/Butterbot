# Proposal sealing remediation — 2026-09-24

Formal release verdict: **FAIL**. Native Linux evidence remains absent and deferred by the user.
No production enablement or grant execution is authorized by this report.

## Candidate and scope

Base commit: `ac6c4403e3b2b70b010e8aa73c72391efd3a9d41`.
Tested source digest: `8d9bc7691014ada92e314fcbabad6164753e124048c90cf968bbf3d5592795a7`.
The deterministic per-file manifest and observed dirty tree are in
`proposal-sealing-candidate.json`; base HEAD alone does not identify this candidate.
Source was unchanged throughout the final full test run; the manifest was captured afterward
and independently checked. Documentation is outside the runner source digest.

Migration 0005 seals target membership and conservatively marks all legacy scopes unverified.
No earlier migration changed. Application approval refuses unverified scopes; previews expose
that state. Fresh submissions seal atomically. No grant executor was added, and no running
Discord session or existing local database was upgraded.

## Observed local verification

- Full pytest: **765 passed, 32 skipped, 1 warning**, 74.89 seconds.
- Ruff check, format check (125 files), Pyright (zero errors/warnings), git diff check: passed.
- Fresh Alembic upgrade to 0005 and autogenerate check: passed, no new upgrade operations.
- Focused initial regression/migration suite: 97 passed.
- Before the fix, all three original append regressions failed as expected; retained in
  `.gate-local/proposal-sealing-before.log`.
- New tests cover pending/approved/applied append attempts, conflict variants, recursive
  triggers on/off, immutable seals, unverified legacy approvals, invalid/missing seals,
  and whole-transaction rollback on injected seal failure.

Raw full stdout/stderr and JUnit: `.gate-local/proposal-sealing-full.log` and
`.gate-local/proposal-sealing-full.xml`. Static-check outputs use
`.gate-local/proposal-sealing-*-final.log`. Initial lint/type findings and their output were
retained and corrected. These Windows results are not native Linux acceptance evidence.

## Remaining conditions and risks

Native gate execution on the exact final candidate, all 16 cases and raw artifacts, and
independent release acceptance remain required before production. Linux remains deferred.
Legacy proposals must be resubmitted for further approval. Historical replay can return an old
approved/applied result without new effects; future execution must verify current sealed scope,
authority, restrictions, expiry, business uniqueness and monetary limits in its transaction.
The one warning is discord.py's existing positional-count deprecation. Local-only logging and
the previously documented telemetry severity issue remain non-blocking development limitations.

## Independent review

Local proposal-sealing remediation: **PASS**. The independent reviewer found no demonstrated
blocker, ran 57 focused tests successfully, and confirmed the exact source digest before and
after execution. One cache-permission warning was observed. Raw evidence is retained as
`.gate-local/proposal-sealing-independent-final-tests.txt` and
`.gate-local/proposal-sealing-independent-final-junit.xml`. This local verdict does not replace
the formal release FAIL above.
