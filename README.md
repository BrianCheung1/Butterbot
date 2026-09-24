# Butterbot

Butterbot is a planned Discord economy game designed for long-lived player progression.
It currently provides a runnable Discord bootstrap, `/ping`, the Slice 1.0 persistence foundation,
and provisional local `/join` and `/balance` commands. Earning, spending, and progression are not implemented.

Native Linux acceptance is deferred under the user-authorized local development exception.
`/join` privately creates or retrieves a player and a zero-balance wallet when eligible. Normal
local bot configuration keeps mutations disabled, so it replies that joining is unavailable.
Successful creation can be exercised in disposable local integration tests or the separate
interactive development launcher below. To run the join checks:

```powershell
.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider tests/test_join.py tests/test_join_command.py
```

Slice 1.0 and Slice 1.1 still require native evidence and independent release acceptance before
production use. See the provisional exception in [ROADMAP.md](ROADMAP.md).

## Development setup

Python 3.13 is required.

```powershell
py -3.13 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

Open `.env` and replace the placeholder with the token from the Discord Developer Portal:

```dotenv
DISCORD_TOKEN=replace-with-your-token
BUTTERBOT_DATABASE_PATH=C:\absolute\path\to\butterbot.sqlite3
BUTTERBOT_RELEASE_ID=development
BUTTERBOT_DATABASE_ROOT=C:\absolute\path\to
BUTTERBOT_DATABASE_VOLUME_ID=
BUTTERBOT_DATABASE_ADMINISTRATOR_UID=
BUTTERBOT_DATABASE_SERVICE_GROUP_GID=
BUTTERBOT_ECONOMY_MUTATIONS_ENABLED=false
```

Normal startup never creates or migrates a database. Initialize or upgrade a local database as
an explicit development/deployment action before starting the bot:

```powershell
$env:BUTTERBOT_DATABASE_PATH = "C:\absolute\path\to\butterbot.sqlite3"
$env:BUTTERBOT_RELEASE_ID = "development"
alembic upgrade head
```

`BUTTERBOT_DATABASE_ROOT` is the canonical approved directory containing the database directly.
Production mutation enablement additionally requires `BUTTERBOT_DATABASE_VOLUME_ID`, set to the
approved Linux mount `major:minor` identity from `/proc/self/mountinfo`, plus the reviewed numeric
administrator UID and Butterbot service-group GID. Startup then requires that exact local ext4/XFS
mount and the owner/group/mode contract in `docs/operations.md`. Development with mutations
disabled may leave all three values empty.

Keep mutations disabled unless every production-enable prerequisite in
[`docs/operations.md`](docs/operations.md) has been satisfied. Slice 1.0 exposes no economic
mutation command regardless of the setting.

Invite the application with the `bot` and `applications.commands` scopes, then launch it
from the repository root:

```powershell
.venv\Scripts\Activate.ps1
python -m butterbot
```

The bot uses Discord's default, non-privileged intents. It synchronizes `/ping`, `/join`, and `/balance` globally at
startup, and Discord may take time to make a newly synchronized global command visible.

## Interactive wallet testing with disposable data

Use a separate Discord development application/bot, invited to a private test server with
the `bot` and `applications.commands` scopes. Put its token and the test IDs in your ignored
local `.env` (never in `.env.example` or chat):

```dotenv
BUTTERBOT_DEV_DISCORD_TOKEN=replace-with-development-bot-token
BUTTERBOT_DEV_GUILD_ID=your-test-server-id
BUTTERBOT_DEV_USER_ID=your-discord-user-id
BUTTERBOT_DEV_CHANNEL_ID=your-test-channel-id
```

Run from this checkout:

```powershell
.venv/Scripts/python.exe -m butterbot.discord_app.development
```

The launcher requires its own token and refuses to reuse the configured `DISCORD_TOKEN`.
It registers `/ping`, `/join`, and `/balance` only in the selected test server, and rejects commands from
other users, servers, channels, or DMs before calling the application. Threads have their own
channel IDs and are also rejected unless explicitly configured. It does not synchronize global
commands. Normal startup and production mutation checks are unchanged.

Each launch allocates and migrates a new database under ignored
`data/discord-development/join-*/`. It never uses `BUTTERBOT_DATABASE_PATH`, never opens an
existing database, and never automatically migrates production storage. Development joins use
the real transaction service and storage monitoring with a zero-balance wallet. No currency
is issued. No database-path override is offered.

In the configured channel, run `/balance` before joining: expect a private invitation to `/join`.
Then run `/join`: expect a private "You joined Butterbot!" response.
Run `/balance`: expect a private zero-coin wallet. Run `/join` again: expect a private "already joined" response. Stop the launcher with Ctrl+C.
Restarting begins a new empty session, so `/join` should create your test player again.
Disposed session files are retained for debugging; old sessions are never reused automatically.
Use a test server where only the intended tester participates. This is local development,
not native Linux or release acceptance evidence.

Quality checks:

```powershell
ruff check .
ruff format --check .
pyright
pytest
```

Regenerate the Phase 0 economic/progression worksheets:

```powershell
python -m butterbot.simulation
```

Start with [the documentation index](docs/README.md) before making design or architecture
decisions. The dependency-ordered implementation plan is in [ROADMAP.md](ROADMAP.md).
The accepted initial production operating contract is in
[docs/operations.md](docs/operations.md). The first production schema and runtime safety checks
are implemented, but backup/restore provisioning, deployment-host evidence, and public mutations
remain gated.


## Provisional local administrator safety

Slice 1.3 adds durable capabilities, audited `/admin_inspect` and `/admin_proposal`, capability
assignment/revocation, and freeze/release/grant proposals. `/admin_approve` applies authorized
restrictions or approves a grant proposal; no coins are issued. All administrative commands are
private and require durable authority, not Discord roles. `/balance` remains readable during a
freeze. See `docs/operations.md` for the explicit one-time local bootstrap and configuration.
The user approved the disposable local operator/limits/logging policy; configuration is kept in
the ignored local environment. Native Linux release acceptance remains deferred.
