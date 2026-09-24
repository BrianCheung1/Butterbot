from __future__ import annotations

import shutil
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock

import discord
import pytest

from butterbot.application.operations.idempotency import NullOperationsTelemetry
from butterbot.discord_app import development
from butterbot.discord_app.config import ConfigurationError
from butterbot.discord_app.development import (
    DevelopmentBot,
    DevelopmentSettings,
    create_disposable_database,
    load_development_settings,
    run_development,
)
from butterbot.infrastructure.persistence.database import create_database_runtime


@pytest.fixture
def dev_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    def ignore_dotenv(*, override: bool) -> None:
        del override

    monkeypatch.setattr(development, "load_dotenv", ignore_dotenv)
    monkeypatch.setenv("BUTTERBOT_DEV_DISCORD_TOKEN", "development-test-token")
    monkeypatch.setenv("DISCORD_TOKEN", "production-test-token")
    monkeypatch.setenv("BUTTERBOT_DEV_GUILD_ID", "123")
    monkeypatch.setenv("BUTTERBOT_DEV_USER_ID", "456")
    monkeypatch.setenv("BUTTERBOT_DEV_CHANNEL_ID", "789")


@pytest.fixture
def disposable_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    shutil.copytree(development.REPOSITORY_ROOT / "migrations", tmp_path / "migrations")
    monkeypatch.setattr(development, "REPOSITORY_ROOT", tmp_path.resolve())
    return tmp_path.resolve()


def test_development_settings_require_separate_token_and_hide_it_in_repr(
    dev_environment: None,
) -> None:
    settings = load_development_settings()
    assert (settings.guild_id, settings.user_id) == (123, 456)
    assert settings.discord_token == "development-test-token"
    assert settings.discord_token not in repr(settings)


@pytest.mark.parametrize("token", ["", "your-discord-bot-token", "production-test-token"])
def test_development_never_falls_back_to_production_token(
    dev_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    token: str,
) -> None:
    monkeypatch.setenv("BUTTERBOT_DEV_DISCORD_TOKEN", token)
    with pytest.raises(ConfigurationError):
        load_development_settings()


@pytest.mark.parametrize(
    "field", ["BUTTERBOT_DEV_GUILD_ID", "BUTTERBOT_DEV_USER_ID", "BUTTERBOT_DEV_CHANNEL_ID"]
)
@pytest.mark.parametrize("value", ["", "-1", "0", "1.0", "abc", "１２３", str(2**63)])
def test_development_requires_explicit_valid_server_and_tester(
    dev_environment: None,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    value: str,
) -> None:
    monkeypatch.setenv(field, value)
    with pytest.raises(ConfigurationError, match=field):
        load_development_settings()


def test_development_allocates_fresh_database_and_ignores_normal_database_environment(
    disposable_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing = disposable_checkout / "do-not-touch.sqlite3"
    existing.write_bytes(b"existing database stand-in")
    monkeypatch.setenv("BUTTERBOT_DATABASE_PATH", str(existing))
    monkeypatch.setenv("BUTTERBOT_DATABASE_ROOT", str(existing.parent))
    monkeypatch.setenv("BUTTERBOT_ECONOMY_MUTATIONS_ENABLED", "true")
    first, second = create_disposable_database(), create_disposable_database()
    assert first != second
    assert first.is_relative_to(disposable_checkout / "data" / "discord-development")
    assert existing.read_bytes() == b"existing database stand-in"
    for database in (first, second):
        connection = sqlite3.connect(database)
        try:
            assert connection.execute("SELECT version_num FROM alembic_version").fetchone() == (
                "20260924_0005",
            )
            assert connection.execute("SELECT COUNT(*) FROM players").fetchone() == (0,)
        finally:
            connection.close()


async def test_development_syncs_only_test_guild_with_default_intents() -> None:
    settings = DevelopmentSettings("not-used", 123, 456, 789)
    bot = DevelopmentBot(settings, AsyncMock(), NullOperationsTelemetry(), AsyncMock(), AsyncMock())
    sync = AsyncMock(return_value=[])
    bot.tree.sync = sync
    try:
        await bot.setup_hook()
        assert bot.tree.get_commands() == []
        assert {c.name for c in bot.tree.get_commands(guild=discord.Object(id=123))} == {
            "ping",
            "join",
            "balance",
            "admin_inspect",
            "admin_capability",
            "admin_propose",
            "admin_approve",
            "admin_proposal",
        }
        sync.assert_awaited_once()
        assert sync.await_args is not None
        assert sync.await_args.kwargs["guild"].id == 123
        assert bot.intents.value == discord.Intents.default().value
    finally:
        await bot.close()


def test_development_has_no_text_commands_that_bypass_interaction_scope() -> None:
    bot = DevelopmentBot(
        DevelopmentSettings("not-used", 123, 456, 789), AsyncMock(), NullOperationsTelemetry()
    )
    assert bot.help_command is None
    assert bot.all_commands == {}


@pytest.mark.parametrize(
    "guild_id,user_id,channel_id,allowed",
    [
        (123, 456, 789, True),
        (124, 456, 789, False),
        (None, 456, 789, False),
        (123, 457, 789, False),
        (123, 456, 790, False),
        (123, 456, None, False),
    ],
)
async def test_development_rejects_other_users_servers_and_direct_messages(
    guild_id: int | None,
    user_id: int,
    channel_id: int | None,
    allowed: bool,
) -> None:
    bot = DevelopmentBot(
        DevelopmentSettings("not-used", 123, 456, 789), AsyncMock(), NullOperationsTelemetry()
    )
    interaction = AsyncMock()
    interaction.guild_id = guild_id
    interaction.user.id = user_id
    interaction.channel_id = channel_id
    try:
        assert await bot.tree.interaction_check(interaction) is allowed
        if allowed:
            interaction.response.send_message.assert_not_awaited()
        else:
            interaction.response.send_message.assert_awaited_once()
            assert interaction.response.send_message.await_args.kwargs == {"ephemeral": True}
    finally:
        await bot.close()


async def test_development_runner_joins_on_disposable_storage_and_closes_after_discord_error(
    disposable_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_discord(bot: DevelopmentBot, token: str) -> None:
        assert token == "not-used"
        assert bot.balance_service is not None
        assert (await bot.balance_service.balance(discord_user_id=456)).status == "unjoined"
        assert (
            await bot.join_service.join(discord_user_id=456, interaction_id=789)
        ).status == "created"
        assert (
            await bot.join_service.join(discord_user_id=456, interaction_id=790)
        ).status == "already_joined"
        balance = await bot.balance_service.balance(discord_user_id=456)
        assert balance.status == "available" and balance.amount == 0
        await bot.close()
        raise RuntimeError("test disconnect")

    monkeypatch.setattr(development, "serve_until_shutdown", fake_discord)
    with pytest.raises(RuntimeError, match="test disconnect"):
        await run_development(DevelopmentSettings("not-used", 123, 456, 789))
    databases = list(
        (disposable_checkout / "data" / "discord-development").glob("*/butterbot.sqlite3")
    )
    assert len(databases) == 1
    # Acquisition by a successor proves the prior runtime released its process ownership.
    runtime = await create_database_runtime(databases[0])
    try:
        async with runtime.unit_of_work_factory() as transaction:
            player = await transaction.players.get_by_discord_user_id(456)
            assert player is not None
            wallet = await transaction.accounts.get_wallet(player.id)
            assert wallet is not None and wallet.amount == 0
    finally:
        await runtime.close()


def test_development_rejects_redirected_storage_before_allocation(
    disposable_checkout: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = Path.resolve
    parent = disposable_checkout / "data" / "discord-development"

    def redirected(self: Path, strict: bool = False) -> Path:
        if self == parent:
            return disposable_checkout / "elsewhere"
        return original(self, strict=strict)

    monkeypatch.setattr(Path, "resolve", redirected)
    with pytest.raises(ConfigurationError, match="symlink or junction"):
        create_disposable_database()
    assert not parent.exists()
