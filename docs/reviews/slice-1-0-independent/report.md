# Independent Slice 1.0 release gate review

Reviewed 2026-09-14. **Final verdict: FAIL. Slice 1.1 remains blocked.**

This review found four reproducible code/gate defects, in addition to absent native Linux evidence. The candidate is suitable for diagnostic Linux runs, but is not structurally ready for an acceptance run whose passing report can be trusted.

The reviewed working tree was already dirty and included untracked Slice 1.0 implementation files. HEAD was `15882168f1fe640ee667d196b3c588ea46f993b9`; HEAD alone does not identify this candidate. The accompanying `candidate-manifest.json` records 99 extant candidate files, their SHA-256 hashes, status, and host. Its deterministic source-map digest is `c1af86491202df78d089e7d9bb697eb2ba56b23b8dcb272990bb64bad7a6be64`. Review artifacts are excluded from that digest. No implementation or existing tests were changed by this review.

## Blocking findings

### B1 — P1: REPLACE bypasses aggregate ownership protection and hides a missing wallet

Affected: `migrations/versions/20260914_0002_aggregate_identity.py:12-28`, especially the account trigger at line 17; historical insert/delete sentinel triggers in `migrations/versions/20260825_0001_slice_1_0_baseline.py:31-49`; startup sentinel read in `src/butterbot/infrastructure/persistence/readiness.py:149`.

The new triggers protect UPDATE only. SQLite INSERT OR REPLACE performs a conflict deletion and insertion; its implicit delete does not fire delete triggers with recursive_triggers=0. That is the observed connection setting. Foreign keys remain ON throughout this reproduction.

Start with two players, each with a complete wallet/projection. Wallet A belongs to player 1, wallet B to player 2. Within one explicit transaction:

```sql
DELETE FROM economy_account_balances; -- two fixture projections
DELETE FROM economy_accounts WHERE id = :wallet_b;
INSERT OR REPLACE INTO economy_accounts
VALUES (:wallet_a, :player_2, 'wallet', 'coin', NULL, 1);
INSERT INTO economy_account_balances VALUES (:wallet_a, 'wallet', 25, 0);
DELETE FROM operations_integrity_violations;
COMMIT;
```

The fixture starts with A=25 and B=0, so the sequence preserves the aggregate amount. The ordinary deletion of B records player 2's missing wallet. Replacing A clears that sentinel when A is inserted for player 2, but never records player 1's missing wallet. Restoring A's projection clears its account sentinel. The final sentinel deletion succeeds, foreign_key_check returns no rows, and player 1 has no wallet. The complete release schema and head remain unchanged.

Observed: `create_database_runtime` accepts the database at `20260914_0002`. The stopped-service verifier independently rejects it with `HistoricalVerificationError: invalid_persisted_state`. A direct replacement while a projection still references the account was also attempted and correctly failed the restrictive FK; the successful reproduction explicitly removes/restores that projection.

Production consequence: raw SQL can move account ownership and leave an incomplete player aggregate invisible to startup, despite the asserted authoritative sentinel contract. This is not an exposed Discord exploit: the problem is the required database backstop and readiness guarantee.

Required remediation: prevent replacement-based identity changes at the database boundary, or otherwise make all supported conflict/delete/insert paths preserve the sentinel and immutable identity contract. Do not rely solely on callers avoiding REPLACE or on an unverified connection setting. Add a new migration and update the manifest rather than editing applied revisions.

Required evidence: regression from a complete starting state, FK enforcement ON, REPLACE and UPSERT/conflict variants, relevant recursive-trigger settings, rollback/savepoints, and both startup/offline verification. Preserve existing financial rows and demonstrate that replacement cannot silently transfer an existing identity.

Reproduction and observed output: `sqlite-probe.txt`, `sqlite-results.txt` (`REPLACE_STATE`, `REPLACE_CHECKS`).

### B2 — P1: Schema filtering excludes legal, uncontracted application triggers

Affected: `src/butterbot/infrastructure/persistence/readiness.py:225`.

`name NOT LIKE 'sqlite_%'` treats underscore as a one-character wildcard, not a literal underscore. Consequently it excludes legal application names beginning with `sqliteX`, as well as actual SQLite internal names. On a fresh head database this ordinary DDL succeeds:

```sql
CREATE TRIGGER sqliteXuncontracted BEFORE INSERT ON players
BEGIN SELECT RAISE(ABORT, 'uncontracted behavior'); END;
```

Both startup and the stopped-service verifier accept this altered schema. The added trigger can change application behavior while all release manifest hashes appear unchanged.

Production consequence: the promised complete schema contract fails open for extra objects; a stale or accidentally modified database can contain unreviewed executable trigger behavior.

Required remediation: filter only the literal reserved internal prefix, using an escaped LIKE pattern or a correctly specified case-sensitive prefix comparison, and compare the complete remaining object set. Test legal near-prefix names for tables, indexes, views, and triggers.

Required evidence: the DDL above and other legal near-prefix objects must fail both entry points without scanning business history. Ordinary internal autoindexes must remain accepted.

Reproduction/output: `sqlite-probe.txt`, `sqlite-results.txt` (`WILDCARD ['accepted', 'accepted']`).

### B3 — P1: Native runner accepts missing required coverage

Affected: `benchmarks/native_linux_gate.py:72-90` and `:195-204`.

Only the effective-capability test has a collection requirement. Other native test identities are never checked. A JUnit document containing just a passing capability testcase, with pytest exit status zero, makes `main()` return 0 and emit `result: passed`. This was reproduced through the real runner policy with a simulated subprocess/JUnit result, not by running native Linux tests.

Independent collection found 16 native cases: seven native-layout cases, five marked process-lock cases, and four SIGTERM cases. An 80-case policy matrix varied each case through pass/failure/error/unrelated-skip/missing while the remaining cases passed. Failure, error, and unrelated skip failed for every case. Missing capability failed; missing each of the other 15 cases passed. Even missing namespace collection passes, although the exception permits a specifically justified skip, not absence of collection.

A practical trigger is a narrowed pytest selection supplied through inherited PYTEST_ADDOPTS, a lost marker, or collection/plugin configuration. Checking only a successful pytest exit does not establish complete required coverage. Matching capability by bare testcase name also lacks full module/node identity validation.

Production consequence: a successful native report does not prove required shutdown, ownership, filesystem, or lock behavior was exercised.

Required remediation: freeze/reconcile the complete required node set, including parameterized SIGTERM phases; reject missing/duplicate/mismatched cases and inconsistent JUnit accounting; prevent inherited options from silently narrowing the gate. Require an actual passing result for every mandatory case and explicit collection/accounting for the optional namespace case.

Required evidence: the complete pass/fail/error/skip/missing matrix must fail everywhere except actual pass and the exact permitted namespace denial. Preserve selected node IDs, per-test outcomes and raw output. Exercise narrowed selection and malformed/incomplete reports.

Reproduction/output: `native-policy-probe.txt`, `native-policy-results.txt`. The capability-only result was `(0, 'passed')`. All policy simulations are Windows unit-level evidence, not native proof.

### B4 — P1: Namespace skip producer mislabels unrelated failures as host denial

Affected: `tests/test_native_linux_gate.py:567-571` and `benchmarks/native_linux_gate.py:23-26`.

The namespace test turns every subprocess exit outside {0,23} into a skip prefixed with the approved host-denial text. The runner checks that prefix. This accepts more than a genuine denied unshare operation.

Independent reproduction invoked the actual namespace test function with a simulated subprocess exit 1 and stderr `Traceback: application import failed`. It emitted the host-denial skip, and `_allowed_skip` returned True. A Python import failure after namespace creation, a utility execution failure, or other unexpected child failure can therefore become an allowed omission of coverage.

Production consequence: a native report can pass without establishing the namespace rejection behavior, for a reason explicitly forbidden by the gate specification.

Required remediation: distinguish failure to create a namespace from failure of the validation child. Permit a skip only after establishing the documented host denial; fail unexpected exits, tooling failures, and child exceptions. Avoid classifying by broad return-code range or a reason prefix generated for arbitrary errors.

Required evidence: real denied unshare case plus unit matrices for missing utility, permission denial, unsupported/tool errors, child import/runtime failure, and wrong probe result. Only actual documented host denial may be an allowed skip. Missing unshare and capability/setpriv skips currently fail the runner and must continue to fail.

Reproduction/output: `native-policy-results.txt` (`NON_DENIAL_SKIP`, `RUNNER_ALLOWS_NON_DENIAL True`).

### B5 — P1 release prerequisite: Current native Linux evidence is absent

Affected evidence contract: `docs/testing.md:136` onward and `docs/operations.md` September gate requirements; claimed outstanding requirement in `docs/slice-1-0-remediation-report.md`.

The repository evidence directory contains only `sqlite-capacity-2026-08-31.json`. Searches of the project and supplied visualization workspace found no current native report, raw JUnit/log bundle, or exact-candidate Linux source binding. The inaccessible pytest cache is not claimed as inspected. No external Linux host or evidence location was provided. The remediation report explicitly says native tests were not run; that is consistent with, but not the basis of, this determination.

The observed host is Windows 11, Python 3.13.15, SQLite 3.50.4. Windows skips and this review's mocked runner probes are not Linux evidence. Existing capacity evidence is a different gate and cannot substitute.

Production consequence: the required kernel/filesystem/identity/capability/shutdown assumptions remain unvalidated on the required platform.

Required remediation/evidence: after fixing code blockers, run on the provisioned native Linux host and retain the exact source manifest or immutable commit plus known working-tree state, kernel/distro/architecture, mount/filesystem details, service/admin UID/GID and groups, capability tooling/state, selected tests, raw results, runner result, complete mandatory accounting, and justified skip accounting. Bind the evidence to the final repaired candidate, not this older manifest. WSL or summaries do not satisfy this review request.

## Remediation determinations and implementation review

| Previous blocker | Determination |
| --- | --- |
| Aggregate identity update bypass | Ordinary UPDATE paths remediated; aggregate contract still fails through REPLACE (B1). |
| Incomplete same-head schema validation | Manifest covers baseline objects, but near-prefix extra objects escape validation (B2). |
| Mutable baseline DDL dependency | Resolved for project runtime definitions in the tested rebuilds. |
| Native Linux evidence absent | Still unresolved (B5). |
| Effective-capability skip accepted | Specific capability requirement is fixed; broader native policy remains unsafe (B3/B4). |

The independently enumerated head schema has 8 tables (including Alembic), 3 explicit indexes, and 11 triggers: 22 contract objects. This covers both retention/ledger-order indexes and the sentinel index, all baseline table definitions, eight sentinel triggers and three new identity triggers. Implicit uniqueness is represented in table DDL. Dropping each explicit index/trigger and changing each table's CREATE casing was rejected by both entry points. Additional real-file mutations weakened a ledger CHECK, correlation UNIQUE, and posting FK; all were rejected. Existing tests additionally exercise transport/ledger weakening and a baseline schema stamped at current head. A normal extra table is rejected; B2 is a specific exception to that protection.

Whitespace-only SQL changes outside literals were accepted, consistent with normalization; this is normalized, case-sensitive comparison, not byte-exact SQL comparison. Fresh migration and downgrade/re-upgrade DDL match SQLite's stored form. Normalization splits all whitespace without parsing SQL literals/comments; preserve this as a maintenance limitation if future schema definitions introduce whitespace-sensitive literals. No additional constraint bypass through that normalization was demonstrated here. Schema comparison is bounded by sqlite_master object count. The transport incomplete-claim predicate uses the retention index; startup does not scan ledger/posting history. The offline verifier intentionally scans historical state after the same readiness contract.

All nine protected fields rejected direct changes. Independent probes exercised no-op assignments, multi-row updates, explicit transactions, ABORT behavior, savepoint rollback/release, and outer rollback; earlier successful statements remained in the transaction until rollback. Existing remediation tests also cover multi-column assignments and active-sentinel deletion. Account classification/currency/owner/system identity and projection membership are covered for UPDATE. Timestamps, lifecycle state and balance/version are not identity fields. This coverage does not imply arbitrary raw ledger/history edits are prevented: Slice 1.0 provides constrained structure and application ownership, not a general SQL authorization system. The demonstrated aggregate completeness failure is narrower and directly violates the sentinel guarantee.

The baseline revision imports only standard-library typing support, SQLAlchemy and Alembic; its project-specific DDL helpers and trigger text are local. Alembic env imports runtime metadata for autogenerate, but the explicit revision does not derive upgrade DDL from it. Independently replacing runtime Base.metadata with empty metadata, poisoning runtime trigger/index definitions and replacing the release manifest produced byte-identical baseline sqlite_master rows. Existing frozen-snapshot tests also passed. The later revision adds its triggers separately.

Migration 0002 performs its sentinel INSERT SELECT operations before creating triggers. It creates no account, balance, or economic value. An independent legacy-hole fixture upgraded to a protected sentinel and startup rejected the incomplete player, retaining the original balance rows. Injecting a duplicate trigger made upgrade fail; reconstructed sentinel inserts and the revision update did not commit. Removing the injected conflict allowed retry and safe rejection of the hole. This supports transactional rollback for the exercised SQLite DML/DDL path, not a power-loss proof. Alembic's log still identifies SQLite DDL as non-transactional. Upgrade is a versioned operation, not an independently idempotent function; repeated direct invocation is not promised. Downgrade removes new triggers without deleting financial data or synthesizing repairs, and re-upgrade succeeds. Partial or stale revisions are rejected by readiness. Do not infer that 0002 can reconstruct historical ownership facts or repair arbitrary malformed financial history.

The tracked diff and new persistence/migration/test files were inspected directly. Existing assertion changes for head/identity errors are consistent with the new revision, and new negative coverage is substantive, though incomplete as above. No Slice 1.1 command was added: the installed Discord extension remains ping, with no durable outcome persistence or monetary mutation command. There is no current command persisting attacker-sized outcome structures.

## Non-blocking findings and residual risk

- The reported intermittent pytest failure/stall did not reproduce in two full runs or the focused rerun. The second full run enabled a 60-second faulthandler dump threshold and completed in 40.14 seconds. Review of transaction/shutdown cancellation and retained-resource paths found no additional demonstrated locking defect. Without the original failed node or traceback, the cause cannot be assigned to SQLite, concurrency, subprocess cleanup, or terminal behavior. Keep the event open as residual risk; capture unbuffered logs, failed node and stack dump if it recurs. The reproducible cache-write warning is not evidence of the earlier failure's cause.
- Capacity validation still trusts stored acceptance booleans for some metrics. The change adds several independent checks, but does not fully recompute all acceptance dimensions. No new reason makes this previously deferred weakness gate-critical; this review did not run the full capacity workload.
- Outcome byte/depth/collection limits are explicitly required before future input-derived payload persistence in `docs/decisions.md`. With ping as the only current command, deferral remains non-blocking.
- The runner report alone does not bind source identity and deletes its temporary JUnit file; a future evidence bundle must preserve raw results and candidate binding separately or improve the runner. Malformed XML raises instead of yielding a false success, but it may fail to write a useful final failure report. B3 addresses incomplete but parseable evidence that actually passes.

## Verification observed

These are reviewer-executed results, not copied author claims. Commands used `.venv/Scripts` executables from the repository root.

| Command / probe | Observed result |
| --- | --- |
| `ruff check .` | Passed. |
| `ruff format --check .` | Passed; 85 files already formatted. |
| `pyright` | 0 errors, 0 warnings, 0 informations. |
| `pytest -q -ra` | 405 passed, 32 skipped, 1 warning; 34.27s. |
| `pytest -q -ra -o faulthandler_timeout=60` | 405 passed, 32 skipped, 1 warning; 40.14s. |
| `pytest -q -ra tests/test_release_gate_remediation.py tests/test_migrations.py tests/test_slice_1_0_gate_findings.py` | 111 passed, 1 warning; 8.20s. |
| `pytest --collect-only -q -m native_linux_kernel` | 16/437 selected, 421 deselected. Collection only, not kernel execution. |
| `alembic upgrade head` | Passed on a fresh unique temporary database using explicit BUTTERBOT_DATABASE_PATH. |
| `alembic check` | Passed; no new upgrade operations detected. Also passed via API in the independent probe. |
| `git diff --check` | Passed; existing LF/CRLF notices only. |
| `sqlite-probe.txt` | Nine-field/savepoint checks, 22-object drift checks, constraint mutations and cycles passed their assertions; reproduced B1/B2. |
| `migration-probe.txt` | Runtime-independence, injected failure rollback/retry and legacy-hole checks passed. |
| `native-policy-probe.txt` | Completed 80 policy combinations plus capability-only and non-denial probes; reproduced B3/B4. No Linux behavior claimed. |

The 32 skips comprise seven native-layout tests, seven Linux process-lock tests, four SIGTERM cases, thirteen Linux storage-permission cases, and one Windows-denied symlink fixture. The warning is inability to write `.pytest_cache/v/cache/nodeids` (WinError 5). The 16-test native selection is intentionally narrower than all Linux-named tests; mocked storage tests are not kernel proof.

Probe sources and observed stdout are retained beside this report. Re-run a probe on this host using `Get-Content -Raw <probe.txt> | .venv/Scripts/python.exe -` from the repository root. They create isolated temporary databases and policy fixtures. Native policy reports use simulated subprocess results explicitly and cannot be submitted as release evidence.

Repository-provided evidence: capacity JSON and frozen baseline snapshot were present; their associated tests passed. The author's local verification and prior intermittent event remain claims in the remediation report; this report distinguishes its own runs above. It does not certify exhaustive fault injection or unavailable Linux behavior.

## Native evidence determination

No current valid native Linux evidence was found in the supplied workspace, and none is bound to the exact reviewed candidate. The runner policy defects must be repaired before its success can establish coverage. Even absent B1-B4, the missing evidence alone prevents acceptance.

## Final verdict

FAIL

Slice 1.1 is not authorized. Fix B1-B4, obtain complete native evidence for the repaired candidate, and repeat the independent gate.
