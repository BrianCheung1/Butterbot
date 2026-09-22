# Provisional Slice 1.2 local verification

Observed 2026-09-22 on Windows/Python 3.13. **Release verdict: FAIL.** Native Linux
acceptance remains deferred. The independent local review found no demonstrated
blocker within the authorized provisional scope. Slice 1.3 and production use remain
unauthorized. See [the independent review](reviews/slice-1-2-independent.md).

## Candidate and change

The prior join isolation fix/report was committed and pushed to origin/main as
`e53641d7413fa82236481f5e0952b5a438e18ed3`. Verification was performed on the uncommitted
balance changes on that base; the base commit alone does not identify them. Source SHA-256:
`522258f6e7b00610fe7466aad9257d8b945d00a05b492869d7ee20adeae31fd8`.
Before/after deterministic source manifests are retained in
`.gate-local/slice12-final-source-before.json` and
`.gate-local/slice12-final-source-after.json`; their source hashes match.
The independent reviewer confirmed the same source hash. Documentation is outside
that runtime/test/configuration manifest scope.

The command reads only the caller's wallet, privately acknowledges/responds, invites
unjoined users to join, and does not create or repair state. Active players can read
while global mutations are disabled. Deferred transactions provide a consistent
snapshot without acquiring the SQLite writer lock. Existing lifecycle, identity,
admission and shutdown protections are reused. No schema change or migration.

## Observed checks and evidence

- Ruff check and format check: passed.
- Pyright: zero errors/warnings.
- Full pytest: **647 passed, 32 skipped in 50.09 seconds**, exit 0.
- git diff --check: passed.
- Independent final focused suite: **86 passed**, with one cache permission warning;
  separate SQL trace, concurrent snapshot, and shutdown probes passed.

Final command results: `.gate-local/slice12-final-results.json`; stdout/stderr:
`.gate-local/slice12-final-{0..4}.log`; raw JUnit: `.gate-local/slice12-final.xml`.
These are local ignored artifacts, not native acceptance evidence. The earlier full
run passed 647/32 in 52.48 seconds; the final run includes additional development
composition assertions. No product failure or stall occurred. The independent
probe's initial fixture-cleanup failure, traceback, diagnosis and successful rerun
are documented in its report.

## Interactive development

No previous development process was found. The updated launcher was started and
observed synchronizing guild commands and connecting to Discord's gateway at
20:52:47 UTC. Log: `.gate-local/development-slice12-live.log`; disposable storage:
`data/discord-development/join-cpjzne6k/`. The configured server remains
`152954629993398272`, tester `1047615361886982235`, channel `455431053528793098`.
Secrets were not included in changes or reports. The user subsequently reported that
the live response showed 0 coins. This establishes user-reported success for the
joined-wallet smoke test; it does not claim live coverage of every denial/error path
or native acceptance. Source identity was rechecked before committing and still
matched the reviewed manifest above.

## Remaining gate and non-blocking risks

Native evidence for the final candidate, all required cases, and independent evidence
acceptance remain necessary. Local success does not establish Linux permissions,
capabilities, mounts, or SIGTERM behavior. The read factory trusts application code
to use reads and shares bounded admission with writers; it is not a database write
sandbox. A displayed balance is a point-in-time snapshot. These documented local
limitations did not produce a demonstrated blocker in this review.
