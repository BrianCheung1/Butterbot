# Independent local Slice 1.1 review

Reviewed 2026-09-17 on Windows. **Provisional local determination: acceptable after
the development text-help fix below. Release verdict: FAIL**, because required native
Linux acceptance remains deferred. This review does not authorize Slice 1.2, production
use, or public mutations.

## Scope and source binding

The reviewer read AGENTS.md, the roadmap's explicit local-development exception,
Slice 1.1 requirements, relevant decisions/testing contracts, join application and
Discord code, development launcher, composition, transaction/idempotency code, and
associated tests. No live Discord request or production database was used. The
reviewer made no implementation changes; the coordinating agent fixed the finding.

Initial checkout was clean at commit
`7171e0335d20be783c3a9a4a02f719da06baab8e`. Final reviewed source has the same base
commit plus the `help_command=None` change and its regression test. The final source
manifest was independently generated after the fix using the reviewed native runner's
source-map function. Its deterministic SHA-256 is
`48442b4a306dafdb956ec4a1bcdd904b51f954ccb3e04a0d3f689b3a6b684a34`.
The manifest is `.gate-local/slice11-independent-source-final.json`. At capture, git
reported modifications to `docs/decisions.md`,
`src/butterbot/discord_app/development.py`, and `tests/test_development.py`.
HEAD alone therefore does not identify the tested candidate. This review document is
outside the runner's source-map scope. The coordinating release report should preserve
the final commit identifier in addition to this source binding.

## Finding: resolved P2 development-scope bypass through default help

The initial DevelopmentBot inherited discord.py's default prefix `help` command and
`BotBase.on_message`/`process_commands`. Its guild/user/channel restriction lived only
in `DevelopmentCommandTree.interaction_check`, which governs application commands.
Thus the text help surface was outside that restriction and could respond publicly
outside the intended tester/channel. This was an isolation/privacy defect, not a
demonstrated bypass that invokes join or mutates player state.

The coordinating reviewer identified the alternate dispatch path. This reviewer
independently instantiated the actual bot and confirmed `TEXT_COMMANDS ['help']` and
the inherited prefix handlers. The final fix passes `help_command=None`. Independent
reinspection/probing confirmed `TEXT_COMMANDS []` and `HELP None`, and the new regression
passed in the focused suite. Only ping/join slash commands are loaded; no prefix command
remains in this candidate. Future prefix extensions would require their own scope
review. A previously running process needs a deliberate restart to adopt this fix;
changing source does not patch an existing in-memory bot.

## Application, transaction, and privacy observations

No additional demonstrated blocker was found in the reviewed local implementation.

- Join claims transport identity, creates or retrieves the player and zero-balance
  wallet, and persists its fixed outcome within one application-owned transaction.
  The service performs no Discord network calls. The existing writer transaction and
  database uniqueness guards provide convergence across distinct interactions.
- The actor participates in the transport fingerprint. An interaction reused for a
  different actor fails; same-request replay returns the stored result. Eligibility
  is evaluated for new requests inside the transaction. Returning an earlier success
  after eligibility changes is the documented replay policy, not a new mutation.
- Denials retain only typed-rejection transport bookkeeping. Existing balances and
  versions survive retrieval; inactive players are not reactivated and missing
  wallet/projection state is not repaired. There is no issuance or ledger mutation.
- Join outcome payloads are fixed empty objects and decoding rejects incompatible
  kind/code/payload combinations. The current feature does not persist arbitrary
  input-derived outcome collections. General payload-size limits remain a later
  prerequisite before such data is introduced.
- The Discord adapter privately defers before calling the service and privately sends
  its fixed response after commit. Defer failure prevents the application call;
  response failure does not repeat it. Error messages omit raw internal exception
  text, IDs, and balances. Cancellation is propagated.
- Development slash execution checks exact guild, user, and channel IDs, rejecting
  direct messages and other threads/channels. Guild-only synchronization and the
  explicit extension list limit registration. Default privileged intents remain off.
  The launcher allocates fresh disposable storage and ignores the normal configured
  database path; it is a deliberate exception documented by the user's authorization.

## Reviewer-executed checks

All checks below were executed independently on the local Windows Python environment,
without network access to Discord. The coordinating agent's full verification is
separate and is not represented here as reviewer-executed work.

```text
.venv/Scripts/python.exe -m pytest -q -ra -o faulthandler_timeout=60 tests/test_join.py tests/test_join_command.py tests/test_development.py tests/test_composition.py --junitxml=.gate-local/slice11-independent-final-junit.xml
```

Final result: **73 passed, one cache-write permission warning, 3.82 seconds**, exit 0.
The initial pre-fix run passed 72 cases in 4.16 seconds, showing the existing suite did
not cover default prefix help. No failure or stall occurred in these focused runs.

Fresh adversarial probes additionally established:

1. A deterministic generated UUID collision fails and rolls back the new request
   claim and second aggregate, leaving counts unchanged.
2. After a disposable fixture's projection is deleted, replay returns the prior
   success without repairing or changing state. A new interaction fails the
   persistence invariant and leaves no extra transport claim.
3. Calling the installed discord.py `CommandTree._call` entry point with six
   out-of-scope guild/user/channel combinations rejects them before command
   resolution, sends only an ephemeral denial, and never calls the join service.
4. The final bot has no registered text commands and no help command.

These probes passed again after the fix. Their source and output are retained under
`.gate-local/slice11-independent-adversarial.py`,
`.gate-local/slice11-independent-final-adversarial.txt`, and
`.gate-local/slice11-independent-final-prefix-probe.txt`. The original prefix probe
is `.gate-local/slice11-independent-prefix-probe.txt`; focused stdout and raw JUnit
are `.gate-local/slice11-independent-final-tests.txt` and
`.gate-local/slice11-independent-final-junit.xml`.

## Residual risks and gate determination

### Coordinating agent's final verification

After the fix, the coordinating agent separately observed Ruff check, Ruff format
check, Pyright, and git diff --check passing. The full pytest run finished with
**624 passed, 32 skipped in 45.12 seconds**, exit 0. Command results are retained in
`.gate-local/slice11-review-final-results.json`, logs in
`.gate-local/slice11-review-final-{0..4}.log`, and raw JUnit in
`.gate-local/slice11-review-final.xml`. The deliberately failing regression before
the fix and its passing rerun are retained in
`.gate-local/slice11-prefix-regression-before.log` and
`.gate-local/slice11-prefix-regression-after.log`.

The final source manifest was compared again after verification and remained
unchanged; `.gate-local/slice11-review-source-after.json` retains that observation.
These local artifacts are ignored working files, not committed native evidence.
The fix and this report remain uncommitted. No live bot restart was performed.
The independent reviewer wrote the findings and focused results above, but its
agent turn ended with a usage-limit error before a final handoff; the coordinating
agent inspected the completed report and added this verification section.

The isolated local checks do not establish genuine Discord delivery, host permissions,
filesystem behavior, native capabilities, or SIGTERM guarantees. No live interaction
was exercised. The development token comparison prevents reuse of a simultaneously
configured normal token; it cannot prove organizational ownership or that an otherwise
unspecified token is a dedicated application. Dedicated test-bot operation remains an
operator configuration requirement.

The default-help defect is resolved for the final source; an already running prior
process may retain it until restarted. The inherited general prefix dispatcher remains,
with no commands registered; future additions must preserve the no-prefix-command
invariant or enforce equivalent scope/privacy checks. The previously reported
intermittent stall did not recur here and remains unexplained.

The explicit roadmap exception permits this provisional local work. It does not waive
the native gate. Complete native evidence must bind the final foundation-plus-join
candidate, account for every required case, and pass independent evidence review.
**Release FAIL remains in force until those requirements and all required verification
are satisfied.**
