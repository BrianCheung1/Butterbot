# Phase 0 operations and deployment readiness

Status: accepted Slice 0.4 operating contract, 2026-08-25. This document selects the
initial topology and defines prerequisites for the first production economy database. It does
not provision infrastructure, create a migration, or implement a gameplay command.

## Responsibility model

The deployment record, kept in the operator's private operations system rather than this
repository, must name a primary and an alternate for each role before production economic data
exists:

| Role | Accountable for |
| --- | --- |
| Deployment operator | Host and service access, releases, runtime configuration, secrets, the global mutation switch, incident command, and rollback decisions |
| Backup owner | Backup automation, off-host retention, daily success review, restore drills, and recovery evidence |
| Application owner | Schema/release compatibility, invariant and reconciliation definitions, migration remediation, and application defects |

One person may initially hold more than one role, but every responsibility must have a named
primary and alternate. Host/cloud access, the private deployment record, secret-store audit,
backup-bucket audit, and release records establish deployment authority. Discord guild roles do
not grant any of it.

## Initial deployment topology

The initial production topology is one long-lived Linux virtual machine with:

- exactly one `butterbot` service process, managed by `systemd`, and no separate economic
  worker or second bot replica;
- a non-login `butterbot` operating-system account with no shared human credentials;
- the application installed as an immutable, identifiable release under `/opt/butterbot`;
- the SQLite database at `/var/lib/butterbot/butterbot.sqlite3` on persistent local SSD-backed
  ext4 or XFS storage; and
- logs written to standard output/error for `journald`, with a small off-host log/alert sink,
  while encrypted backups go to off-host object storage in a separate failure domain.

The host initiates its Discord connection; no inbound public web service, container
orchestrator, shared database volume, or in-process scheduler is required initially. A backup
utility invoked by a host timer may open a read/backup connection, but it is not an economic
writer and must not run migrations or mutations.

The database, `-wal`, and `-shm` files remain on the same persistent local filesystem. That
filesystem must provide correct local file locks, atomic rename, and durable `fsync`; it must
survive process and host restarts. The database must not live in an image layer, temporary
directory, network filesystem, synchronized folder, or ephemeral container volume. At startup
and during periodic storage checks, the data volume must have at least both 5 GiB and 20% free.

### Assumptions that invalidate the SQLite decision

SQLite must be re-evaluated, and public mutations remain disabled, if any of these becomes true:

- a second bot or economic worker process is required;
- the database moves to NFS, SMB, a shared/synchronized volume, ephemeral storage, or storage
  without demonstrated locking and durability semantics;
- the selected host or its database volume fails the accepted deployment-host benchmark;
- WAL, `synchronous=FULL`, foreign keys, the busy timeout, bounded retries, or the single-writer
  limit cannot be retained;
- backup, restore, RPO, or RTO requirements cannot be met with SQLite;
- reporting, antivirus, snapshotting, or backup work causes gameplay latency or write
  contention outside the accepted envelope;
- the projected launch peak changes without replacement evidence, or an existing PostgreSQL
  trigger in `database.md` fires; or
- operators cannot preserve the database and its sidecar files across restart and incident
  collection.

Changing providers or replacing a host does not automatically reject SQLite, but it does require
the host-validation procedure below before mutations are enabled on the replacement.

## Runtime and database safety contract

Production configuration uses these environment names when their runtime support is introduced:

- `DISCORD_TOKEN`, supplied by the deployment secret store;
- `BUTTERBOT_DATABASE_PATH`, an absolute path whose production value is the path above; and
- `BUTTERBOT_ECONOMY_MUTATIONS_ENABLED`, parsed strictly as `true` or `false` and treated as
  `false` when absent.

`.env` remains a local-development convenience only. Production secrets and configuration are
set in a root-readable service environment/credential file or provider secret store, never in a
release, repository, database, backup manifest, command line, or log. The bot service account
may read the Discord token and database but not delete retained off-host backups. Credentials
are rotated after suspected exposure and at operator handoff; the deployment record identifies
the current secret owners without storing secret values.

### Startup checks

Normal application startup never creates or migrates a database. Production opens the configured
file in an existing-file/read-write mode equivalent to SQLite URI `mode=rw`, so a misspelled or
missing path cannot silently create an empty economy. Before connecting to Discord or composing
any mutating service, startup must verify all of the following:

1. the database is a regular file on the approved local persistent data volume and the process
   holds the deployment's exclusive bot-process lock;
2. it can connect and `PRAGMA quick_check` returns `ok`;
3. `PRAGMA foreign_keys` is `1`, `journal_mode` is `wal`, `synchronous` is `2` (`FULL`), and
   `busy_timeout` is `1000` on each connection where applicable;
4. `PRAGMA foreign_key_check` returns no rows;
5. the database contains exactly the Alembic revision expected by the release, with one known
   head and no unknown or multiple heads; and
6. the mutation switch is enabled only when every production-enable prerequisite in this
   document is recorded as satisfied.

The connection setup issues `foreign_keys=ON`, `synchronous=FULL`, and `busy_timeout=1000` for
every new connection and verifies their effective values. WAL is established deliberately by
the database initialization/migration procedure and verified at every startup; the application
does not silently continue in another journal mode. SQLite's default automatic checkpoint
cadence is retained initially, WAL/checkpoint health is observed, and tuning it requires new
evidence.

The accepted application retry contract remains at most two retries after the initial attempt,
25/75 ms backoff, a three-second total database budget with 200 ms reserved for scheduling, and
the original transport fingerprint and business key on every attempt. Only busy/locked errors
are retryable. No Discord or network wait occurs inside a transaction, and at most four writer
transactions may be in flight in the single process.

### Schema readiness outcomes

| Condition | Required outcome |
| --- | --- |
| Database file or Alembic table missing | Log `database.schema_readiness` as failed and exit non-zero; do not auto-create |
| Known revision behind the release | Exit non-zero; the deployment operator runs the reviewed migration explicitly while mutations are disabled |
| Revision ahead, unknown, incompatible, or multiple heads | Exit non-zero and escalate to the application owner; never downgrade or guess |
| Integrity, foreign-key, filesystem, lock, or required-PRAGMA check fails | Exit non-zero, record a critical readiness failure, and enter the corruption/incident procedure |
| Exact compatible revision and all safety checks pass | The service may start; mutation composition still depends on the global switch and enable prerequisites |

Schema migration is a separate deployment action, never an application-startup side effect.
Failing readiness prevents the Discord bot from entering normal service; a supervisor process
state and startup logs provide health evidence without exposing an unsafe command surface.

### Global mutation disable before Slice 1.3

Until Slice 1.3 supplies durable safety/access state, the deployment-owned global switch is the
only production mutation authority. Missing or `false` blocks every durable gameplay/economy
mutation, including `/join`, inside the application transaction boundary; `/ping` and
schema-compatible safe reads may remain available. The switch is not a Discord permission and
creates no player restriction rows.

The composition/runtime work that first introduces mutations must implement this fail-closed
policy and log its state at startup. To freeze during an incident, the deployment operator sets
the service environment value to `false` and performs a controlled restart. If the value or
restart cannot be confirmed, the operator stops the process. The target from incident decision
to confirmed freeze is five minutes.

Slice 1.3 will introduce durable administrator capabilities. Its bootstrap input will be an
explicit reviewed list of Discord snowflake identities consumed by a one-time operator command
that creates audited durable capabilities; it will not inspect Discord roles. After bootstrap,
the durable records are authoritative and the one-time input is removed. No in-bot economic
operator exists before that slice, and Slice 0.4 creates no placeholder player or restriction
rows.

## Deployment, shutdown, and restart procedure

Every production update has an identified release and operator record:

1. Confirm the release checks passed, the proposed release supports the current schema, the
   latest backup is verified, storage is healthy, and an app rollback/remediation route exists.
2. Set the global mutation switch to `false`, restart or stop the service, and confirm the
   disabled state. Stop accepting new mutations, allow up to ten seconds for in-flight use cases
   to commit or roll back, cancel remaining tasks so sessions roll back, close Discord, and
   dispose database connections.
3. Produce and verify a pre-deployment backup. Preserve the previous immutable application
   release and record the current database revision.
4. Install the new release and dependencies. If a future release includes a reviewed migration,
   run `alembic upgrade` as an explicit one-shot step; normal bot startup never runs it.
5. Start with mutations disabled. Require all startup checks, `/ping`, and applicable safe-read
   smoke tests to pass. Confirm backup and alert paths still work.
6. Enable mutations only if the production-enable checklist is complete, restart, verify the
   logged enabled state, and watch readiness/error/latency summaries through the first peak
   window.

Graceful shutdown is also required for routine service stops and host reboots. A crash may leave
WAL sidecars, which are normal database state and must not be deleted. On every restart SQLite
rolls back incomplete transactions, application idempotency returns committed outcomes, and the
same readiness checks run before work resumes. `systemd` uses `Restart=on-failure` with at least
a five-second delay and a limit of five starts in five minutes; exhausting the limit alerts the
deployment operator instead of looping indefinitely.

Application rollback means selecting the prior immutable release only when it explicitly
supports the current database revision. Alembic downgrade is not the default rollback. After a
schema change, prefer a reviewed forward fix; otherwise restore the matching pre-deployment
backup to a new database path under the recovery procedure. Never start old code against an
unknown newer schema.

## Backup policy

The backup owner is accountable; a `systemd` timer performs the routine work under a dedicated
least-privilege account. The initial policy is:

- create a consistent backup every 15 minutes and immediately before every application or
  schema deployment;
- retain 15-minute recovery points for 48 hours, one daily backup for 35 days, and one monthly
  backup for 12 months;
- encrypt in transit and at rest, then store in versioned/retention-protected off-host object
  storage in a separate failure domain; and
- keep a manifest containing backup ID, UTC start/end, source schema revision, application
  release, byte size, SHA-256 checksum, verification results, and uploaded object version, but
  no credentials or Discord token.

For a running database, the backup utility must use SQLite's online backup API to create a
consistent destination database in a restricted temporary directory. It must not copy only the
main database file while WAL is active. A fully offline copy is acceptable only after a clean
shutdown and when the main database and any required sidecars are handled as one database state.

Every backup succeeds only when the backup API completes, the destination opens independently,
`quick_check` returns `ok`, `foreign_key_check` returns no rows, the expected schema revision is
present, the file checksum matches after upload, and the manifest is durably stored. Once the
ledger exists, the backup verifier also runs the release's read-only reconciliation checks.
Failure leaves the previous backups intact, emits `backup.completed` with `outcome=failed`, and
alerts; more than 30 minutes without a verified recovery point is a production incident and
keeps or puts mutations in the disabled state.

At least weekly, automation restores the newest backup into a disposable isolated path and runs
full `integrity_check`, foreign-key, schema, and application reconciliation checks. Before the
first public mutation and every six months thereafter, the backup owner and application owner
perform and record a complete restore drill, including disabled startup and safe-read smoke
tests.

The recoverable source of truth is all committed database state through the last verified
backup: players, idempotency outcomes, ledger/history, projections, and later owned game state.
Repository releases, migrations, and versioned content are recovered from immutable release
artifacts/source control, not from the database backup. Discord responses and operational logs
are evidence, not authoritative state, and requests committed after the recovery point are not
automatically replayable. Any resulting player remediation uses reviewed forward or compensating
operations after the relevant capability workflow exists.

## Recovery objectives and procedure

The initial targets are a **15-minute RPO** and a **two-hour RTO**, measured from incident
declaration to a verified service running with mutations disabled. Restoring public mutation
service may take longer if reconciliation or cause analysis is incomplete. This single-host
topology does not promise high availability; the targets assume the off-host backup store and a
replacement Linux host/runtime are reachable.

For loss, corruption, or an unsafe deployment:

1. Declare the incident, set the global switch to `false`, and confirm the freeze within five
   minutes; stop the process if confirmation is unavailable.
2. Preserve the original database, `-wal`/`-shm` files, release ID, service logs, backup
   manifests, and storage/host evidence read-only. Do not checkpoint, vacuum, downgrade, edit,
   or run repair SQL against the original.
3. Work only on copies. Run SQLite integrity/foreign-key checks and application reconciliation
   to determine the last known-good state and select the newest verified backup preceding the
   fault.
4. Restore that object to a new restricted local path, verify its checksum, run full
   `integrity_check`, `foreign_key_check`, exact schema readiness, and all available read-only
   reconciliation/invariant checks.
5. Point the disabled service at the restored path, start it, confirm startup readiness and
   safe-read smoke tests, and record the achieved recovery point and elapsed time. Preserve the
   damaged state and restored backup IDs for review.
6. Re-enable mutations only after the application owner explains the discrepancy, the
   deployment operator approves, backup automation has produced a new verified recovery point,
   and required remediation is reviewed. Apply corrections through forward migrations or
   compensating economic transactions, never untracked manual ledger edits.

Suspected corruption includes any SQLite integrity/foreign-key error, ledger/projection or
supply invariant failure, unexplained missing/duplicate committed state, I/O error, filesystem
durability concern, or mismatch between the expected and observed schema. When in doubt, freeze
first and preserve evidence.

## Minimum observability contract

The initial implementation uses structured JSON logs to standard output plus periodic summary
events; it does not require Prometheus, a data warehouse, or a separate monitoring service.
`journald` retains local logs through host restart, forwards them to one off-host searchable
sink for 30 days, and routes critical events to a tested operator alert destination.

Every event includes UTC timestamp, event name, severity, release, expected/observed schema
revision where relevant, correlation ID, use-case/operation, outcome/error category, duration
where relevant, and current mutation-enabled state. Mutation events also include retry/lock
counts and an internal pseudonymous actor/player reference when needed. Tokens, credentials,
raw Discord payloads, usernames, raw request fingerprints, and database URLs are forbidden.

| Event/metric contract | Minimum fields or measurement |
| --- | --- |
| `discord.command.completed` | command, outcome, duration; count by command/outcome |
| `economy.mutation.completed` | use case, `applied`/`replay`/`domain_rejected`/`failed`, transaction and end-to-end duration, attempts; count and p50/p95/p99 per 60-second summary |
| `database.busy_retry` | use case, attempt, wait and elapsed budget; lock events, retry rate, final lock failures |
| `economy.mutation.failed` | stable error category and rollback outcome; internal failures separate from expected domain rejection |
| `operations.transport_idempotency` | namespace plus replay or fingerprint-conflict outcome; never log the raw key/fingerprint |
| `operations.transport_idempotency_storage` | live/expired row counts, oldest expiry, cleanup deletions/failures, and cleanup duration |
| `application.business_uniqueness` | owning domain/use case plus accepted or already-consumed/stale-revision outcome; never log a raw entitlement key |
| `economy.invariant_failure` | invariant name, affected internal references, detection source; count is expected to remain zero |
| `database.schema_readiness` | database-path alias, expected/observed revision, each PRAGMA/check result, startup outcome |
| `database.storage` | main/WAL/SHM bytes, data-volume free bytes/percent, WAL checkpoint busy/result, daily growth |
| `backup.completed` | backup ID, schema/release, duration, bytes, verification stages, upload/checksum result, age of last verified backup |
| `economy.mutations_state` | enabled/disabled, reason category, release, readiness result; emitted on every startup and state change |

The first alert contract is also small and measurable:

- alert immediately on any invariant/corruption finding, schema-readiness failure, final lock
  failure, backup verification failure, or process start-limit exhaustion;
- alert and disable/keep disabled mutations when the newest verified backup is older than 30
  minutes or free storage violates the minimum;
- warn on one idempotency fingerprint conflict and alert on more than five in five minutes;
- warn when expired transport-idempotency rows remain after the scheduled incremental cleanup
  window and alert on repeated cleanup failure;
- warn on one 15-minute window with p95 over 100 ms, p99 over 250 ms, or retry rate at least 1%;
  three peak windows over the accepted p95/retry limits invoke the PostgreSQL trigger; and
- alert when internal mutation failures exceed 1% in five minutes or five consecutive attempts,
  excluding typed domain rejections, and notify on every global mutation-state change.

Command/mutation counts, business-uniqueness outcomes, failed mutations, and latency are emitted
from the owning application boundary; the shared Operations idempotency coordinator emits
transport replay/conflict outcomes; database retry events come from the database adapter;
invariant checks own their critical event; startup owns readiness and state; and the backup
utility owns backup events. This ownership keeps metrics from being guessed in Discord cogs.

## Deployment-host SQLite validation

The accepted Slice 0.3 evidence was produced on the development machine. Before the first public
durable mutation, run the unchanged accepted benchmark on the exact selected production VM and
the same local filesystem/mount intended for `/var/lib/butterbot`. Run as the service account
with the production Python, SQLite, and aiosqlite versions, while normal host encryption,
logging, backup, monitoring, and security agents are active. Use fresh disposable files on that
volume; never point the benchmark at the production database.

Use the reproduction command in `sqlite-capacity.md` without changing the accepted 17 TPS peak,
34 TPS offered rate, 10-second warm-up, 30-second measurement, three repeats, four workers,
retry policy, pragmas, workload, or correctness diagnostics. Record the host class, storage
type/mount, runtime versions, benchmark implementation fingerprint, configuration, and raw JSON
in a reviewed deployment-host evidence file.

Public mutations remain disabled unless every open-loop repeat completes at least 99% within
its window with p95 at most 100 ms, p99 at most 250 ms, retry rate below 1%, no final lock,
backlog, invariant, or idempotency failure, all correctness diagnostics pass, and no independent
PostgreSQL trigger fires. Saturation remains diagnostic and cannot replace or weaken the
open-loop gate. A failure requires host/storage remediation, a reviewed replacement run, or
PostgreSQL work—not a lower offered rate or weaker durability.

Repeat host validation after moving/replacing the VM or database volume; materially changing
CPU/storage class, filesystem, virtualization, encryption, security/backup agents, Python/
SQLite/aiosqlite, benchmark implementation, or SQLite settings; or replacing the projected
peak. A pure application release that leaves those inputs unchanged does not require a rerun.

## Acceptance and deferred implementation

Slice 0.4 is accepted when this topology, responsibility split, startup contract, backup policy,
recovery objectives/procedure, observability contract, operator bootstrap boundary, and unchanged
deployment-host benchmark gate are reviewed together. These are the operational inputs required
before authorizing the first production economy migration.

The following are deliberately deferred because no production database or economic mutation
exists yet; each becomes a blocker at the named enable/deployment gate, not a reason to build
speculative infrastructure in Slice 0.4:

- selecting/provisioning the actual VM, object store, secret store, log sink, alert endpoint, and
  naming the role holders: before the first production deployment;
- implementing the database lifecycle, process lock, schema/PRAGMA readiness checks, global
  switch, transaction telemetry, and graceful drain: with the first persistence/mutation slices
  and before any such mutation is enabled;
- implementing backup automation and the application reconciliation verifier, then recording a
  successful full restore drill: before real economic data/public mutation;
- producing accepted evidence from the selected deployment host: before its first public
  durable mutation; and
- durable capabilities and one-time bootstrap tooling: Slice 1.3, before any in-bot economic
  administration.

The first production-enable checklist is therefore measurable: named owners and alternate;
one approved host/process; persistent local storage checks; exact schema/runtime readiness;
mutation switch proven fail-closed; a verified backup newer than 30 minutes; a successful restore
drill meeting the 15-minute RPO/two-hour RTO; alert delivery test; and accepted deployment-host
benchmark evidence. Any unchecked item keeps mutations disabled.
