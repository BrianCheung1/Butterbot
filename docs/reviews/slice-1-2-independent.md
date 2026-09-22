# Independent provisional local Slice 1.2 review

Reviewed 2026-09-22 on Windows. **Local determination: acceptable for the explicitly
authorized provisional development/testing scope. Formal verdict: SLICE 1.2: FAIL.**
Required native Linux foundation acceptance remains deferred. This does not authorize
production use, public mutations, or Slice 1.3.

## Exact reviewed candidate

Base commit: `e53641d7413fa82236481f5e0952b5a438e18ed3`, with the dirty Slice 1.2
implementation and tests. HEAD alone does not identify the candidate. Independently
captured source manifest: `.gate-local/slice12-independent-source.json`.
Its deterministic source SHA-256 is
`522258f6e7b00610fe7466aad9257d8b945d00a05b492869d7ee20adeae31fd8`.
This is the runner's Python/configuration/fixture source map, not a complete repository
archive. A final committed candidate should preserve this binding separately from
documentation updates and ignored local evidence.

During review the coordinating agent added development integration-test assertions for
the composed balance service before and after joining; runtime source did not change.
The reviewer reran the focused suite and adversarial probes against the final source.
Before/after hashes matched during the successful probe run. No implementation files
were edited by this reviewer. No Discord token, live request, or production database
was used.

## Findings and direct review

No demonstrated blocking defect was found in the final local implementation.

The reviewer inspected AGENTS.md, the roadmap's narrow authorization and Slice 1.2
requirements, relevant testing/decision documents, BalanceService, the Discord adapter,
read-snapshot changes, normal/development composition, and the focused tests. The
query selects only the caller's player, then wallet/projection, within a single explicit
deferred transaction. It does not invoke creation, repair, eligibility, transport replay,
or ledger operations. Integer bounds are checked and inactive identities reveal no
balance. Missing identities return unjoined; missing wallets return unavailable;
missing projections raise an invariant error converted to a private sanitized response.

The read-snapshot factory changes transaction acquisition from BEGIN IMMEDIATE to BEGIN
while sharing lifecycle registration, bounded admission, path validation, commit identity
checks, cancellation/cleanup, and shutdown ownership. Direct review found no new bypass
of those shared mechanisms. The factory is intentionally not a database-enforced write
sandbox: trusted future callers could invoke repository writes. This is documented and
non-blocking for the inspected balance service, which uses only reads. The shared
four-slot admission limit remains a possible load-related availability constraint.

The Discord command has no target-user parameter, takes identity from the interaction,
privately defers before the application call, and privately responds afterward. Errors
omit raw exception messages and balances. Cancellation propagates and failed delivery
does not retry the query. Development registration uses the existing exact guild/user/
channel scope and disabled default prefix help. Normal composition keeps mutation
eligibility separate from this safe read.

## Reviewer-owned verification

Final command:

```text
.venv/Scripts/python.exe -m pytest -q -ra -o faulthandler_timeout=60 tests/test_balance.py tests/test_balance_command.py tests/test_development.py tests/test_join.py tests/test_composition.py --junitxml=.gate-local/slice12-independent-final-junit.xml
```

Observed **86 passed, one cache-write permission warning, 5.39 seconds**, exit 0.
No focused test failed or stalled. Stdout and raw JUnit are retained as
`.gate-local/slice12-independent-final-tests.txt` and
`.gate-local/slice12-independent-final-junit.xml`. The initial run also passed 86
tests in 5.89 seconds; it preceded the final development integration assertions.
The coordinating agent's full suite/static checks are separate observations.

Fresh adversarial probes, beyond rerunning the author's assertions, established:

1. SQLAlchemy engine tracing for joined and unjoined balance requests observed deferred
   BEGIN and SELECT/connection-local PRAGMA statements, with no DML, DDL, or BEGIN
   IMMEDIATE. Existing complete-database dump tests additionally passed.
2. A real independent SQLite connection committed a player lifecycle change and a
   balance change between the query's player and wallet reads. The in-flight query
   returned the coherent earlier active/zero snapshot; the next returned inactive.
3. A real runtime shutdown cancelled an intentionally blocked active read, completed
   cleanup, and allowed a successor runtime to acquire process ownership. This is local
   cancellation/ownership evidence, not native SIGTERM evidence.

Probe source: `.gate-local/slice12-independent-probe.py`; successful output:
`.gate-local/slice12-independent-probe-rerun.txt`. The first probe invocation reached
all three passing assertions but failed temporary-directory cleanup with WinError 32.
The reviewer identified the cause in the probe itself: `with sqlite3.connect(...)`
commits/rolls back but does not close that fixture connection. Wrapping it in
`contextlib.closing` resolved cleanup; the rerun passed and confirmed unchanged source.
The original complete traceback is retained in
`.gate-local/slice12-independent-probe.txt`. It is not evidence of a product resource leak.

## Limitations and release gate

No genuine Discord delivery or native Linux filesystem, capability, or SIGTERM behavior
was exercised by this review. The snapshot's consistent point-in-time balance can become
stale immediately after its transaction; this is ordinary query semantics. Read activity
shares admission/drain resources with writes. No new schema or migration was introduced.

The user-authorized exception permits provisional local Slice 1.2 work and testing.
Formal acceptance still requires complete native evidence for the final dependent
candidate, all required verification, and independent evidence review. Windows results
and the successful local probes cannot replace that evidence.

**SLICE 1.2: FAIL — native acceptance outstanding; local review found no remaining
demonstrated blocker within the authorized provisional scope.**
