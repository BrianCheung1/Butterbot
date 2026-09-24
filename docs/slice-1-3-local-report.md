# Provisional Slice 1.3 local verification

Observed 2026-09-23 on Windows, Python 3.13.15. **SLICE 1.3: FAIL.** The code is
ready for continued local testing. The user subsequently approved the local operator/policy/alert
settings; native Linux acceptance remains outstanding. Activation evidence is recorded in the
addendum below. No production migration or Slice 1.4 work was performed.

## Candidate binding

Base commit: `fe8c99db95878d38abf00455ed5cb7f3ed632075`, plus the uncommitted Slice 1.3
implementation, tests, new migration and documentation. HEAD alone does not identify
this candidate. Deterministic source-map SHA-256:
`1742eb9f5bc54db85e1001e4f399c0c6b7c7ed1c8e2dae93bd4729305a363b8f`.
Before/after maps are `.gate-local/slice13-final-source-before.json` and
`.gate-local/slice13-final-source-after.json`; their source hashes match. The map
covers runtime/test/configuration source, not all documentation. Changes remain
uncommitted and have not been pushed.

Migration `20260922_0004` has SHA-256
`e132541173cfad77ff1021da3afdaa5589b4081de11cf25d24164cd39acc1d64` and remained unchanged
after application to disposable storage. Revisions 0001, 0002 and 0003 are unchanged.
The release schema manifest now includes the safety tables, indexes and triggers.

## Implemented behavior

- Durable capabilities, one-time local bootstrap and audited capability changes.
- Private authorized player inspection and stored-proposal preview.
- Freeze/release/grant proposals, total and rolling monetary ceilings, expiry,
  distinct-person approval for bulk/global/above-threshold proposals, and concurrent
  approval protection. Grant proposals never issue coins.
- Central global/player freezes enforced by join while balance reads and authorized
  release remain available. Existing replayed join results do not create state.
- Immutable access audit and permanent administrative receipts preventing stale
  replays after transport retention cleanup from restoring revoked authority.
- Private Discord adapters with existing development guild/user/channel scope;
  no Discord role is accepted as administrator authority.

## Verification and retained failures

Final mandatory commands all exited 0:

- Ruff check and formatting check passed.
- Pyright: zero errors, warnings or information diagnostics.
- Full pytest: **729 passed, 32 skipped, one warning in 69.67 seconds**.
- git diff --check passed.

The warning is the installed discord.py Markdown escaping implementation's deprecated
positional `re.sub` count argument. Native/platform cases remain skipped on Windows.
Command results: `.gate-local/slice13-final-results.json`; logs:
`.gate-local/slice13-final-{0..4}.log`; raw JUnit: `.gate-local/slice13-final.xml`.

The initial full run failed two counterfeit-head fixtures that still stamped schemas
with revision 0003; they reached version rejection rather than the intended schema
contract rejection. The fixtures now stamp the current head without weakening their
assertions. Full failed nodes/tracebacks remain in
`.gate-local/slice13-full-initial.log` and `.gate-local/slice13-full-initial.xml`.
Initial lint/type diagnostics and corrected results are also retained under
`.gate-local/slice13-*`. No product test stall occurred in these runs.

Data-bearing upgrades from each prior revision preserve the existing aggregate, pass
Alembic check, and start under the new readiness contract. All three migration cases
passed. Independent review recorded 141 focused passes, separate adversarial replay,
limit-race and rollback probes, then three passes for the additional migration tests.
See [the independent report](reviews/slice-1-3-independent.md) for precise ownership,
source binding, raw evidence and its final handoff limitation.

## Approved local policy

The user explicitly approved these settings for disposable local testing:

| Setting | Proposed value |
| --- | --- |
| Initial operator | Existing tester `1047615361886982235` |
| Second approval threshold | Total greater than 100 coins |
| Per-proposal total ceiling | 1,000 coins across all targets |
| Per-proposer rolling 24-hour ceiling | 10,000 proposed coins |
| Alert destination | Local structured logs only |
| Bulk/global proposals | Always require another distinct authorized operator |

No second operator is configured or allowed through the single-user development scope;
those approvals remain blocked in live testing. Synthetic fixtures use other identities
only in temporary databases. The ignored local `.env` now contains the approved policy.
No prior database is upgraded or reused; activation allocates a fresh disposable session.
This approval enables local testing only, not production acceptance.

## Remaining blockers and risks

The explicit local policy approval required by ROADMAP.md Slice 1.3 has been received.
Complete native evidence for the final dependent candidate and independent evidence
acceptance remain required before release. Neither local test results nor user approval
of a disposable policy substitute for Linux evidence.

The reviewer demonstrated that privileged raw SQL can append proposal targets after
approval. No current service exposes that operation and no grant execution exists;
seal/verify approved membership with a new migration before Slice 1.4 consumes these
proposals. Existing row immutability is not membership immutability. Local logs also
do not provide reliable remote alert delivery. Capability managers are trusted to
delegate authority, and distinct Discord identities do not prove distinct humans.

No later slice or production release is authorized by this report.

## Approved local activation

After explicit user approval, the dedicated development bot started a fresh session
`data/discord-development/join-3wq33dgs/`, migrated that new disposable database to
0004, synchronized the configured guild commands and connected to Discord at
2026-09-24 02:43:47 UTC (September 23 local time). No prior development process was
found during the process check. The previous database was not reused or upgraded.

Read-only inspection confirmed exactly the approved user as the sole capability
holder, all five expected capabilities, one bootstrap marker and one bootstrap audit.
The bootstrap alert appeared in `.gate-local/development-slice13-live.log`; structured
verification is `.gate-local/slice13-live-bootstrap.json`. Guild/user/channel scope
was validated unchanged. No token was displayed or added to tracked files.

Runtime/test source still matches the reviewed hash above, with no code changes since
the 729-pass verification. This activation proves startup/bootstrap and gateway
connection; actual user-executed admin command smoke testing remains to be confirmed.
Changes remain uncommitted. Native acceptance and the formal FAIL verdict are unchanged.


## Live administrator smoke test confirmed (2026-09-24)

The retained Discord command-completion events from 09:33–09:35 UTC show join creation,
applied freeze, denied new join, available balance, available authorized inspection,
applied release, and successful existing-player join afterward. Read-only inspection of
`join-3wq33dgs` independently confirmed applied single-target freeze/release proposals
for the approved tester, immutable audit entries, and no remaining restrictions.
Evidence: `.gate-local/slice13-live-smoke-observations.json` and
`.gate-local/development-slice13-live.log`. These are observed handler completion and
persistence results, not screenshots of the user's private response.

An earlier `/admin_proposal` invocation returned invalid input; it did not create a
proposal. The subsequent valid `/admin_propose` workflow completed as above. The existing
command telemetry labels outcomes other than literal completed at error severity, including
successful available/applied results. Outcome fields and durable records establish success;
this noisy severity mapping is a non-blocking observability issue to correct before routing
production alerts. No new runtime/test changes were made for this checkpoint.

The local policy and single-operator interactive checks are complete. Native acceptance still
blocks formal PASS. The target-membership limitation remains a prerequisite before Slice 1.4.
This report is committed with the implementation; its earlier uncommitted-state statements
record the state during verification. The tested source digest remains unchanged.
