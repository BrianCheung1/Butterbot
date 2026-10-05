# Slice 1.5 provisional local implementation — 2026-09-30

Local status: **PASS**, independently accepted 2026-10-05 after downgrade remediation.
Native production/release verdict remains FAIL/deferred.
See `slice-1-5-independent-acceptance.md` for the final verdict and closed finding.

## Live development smoke — 2026-10-05

The user requested activation after local acceptance. Fresh disposable session `join-8i0htzey`
connected with the existing guild/user/channel restrictions. The tester explicitly delegated
correction authority through the command workflow, issued a 10-coin grant, corrected 4 coins,
and reported a private history showing +10/balance 10 followed by -4/balance 6. The original
transaction was `fa000686-0588-4f43-b7e2-4480689e974d`; the correction was
`3dfddaa1-b997-4a6c-b8a8-76eb72cf2eae`. The tester then confirmed the repeated correction worked
as expected. Retained logs independently show `corrected`, history/balance reads, and
`already_corrected` on the second request. Earlier invalid-input attempts produced no success.
Evidence: `.gate-local/development-20261005.stderr.log`; user-reported display is in this chat.
This supersedes the pre-activation statements in the implementation narrative below. It is a
restricted live development smoke, not Linux production acceptance.

## Downgrade remediation addendum

After the first 904-pass full run, the coordinator probed downgrade compatibility and the
independent reviewer confirmed a mismatch: the unused correction schema downgraded to equivalent
capability rules but a quoted table name and different constraint order failed the old release's
exact schema fingerprint. Local acceptance was withheld. The regression was reproduced before
the fix; logs are `.gate-local/slice15-downgrade-{probe,regression-before}.log` and the independent
`.gate-local/slice15-independent-downgrade-before.log`.

The rollback path now explicitly recreates the original unquoted table with the frozen prior
constraint order and copies capabilities back. A full normalized-schema comparison checks an
0007 → 0008 → 0007 roundtrip, retained authority, and subsequent upgrade/readiness. All three
migration tests pass. Only new migration 0008 and its regression test changed; previously applied
0001–0007 remain unchanged, and the forward 0008 release schema fingerprint did not change.
Remediated source digest:
`bafa67d5a9e19e5a9c4e43cc9da1ba37a9e158439c0da8642c24d699bb3eaa16`.
Final repeated evidence uses `.gate-local/slice15-*-remediated.log`,
`slice15-full-remediated.xml` and `slice15-source-remediated-{before,after}.json`.
The remediated full suite passed **905 tests, 32 skipped, one known warning** in 108.79 seconds.
Ruff, formatting (146 files), strict Pyright and Git diff checks passed. The independent
remediation run passed 66 focused tests and compared all 72 downgraded schema objects against
the frozen prior-release manifest. Source hashes matched before/after the full run and were
reverified unchanged when work resumed on 2026-10-05.
The earlier verification below remains historical evidence for the pre-remediation candidate.

The user authorized the next slice after local Slice 1.4 PASS and a live 10-coin development
grant. Read-only reconciliation confirmed that grant; all 39 grant regressions passed again.
The `/give` simplification is explicitly deferred. No Slice 1.6 work was started.

## Behavior and scope

`/history` pages only the caller's wallet, five records at a time, in deterministic descending
time/UUID order. Reads use a single snapshot and do not create or repair players or wallets.
Fixed labels, signed amount, recorded after-balance and transaction reference are public to the
caller; administrative free-text reasons, operators and system accounts remain hidden.

`/admin_correct_grant` performs a bounded debit against one executed grant target, once per
original transaction/wallet. A partial correction consumes that identity. Its amount cannot exceed
the original grant or current single-operator threshold/per-operation ceiling. Current local
policy thus permits at most 100 coins per correction. Larger, bulk, policy-changing and additional
corrections of the same target grant are unsupported. Separate actual-correction rolling usage
uses the existing configured 24-hour ceiling; retiring money never restores grant quota.

Explicit durable `corrections.execute` authority is required. Frozen targets additionally require
an explicit bypass flag and `corrections.bypass_freeze`, with a dedicated audit and alert. Runtime
disable and unsafe storage cannot be bypassed. New capabilities are neither migrated onto existing
operators nor included in the old bootstrap. No live delegation was performed.

Wallet debit, retirement.correction credit, balanced postings, immutable before/after receipt,
audit and transport outcome commit together. A distinct transport request cannot consume the
same business identity again. The original grant and issuance history are preserved. Migration
0008 adds the receipt/guards and capability names without changing previous migrations.

## Candidate and verification

Base HEAD: `9dd825d957385a49eab43ed4f0dadb3af1f3267b`; working tree is intentionally dirty.
Final candidate source digest before verification:
`069259d16fedc323271984317deb89406200e45d160bc56d29e1240e8116ca33`.
Per-file identity is retained in `slice-1-5-candidate.json` and the ignored before/after
snapshots. The source digest matched before and after the final full run.

Final mandatory pytest: **904 passed, 32 skipped, one known discord.py deprecation warning**,
108.10 seconds. Ruff check, formatting (144 files), strict Pyright (zero errors/warnings),
and Git diff check passed. The skips are native/platform cases and provide no Linux proof.
Independent final acceptance is pending at this point; focused reviewer evidence follows.

Focused new-feature verification passed 55 tests before the final response-loss test and nine
reviewer probes were included. Independent focused verification then passed 183 tests, including
the new features and grant/safety/development regressions. Fresh reviewer probes cover incoming
posting UPSERT, ledger ID and correlation replacement, receipt replacement under recursive
triggers on/off, and competing corrections at the rolling cutoff; these nine probes are now
tracked in `tests/test_correction_adversarial.py`.

Data-bearing 0007 upgrade preserves grants, ledger, projections, authority and audit; Alembic
check reports no new operations. Downgrade refuses committed corrections. Other tests cover
private bounded responses, cursor ties/self-only access, read-only unavailable/frozen states,
insufficient funds, revoked authority, freeze audit, replay after retention, concurrent duplicates,
overflow, rollback/cancellation after partial writes, and real commit followed by lost response.
Reconciliation checks account postings/projections, balanced transactions and minted minus retired
equals wallets. This is local test evidence, not production reconciliation.

Static final checks passed: Ruff; formatting (144 files); strict Pyright (zero errors/warnings).
Evidence: `.gate-local/slice15-{ruff,format,pyright}-final.log`. Full-run logs and JUnit use
`.gate-local/slice15-full-final.{log,xml}`. Independent logs/JUnit use
`.gate-local/slice15-independent-final.{log,xml}`.

## Retained failures and limitations

During construction, a missing deferred type annotation import, initial format/type diagnostics
and a reflected capability-table constraint-order mismatch were corrected. Migration now uses
explicit stable DDL instead of reflection. Early overlapping regression runs saw setup errors
while schema fingerprint work was underway and are not acceptance evidence.
The first stable full run was 900 passed, 32 skipped and four failures from stale 0007 release-head
expectations. Those four expectations were updated to 0008; the original stdout and JUnit remain
in `.gate-local/slice15-full.{log,xml}`. A prior focused run had one stale command-registration
expectation, corrected to include history/correction. No application safety check was relaxed.

Existing legacy unsealed ledger data is not certified or repaired. History does not invent an
after-balance for such rows. The history query has bounded output but may sort growing per-wallet
history; an indexed projection is a future measured scaling improvement. Cursor pages are separate
snapshots. Alert delivery remains the approved development local-log sink, not reliable production
routing. The earlier command-outcome severity limitation remains outside this slice.

The running Discord bot remains on accepted Slice 1.4 and its database was not migrated or
restarted. No Slice 1.5 live interaction is claimed. Native Linux storage/kernel/signal checks and
operational production gates remain deferred; Windows skips cannot satisfy them.
