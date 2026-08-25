# Butterbot

Butterbot is a planned Discord economy game designed for long-lived player progression.
It currently provides a runnable Discord bootstrap and a `/ping` health check. Gameplay has
not been implemented.

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
```

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

Start with [the documentation index](docs/README.md) before making design or architecture
decisions. The dependency-ordered implementation plan is in [ROADMAP.md](ROADMAP.md).
