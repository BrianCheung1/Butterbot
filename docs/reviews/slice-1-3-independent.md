# Independent provisional local Slice 1.3 review

Reviewed on 2026-09-23. **Formal verdict: SLICE 1.3: FAIL.** Explicit approval
of bootstrap identities, monetary policy and alert destination is outstanding; native
Linux release acceptance also remains deferred. Synthetic test policy is not operator
approval. No live bootstrap, token use, or production access was performed by this reviewer.

The local code is suitable for continued synthetic testing, with no demonstrated
blocking service-path defect found. It is not ready for live bootstrap or slice
completion while policy approval is pending. This review authorizes no later slice.

## Candidate identity and scope

Base HEAD is `fe8c99db95878d38abf00455ed5cb7f3ed632075`; the reviewed Slice 1.3
implementation is a dirty working tree, including untracked new source and migration.
The final independently captured source-map SHA-256 is
`379562f982ab346c78016bdbc57e2d5c22dafaef6952f8ba68ee4219d2a620e7`.
Per-file hashes and git state are in
`.gate-local/slice13-independent-final-source.json`. This is the native runner's
Python/configuration/fixture source map, not a complete documentation archive.
HEAD alone is insufficient. Final probes confirmed unchanged source before/after.

The reviewer directly read the safety service/repository, new migration and constraints,
audit triggers, join restriction check, unit-of-work integration, composition,
development/bootstrap/configuration code, Discord adapter, and relevant roadmap,
decision and testing contracts. No source or migration was edited by this reviewer.
Applied migration 0004 remained byte-identical during review, SHA-256
`e132541173cfad77ff1021da3afdaa5589b4081de11cf25d24164cd39acc1d64`.

## Findings

The independent review found no demonstrated authorization or transactional bypass in
the current service paths. Durable capabilities are checked before administrative replay;
approval checks distinct approver, expiry, proposer authority, policy limits and target
freeze state. Immutable audit receipts prevent replay after transport cleanup from
regranting a revoked capability. Grant proposals never issue coins in this slice.

One demonstrated nonblocking limitation requires treatment before Slice 1.4 executes
approved grants: raw SQL can append a new target row to an already approved proposal.
Existing target rows cannot be updated, deleted or replaced, but the membership set is
not sealed against additions. A fresh independent probe appended a second target to an
approved single-target grant. There is no current exposed service path to do this and
no grant execution, so this does not establish a present money/authorization exploit.
Future execution must verify or seal the approved scope and recheck authorization,
freezes, limits and business uniqueness. Any schema hardening requires a new migration;
applied revision 0004 must remain unchanged.

The final candidate includes the coordinating reviewer's audited `/admin_proposal`
preview. Direct review confirmed durable `proposals.approve` authorization before
payload disclosure, audit of both denial and successful inspection within the owning
transaction, and runtime storage-safety checks. The private response includes stored
operation, targets, amount, reason, proposer and expiry, escapes Markdown, and disables
mentions. The approver can inspect the exact proposal before approving it.

The schema/repository uses bounded target counts and integer amounts; Python summation
avoids SQLite aggregate overflow before the ceiling comparison. Shared BEGIN IMMEDIATE
transactions serialize admission, capability changes, rolling reservations and approval.
Audit failures roll back the action. Alerts occur after commit; local logging is not a
reliable remote delivery guarantee. Bootstrap is explicit and single-use, and normal
startup does not restore revoked capabilities. The development launcher may bootstrap
only explicitly configured identities in a freshly allocated session.

Policy limitations remain explicit: the suggested numeric limits, operators and local
alert destination have not been approved. The existing single-user development scope
does not permit a second live approver without separate scope authorization. Distinct
Discord IDs establish distinct application actors, not independently verified humans.
None of these synthetic fixtures establish approved live operators.

## Reviewer-owned verification

The initial focused run covered safety, join and balance tests: **58 passed, one existing
cache-write permission warning, 8.84 seconds**, exit 0. Retained stdout/JUnit are
`.gate-local/slice13-independent-tests.txt` and
`.gate-local/slice13-independent-junit.xml`.

Final focused command, after proposal preview and additional configuration/migration
coverage were present:

```text
.venv/Scripts/python.exe -m pytest -q -ra -o faulthandler_timeout=60 tests/test_safety.py tests/test_safety_command.py tests/test_safety_config.py tests/test_join.py tests/test_balance.py tests/test_migrations.py --junitxml=.gate-local/slice13-independent-final-junit.xml
```

Observed **141 passed, two warnings, 15.01 seconds**, exit 0. No test failure or stall
occurred. Warnings were the existing pytest-cache permission denial and installed
discord.py's positional `re.sub` count deprecation in Markdown escaping. Final stdout
and raw JUnit are `.gate-local/slice13-independent-final-tests.txt` and
`.gate-local/slice13-independent-final-junit.xml`. The coordinating agent's full suite,
Ruff, formatting, Pyright and standalone migration checks are separate observations.

Fresh probes additionally verified that two concurrent 60-unit proposals under a
100-unit rolling ceiling yield one pending proposal and one limit rejection; approval
creates no ledger transaction; revoking the approver blocks replay of an earlier
approval both before and after transport cleanup. A further injected failure on the
second target of a bulk freeze rolled back the first target, proposal transition and
transport claim; retrying the same request succeeded. They also demonstrated the target
append limitation above. Final probe source/output are
`.gate-local/slice13-independent-probe.py` and
`.gate-local/slice13-independent-probe-final.txt`. These use temporary databases, synthetic
operators and synthetic policy, not native Linux or approved deployment evidence.

## Final determination

### Final source addendum (coordinating agent)

The reviewer subsequently captured `.gate-local/slice13-independent-final2-source.json`,
with source SHA-256
`1742eb9f5bc54db85e1001e4f399c0c6b7c7ed1c8e2dae93bd4729305a363b8f`.
A per-file comparison shows only the addition of `tests/test_safety_migration.py` since
the 141-test review above; runtime source and migration 0004 are unchanged. The reviewer
ran those three data-bearing migration cases independently: **3 passed, one cache
permission warning, 0.77 seconds**. Raw output/JUnit are
`.gate-local/slice13-independent-migration-tests.txt` and
`.gate-local/slice13-independent-migration-junit.xml`. Its agent turn then ended with a
usage-limit error before updating this report. The coordinating agent inspected these
artifacts and added this source-binding clarification; it does not relabel the earlier
141-test run as having included the newly added file.

**SLICE 1.3: FAIL.** Local service and adapter review found no remaining demonstrated
blocking defect within synthetic testing scope. Required explicit operator/policy/alert
approval and valid native Linux evidence for the final dependent candidate are absent.
Do not bootstrap live identities, declare release acceptance, or proceed to Slice 1.4
on the basis of this review. Address the approved-target membership limitation before
grant execution and preserve all execution-time safety checks described in the decisions.


## Subsequent operator-policy approval (coordinating agent)

After this independent review, the user explicitly approved the proposed disposable local
policy: existing tester as initial operator, threshold 100, proposal ceiling 1,000, rolling
24-hour ceiling 10,000, and local structured logs. This resolves the policy-approval blocker
for local activation only; the review's earlier pending-policy statements describe its original
review time. No production authorization or second-operator scope was granted. Runtime/test
source remains the final addendum's reviewed hash. Formal FAIL remains due to native acceptance.
