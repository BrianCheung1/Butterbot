# Butterbot

Butterbot is a planned Discord economy game designed for long-lived player progression.
It currently provides a runnable Discord bootstrap, a `/ping` health check, and the Slice 1.0
persistence/composition foundation. Gameplay has not been implemented.

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

The bot uses Discord's default, non-privileged intents. It synchronizes `/ping` globally at
startup, and Discord may take time to make a newly synchronized global command visible.

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
