# Slice 1.6 local report

Date: 2026-10-06. Base commit: `368c33ac02fbfedc6d1402cbb3f17538e67f974e`.
Candidate: `slice-1-6-candidate.json`; source SHA-256
`3512e2c639f4056f9150b131373f1d45852395220e92fc22b3ea29cd6cc10031`.

Verdict: `SLICE 1.6: PASS` for provisional local use, independently accepted.
See `slice-1-6-independent-acceptance.md`. Native production remains deferred and FAIL.

Current live status: activated 2026-10-06; tester reported daily rewards working. Legacy global
commands were removed and the 12 current test-guild registrations verified unchanged. The
implementation-time and activation-time statements below are historical snapshots.

## Scope and policy

The user delegated reward selection from the plans. Selected 15 coins per UTC calendar day,
reset at midnight UTC, no streak multiplier, grace window or catch-up. The choice follows the
Phase 0 modest reward baseline and still requires Phase 2 integrated balance validation before
public gameplay. Added private `/daily status` and `/daily claim`, self-only history entries,
atomic balanced issuance.daily postings, permanent business uniqueness and success replay.
The request's immutable Discord creation day is checked against injected time after writer
admission; an uncommitted request crossing midnight expires and requires a new interaction.

Revision 0009 is additive. Prior migrations and schema object fingerprints are unchanged.
Empty downgrade restores the exact prior schema; populated daily history blocks downgrade.
Neither migration nor composition grants operator permissions or changes existing development
server/user/channel restrictions. The running Slice 1.5 disposable session was not migrated,
restarted or modified. No live Slice 1.6 Discord interaction is claimed.

## Verification

- Ruff check: PASS (`.gate-local/slice16-ruff.log`).
- Ruff format check: PASS, 155 files (`.gate-local/slice16-format.log`).
- Pyright: PASS, zero errors/warnings (`.gate-local/slice16-pyright.log`).
- Targeted daily/service/adapter/migration tests: 25 passed.
- Full pytest: PASS, 948 passed, 32 skipped, one known discord.py deprecation warning
  in 168.36 seconds (`.gate-local/slice16-full.log`).
- Independent regression: 262 passed with the same known warning
  (`.gate-local/slice16-independent-final.log` and XML); final verdict in the independent report.
- `git diff --check`: PASS.

Coverage includes distinct simultaneous claims, exact midnight and writer admission across it,
missed days, permanent replay after cleanup and conflict rejection, freeze/runtime restrictions,
read-only inspection, partial-write rollback/cancellation, balance/version overflow, private
history, response loss after real commit, populated prior-state migration and downgrade safety.
Independent tests add incoming replacement/UPSERT attacks with foreign keys enabled and recursive
triggers on/off, clock regression and cross-player history isolation.

## Limits

Success replay from the permanent receipt bypasses temporary transport-coordinator replay metrics;
Discord command telemetry still records replay. This is an observability limitation, not additional
issuance. Changes were uncommitted when acceptance evidence was captured. The next slice has not started. Native Linux production
validation remains deferred and FAIL; Windows local checks cannot establish those guarantees.

## Manual development smoke after acceptance and a fresh launch

1. In the existing approved test server/channel, use `/join` as the approved tester.
2. Use `/daily status`; expect 15 coins available and the next midnight UTC reset.
3. Use `/daily claim`; expect +15 and wallet balance 15 for a new wallet.
4. Repeat `/daily claim`; expect already claimed and no balance change.
5. Check `/balance` and `/history`; expect one Daily reward +15 entry and balance 15.
6. A new UTC day permits another 15. Automated clock tests cover this without waiting overnight.

Each development launch intentionally creates a fresh disposable database. Existing nonzero
wallets would gain 15 rather than being set to 15. Scope checks continue to reject other users,
servers, channels and DMs. Live smoke was pending at acceptance; see the later tester confirmation below.


## 2026-10-06 restricted development activation

The user authorized a fresh development run. No previous Butterbot Python process was found.
Accepted candidate hashes, guild/user/channel restrictions, sole operator and policy limits
100/1000/10000 were verified unchanged. Hidden development process 7856 launched fresh session
`join-wb2fgkrf`. Commands synchronized to the configured test guild and the Discord gateway
connected at 20:51:13 UTC. Logs: `.gate-local/development-20261006-165110.{stdout,stderr}.log`.
Previous disposable databases were preserved. Live daily command smoke awaits the tester;
no live reward was issued by this activation. Production validation remains deferred.


The tester subsequently reported the daily feature working. At the user's explicit request,
removed 15 legacy global Discord command registrations from the reused development application.
A read-back confirmed zero global commands and all 12 current test-guild command registrations
byte-for-byte unchanged. The running bot, wallet data and guild/user/channel restrictions were
preserved; no restart or new database was required.
