# Slice 1.4 disposable development activation — 2026-09-27

Independent provisional local acceptance passed before activation; see
`slice-1-4-independent-acceptance.md`. Application/migration/test source remains commit
`9dd825d957385a49eab43ed4f0dadb3af1f3267b`.

## Disposable smoke evidence

The real development launcher composition allocated and migrated a new disposable database,
loaded the existing approved configuration, bootstrapped its single approved operator and ran
the application services. Only Discord serving was replaced with an offline smoke callback.
This is not a live Discord interaction test.

The smoke passed: unjoined read, explicit join, zero balance, approved 10-coin proposal,
unexecuted preview, execution, distinct-interaction duplicate rejection, executed preview and
10-coin balance. A 101-coin proposal remained pending and execution required approval. A target
freeze blocked a new grant proposal while balance remained readable; release succeeded.
SQLite integrity and foreign-key checks passed. Exactly one execution remained, wallet +10 and
issuance.admin -10; every projection matched its postings and total postings balanced to zero.

Retained ignored evidence: `.gate-local/slice14-development-smoke.py` and `.log`.
Smoke database: `data/discord-development/join-4xsu61be/butterbot.sqlite3`.

## Live activation

No prior development bot was running. The first sandboxed launch could not connect to Discord
and shut down; its failure log is retained as `slice14-live-development.stderr.log`.
The network-enabled retry successfully synchronized commands only to the configured test server
and connected to the Discord gateway at 23:49:56 UTC. Launcher PID: 10132.
Fresh live database: `data/discord-development/join-ss_0ocae/butterbot.sqlite3`.
Logs: `.gate-local/slice14-live-activated.stdout.log` and `.stderr.log`.

Configuration was verified without displaying the token: guild `152954629993398272`, tester
and operator `1047615361886982235`, channel `455431053528793098`; approval above 100 coins,
1,000 per proposal, 10,000 per proposer/24 hours, local structured alerts. No settings, scope,
operator identities or production configuration were changed. No prior database was migrated.

Live command smoke remains pending: the available browser reached Discord sign-in, not an
authenticated tester session. The bot is left running for the approved tester. Run `/join`,
then `/admin_propose operation:grant targets:1047615361886982235 amount:10` with a test reason;
inspect the returned proposal, execute it, check `/balance`, and execute the same proposal again.
Expected results are executed, 10 coins, then already_executed with balance still 10.
No live grant or user-visible response verification is claimed by this report.

No next feature was started. Native Linux and production release acceptance remain deferred.

## 2026-09-30 live smoke addendum

The user requested a new start. Fresh session `join-3d60xh0l` connected and synchronized the
restricted guild commands at 20:45 UTC. The user reported executing proposal
`d18d3fd2-9ec5-599a-9b6c-3c149aac5a4e` and seeing 10 coins. Logs show execution success followed
by a balance read. A read-only database check independently confirmed exactly one execution,
wallet +10, issuance -10, balanced postings and projections matching their account posting sums.
All 39 automated grant regressions passed again, including duplicate and retention tests;
the user has not reported a live duplicate-execution attempt. Evidence is
`.gate-local/development-20260930.stderr.log` and `.gate-local/slice14-before-slice15.log`.
The user then authorized local Slice 1.5 and deferred the `/give` usability follow-up.
