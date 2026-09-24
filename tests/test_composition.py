from __future__ import annotations

from pathlib import Path

import pytest

from butterbot.bootstrap import compose_application
from butterbot.discord_app import startup
from butterbot.discord_app.config import (
    PRODUCTION_DATABASE_PATH,
    PRODUCTION_DATABASE_ROOT,
    Settings,
)
from butterbot.infrastructure.persistence.readiness import DatabaseReadinessError


async def test_composition_wires_fail_closed_mutation_policy_and_disposes(
    migrated_database: Path,
) -> None:
    application = await compose_application(
        Settings(
            discord_token="not-used",
            release_id="test-build",
            database_path=migrated_database,
            database_root=migrated_database.parent,
            database_volume_id=None,
            economy_mutations_enabled=False,
        )
    )
    try:
        decision = application.mutation_eligibility.evaluate()
        assert decision.allowed is False
        assert decision.reason == "globally_disabled"
        assert application.database.readiness.observed_revision == "20260922_0004"
        result = await application.join_service.join(discord_user_id=123, interaction_id=456)
        assert result.status == "disabled"
        assert result.replayed is False
        replay = await application.join_service.join(discord_user_id=123, interaction_id=456)
        assert replay.status == "disabled"
        assert replay.replayed is True
        async with application.database.unit_of_work_factory() as transaction:
            assert await transaction.players.get_by_discord_user_id(123) is None
    finally:
        await application.close()


async def test_composition_rejects_enabled_mutations_without_production_volume_identity() -> None:
    with pytest.raises(DatabaseReadinessError) as caught:
        await compose_application(
            Settings(
                discord_token="not-used",
                release_id="test-build",
                database_path=Path(PRODUCTION_DATABASE_PATH),
                database_root=Path(PRODUCTION_DATABASE_ROOT),
                database_volume_id=None,
                economy_mutations_enabled=True,
            )
        )

    assert caught.value.category == "unsafe_storage"


async def test_composition_fails_before_discord_for_missing_database(tmp_path: Path) -> None:
    settings = Settings(
        discord_token="not-used",
        release_id="test-build",
        database_path=tmp_path / "missing.sqlite3",
        database_root=tmp_path,
        database_volume_id=None,
        economy_mutations_enabled=False,
    )

    with pytest.raises(DatabaseReadinessError) as caught:
        await compose_application(settings)

    assert caught.value.category == "missing_database"


async def test_startup_does_not_construct_discord_when_database_is_unsafe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = Settings(
        discord_token="not-used",
        release_id="test-build",
        database_path=tmp_path / "missing.sqlite3",
        database_root=tmp_path,
        database_volume_id=None,
        economy_mutations_enabled=False,
    )
    bot_constructed = False

    def fake_create_bot() -> object:
        nonlocal bot_constructed
        bot_constructed = True
        return object()

    monkeypatch.setattr(startup, "load_settings", lambda: settings)
    monkeypatch.setattr(startup, "create_bot", fake_create_bot)

    with pytest.raises(DatabaseReadinessError):
        await startup.run()

    assert bot_constructed is False
