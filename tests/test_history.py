import sqlite3
from contextlib import closing
from uuid import UUID

import pytest
from tests.test_corrections import correct, funded
from tests.test_join import Eligibility
from tests.test_join import service as joins
from tests.test_safety import service

from butterbot.application.economy.balance import BalanceService
from butterbot.application.economy.history import HistoryCursor, HistoryEntry
from butterbot.infrastructure.persistence.database import DatabaseRuntime


async def test_history_self_only_keyset_ties_and_privacy(database_runtime: DatabaseRuntime) -> None:
    original = await funded(database_runtime)
    admin = service(database_runtime, grant_eligibility=Eligibility())
    for i in range(12):
        proposal = await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123,),
            amount=1,
            reason="secret operator reason",
            interaction_id=100 + i,
        )
        assert proposal.proposal_id is not None
        await admin.execute_grant(
            actor_id=111, proposal_id=proposal.proposal_id, interaction_id=200 + i
        )
    assert await correct(database_runtime, original, amount=3) == "corrected"
    await joins(database_runtime).join(discord_user_id=456, interaction_id=300)
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    assert not (await query.history(discord_user_id=456)).entries
    entries: list[HistoryEntry] = []
    cursor = None
    for _ in range(4):
        page = await query.history(discord_user_id=123, cursor=cursor)
        assert len(page.entries) <= 5
        assert "secret" not in repr(page)
        entries.extend(page.entries)
        cursor = page.next_cursor
        if cursor is None:
            break
    assert len(entries) == len({e.transaction_id for e in entries}) == 14
    assert [(e.committed_at_ms, e.transaction_id) for e in entries] == sorted(
        ((e.committed_at_ms, e.transaction_id) for e in entries), reverse=True
    )
    assert sum(e.amount for e in entries) == 19
    assert all(e.resulting_balance is not None for e in entries)


@pytest.mark.parametrize(
    "case,expected",
    [
        ("unjoined", "unjoined"),
        ("inactive", "inactive"),
        ("missing_wallet", "unavailable"),
        ("frozen", "available"),
    ],
)
async def test_history_read_only_state_cases(
    database_runtime: DatabaseRuntime, case: str, expected: str
) -> None:
    if case != "unjoined":
        await funded(database_runtime)
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        if case == "inactive":
            db.execute("UPDATE players SET lifecycle_state='pseudonymized'")
        if case == "missing_wallet":
            # Simulate pre-existing missing wallet without mutating sealed grant rows.
            db.execute(
                "INSERT INTO players VALUES ('aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa', 999, 0, 'active')"
            )
        if case == "frozen":
            db.execute("INSERT INTO safety_restrictions VALUES (0)")
        before = tuple(db.iterdump())
    result = await BalanceService(database_runtime.unit_of_work_factory.read_snapshot).history(
        discord_user_id=999 if case == "missing_wallet" else 123
    )
    assert result.status == expected
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        assert tuple(db.iterdump()) == before


async def test_history_cursor_validated(database_runtime: DatabaseRuntime) -> None:
    query = BalanceService(database_runtime.unit_of_work_factory.read_snapshot)
    with pytest.raises(ValueError):
        await query.history(discord_user_id=123, cursor=HistoryCursor(-1, UUID(int=0)))
