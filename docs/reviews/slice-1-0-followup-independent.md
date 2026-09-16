# Independent follow-up code review of Slice 1.0

Reviewed 2026-09-16 UTC on Windows. **Release verdict: FAIL pending native Linux
evidence.** This is an independent review of the four code remediations, not native
release acceptance. No implementation or historical migration was edited by this review.

## Candidate binding

The reviewer independently called the native runner's source identity function after
examining its implementation. All file hashes matched
`slice-1-0-candidate-0003.json`, with no added, removed, or changed source-map entries.
The deterministic source-map SHA-256 was
`aa0d0bcf05fb8ebc48f6e5127b1ec439b02fee878e8e7212cdce5a36f83cb860`.
HEAD was `15882168f1fe640ee667d196b3c588ea46f993b9`; the working tree was dirty,
so HEAD alone is not the reviewed candidate. This binding includes the unchanged
0001 and 0002 migration bytes recorded in candidate 0003. Review documents and test
output are outside the runner's source-map scope. A subsequent candidate commit or
source modification must be bound separately by the final release report.

## Code findings

No remaining demonstrated B1-B4 blocker was found in the reviewed source.

| Finding | Independent determination |
| --- | --- |
| B1: SQLite replacement bypass | Resolved for the reported aggregate identity/ownership paths. Migration 0003 adds BEFORE INSERT guards for player primary/Discord keys, account primary/owner-kind/system keys, and balance primary keys. RAISE(ABORT) precedes conflict deletion, regardless of recursive triggers. Repository retries read under the existing writer transaction. The historical migrations remain separate and unchanged. |
| B2: Near-prefix schema filtering | Resolved. The literal `sqlite_` GLOB prefix replaces LIKE's wildcard underscore. Extra table/index/view/trigger tests exercise lowercase, mixed-case, and numeric near-prefix names through both startup and offline verification. |
| B3: Missing native test coverage | Resolved. The inventory identifies 16 complete module-qualified cases, including all four SIGTERM outcomes. Parsing rejects missing, extra, duplicate, failed, errored, ambiguous, or incorrectly skipped cases and inconsistent suite counts. The gate removes inherited pytest selection/plugin options and explicitly loads its asyncio plugin. |
| B4: False namespace-denial skip | Resolved in the reviewed producer and policy. Only exit 1 with empty stdout and exact C-locale util-linux EPERM/EACCES stderr qualifies. Child startup prints before application imports; child failures cannot acquire the approved skip reason through the previous broad exit-code rule. Missing unshare fails. |

The reviewer read the runner, native fixture/probes, replacement migration,
repository changes, schema query, policy tests, replacement tests, and the relevant
testing/operations/decision contracts. The policy matrix covers all 16 cases across
pass/failure/error/skip/missing, and includes malformed accounting and source-change
rejection. Those simulations are unit evidence only.

## Reviewer-executed verification

Command, using the repository Windows Python 3.13 environment:

```text
.venv/Scripts/python.exe -m pytest -q -ra -o faulthandler_timeout=60 tests/test_aggregate_replacement.py tests/test_native_gate_policy.py tests/test_release_gate_remediation.py --junitxml=docs/reviews/slice-1-0-followup-independent-junit.xml
```

Observed: **198 passed, 1 warning in 11.86 seconds**, exit code 0. No test failed or
stalled. The warning was the existing permission denial writing pytest's node cache.
Raw output is `slice-1-0-followup-independent-tests.txt`; raw JUnit is
`slice-1-0-followup-independent-junit.xml`. These are explicitly Windows focused-test
artifacts and must not be presented as native Linux evidence. This reviewer did not
independently run the full suite, Ruff, formatting, Pyright, or an external Linux gate;
their current results belong in the coordinating release report.

## Remaining release blocker and evidence review requirements

B5 remains open: no actual native Linux run was supplied to this reviewer. The final
review must independently compare the retained JSON and raw JUnit/stdout/stderr/layout
against the exact final candidate, including source state before and after execution.
It must account for exactly 16 cases with actual passing mandatory outcomes, including
effective-capability rejection and active/waiting/committing/fail-stop SIGTERM coverage.
Only the exact pre-child namespace host-denial exception may skip. Host distro/kernel,
architecture, ext4/XFS mount, controller and service identities, capabilities, and the
provisioned isolated storage parent must be independently checked.

The runner's `passed` value alone is insufficient. In particular, its source map
covers Python files plus selected configuration/fixture files rather than every
repository artifact; preserve a complete release manifest and known git state as well.
Before/after hashing does not prove absence of transient modifications restored during
the run, so the release execution must take place in an isolated candidate checkout
without concurrent editing. These are evidence-handling limitations, not newly
demonstrated application defects. The prior intermittent stall remains unexplained;
this focused run did not reproduce it.

**FAIL. Slice 1.1 remains blocked until complete valid native evidence and all required
verification support the exact final candidate.**
