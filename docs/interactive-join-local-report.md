# Interactive join development verification

2026-09-16: implemented the explicitly requested disposable Discord test launcher. This
report records local automated verification only; no live Discord interaction or native Linux
acceptance run was performed. The development token is not configured yet. The supplied test
guild/user IDs were written only to the ignored local `.env`, not committed documentation.

The separate module `butterbot.discord_app.development` requires a development token and
one test guild/user. It synchronizes only guild commands and rejects other users, other guilds,
and DMs before application execution. It exposes only ping/join, uses a freshly migrated
database per launch, and never consumes an existing database path or normal database settings.
Normal configuration, production composition, and all migration files are unchanged.

Observed with repository Windows `.venv/Scripts` executables:

- Ruff lint and formatting passed (100 files).
- Pyright passed with 0 errors and 0 warnings after fixing three initial test-typing diagnostics.
- Focused development suite: 26 passed in 0.71 seconds.
- Full pytest with verbose output, no cache provider, and 60-second faulthandler threshold:
  614 passed, 32 platform/permission skips in 47.99 seconds; no warnings or runtime test failures.
- `git diff --check` passed. `.env` and disposable `data/` files are ignored by Git.

Logs/JUnit are retained under `.gate-local/development-*`; `development-results.json` records
all final exit codes. `development-pyright-initial.log` retains the corrected typing diagnostics.
`development-source.json` records the dirty candidate source map; its SHA-256 is
`5d0d47372b49dba5c69ea2a10f3ffd5b5fdf08cc11662f369429c0d6abcdafa4`.
These changes are not identified by the existing HEAD alone and are not yet committed.

See README's interactive `/join` procedure to supply the token locally, start the launcher,
and exercise first/repeated joins. Each launch resets the test state. Native Linux and
independent release acceptance remain outstanding; this development mode grants no production
or later-slice acceptance.

## 2026-09-17 channel restriction and live startup

Added required `BUTTERBOT_DEV_CHANNEL_ID` and an exact channel check alongside guild and user
checks. Wrong channels, missing channel IDs, and thread IDs fail that check. The original
server selection is preserved; supplied IDs are stored in ignored `.env` only.

Current verification: Ruff lint/format and Pyright passed; full pytest passed with 623 passed,
32 skipped in 45.90 seconds. Final diff check passed. Logs, JUnit, and source binding are retained
under `.gate-local/channel-*`.

After local credentials were configured, the development bot started successfully, synchronized
guild commands, and connected to Discord's gateway. The log is `.gate-local/development-live.log`.
The user subsequently confirmed that interactive `/join` is working in the configured channel.
This is user-reported interactive verification, not an independently inspected Discord transcript
or native Linux acceptance. The commit containing this update records the development-mode
checkpoint; local credentials, disposable databases, and runtime logs remain excluded.
