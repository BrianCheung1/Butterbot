import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL
from tests.test_safety import service

from butterbot.infrastructure.persistence.database import DatabaseRuntime, create_database_runtime


@pytest.mark.parametrize("recursive", [0, 1])
@pytest.mark.parametrize("insert", ["INSERT", "INSERT OR IGNORE", "INSERT OR REPLACE"])
@pytest.mark.parametrize("state", ["pending", "approved", "applied"])
async def test_proposal_targets_cannot_expand_after_creation(
    database_runtime: DatabaseRuntime, state: str, recursive: int, insert: str
) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    proposed = await admin.propose(
        actor_id=111,
        operation="freeze" if state == "applied" else "grant",
        targets=(123,),
        amount=0 if state == "applied" else (101 if state == "pending" else 1),
        reason="sealed scope",
        interaction_id=1,
    )
    assert proposed.status == state and proposed.proposal_id is not None
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        db.execute(f"PRAGMA recursive_triggers={recursive}")
        with pytest.raises(sqlite3.IntegrityError, match="sealed"):
            db.execute(
                f"{insert} INTO safety_proposal_targets VALUES (?,456)", (proposed.proposal_id.hex,)
            )


@pytest.mark.parametrize("state", ["pending", "approved", "applied"])
async def test_legacy_scopes_preserved_but_never_certified(tmp_path: Path, state: str) -> None:
    path = tmp_path / "legacy.sqlite3"
    config = Config("alembic.ini")
    config.set_main_option(
        "sqlalchemy.url",
        URL.create("sqlite+pysqlite", database=str(path)).render_as_string(hide_password=False),
    )
    command.upgrade(config, "20260922_0004")
    pid = UUID(int=1)
    with closing(sqlite3.connect(path)) as db, db:
        db.execute(
            "INSERT INTO safety_proposals VALUES (?,111,?,?,'legacy',1,999999,1,?,?)",
            (
                pid.hex,
                "freeze" if state == "applied" else "grant",
                0 if state == "applied" else 101,
                state,
                None if state == "pending" else 222,
            ),
        )
        db.execute("INSERT INTO safety_proposal_targets VALUES (?,123)", (pid.hex,))
        db.execute("INSERT INTO safety_proposal_targets VALUES (?,456)", (pid.hex,))
        before = db.execute("SELECT * FROM safety_proposals").fetchall()
    command.upgrade(config, "head")
    with closing(sqlite3.connect(path)) as db:
        assert db.execute("SELECT * FROM safety_proposals").fetchall() == before
        assert db.execute("SELECT * FROM safety_proposal_scopes").fetchall() == [(pid.hex, 2, 0)]
        for sql in [
            "UPDATE safety_proposal_scopes SET scope_verified=1",
            "DELETE FROM safety_proposal_scopes",
            "INSERT OR REPLACE INTO safety_proposal_scopes VALUES (?,2,1)",
            "INSERT INTO safety_proposal_targets VALUES (?,789)",
        ]:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute(sql, (pid.hex,) if "?" in sql else ())
    runtime = await create_database_runtime(path)
    try:
        admin = service(runtime)
        await admin.bootstrap((111, 222))
        result = await admin.approve(actor_id=222, proposal_id=pid, interaction_id=90)
        assert result.status == "unverified_scope"
    finally:
        await runtime.close()


async def test_verified_seal_is_immutable(database_runtime: DatabaseRuntime) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    result = await admin.propose(
        actor_id=111,
        operation="grant",
        targets=(123,),
        amount=101,
        reason="seal",
        interaction_id=10,
    )
    assert result.proposal_id is not None
    with closing(sqlite3.connect(database_runtime.database_path)) as db:
        for recursive in (0, 1):
            db.execute(f"PRAGMA recursive_triggers={recursive}")
            for sql in [
                "UPDATE safety_proposal_scopes SET target_count=2",
                "DELETE FROM safety_proposal_scopes",
                "INSERT OR REPLACE INTO safety_proposal_scopes VALUES (?,1,1)",
            ]:
                with pytest.raises(sqlite3.IntegrityError):
                    db.execute(sql, (result.proposal_id.hex,) if "?" in sql else ())
    assert (
        await admin.approve(actor_id=222, proposal_id=result.proposal_id, interaction_id=11)
    ).status == "approved"


@pytest.mark.parametrize("targets,count", [((), 0), ((123,), 2), ((0,), 1), ((0, 123), 2)])
def test_invalid_verified_seals_rejected(
    migrated_database: Path, targets: tuple[int, ...], count: int
) -> None:
    with closing(sqlite3.connect(migrated_database)) as db:
        pid = UUID(int=55).hex
        db.execute(
            "INSERT INTO safety_proposals VALUES (?,111,'grant',1,'test',1,9999,1,'pending',NULL)",
            (pid,),
        )
        for target in targets:
            db.execute("INSERT INTO safety_proposal_targets VALUES (?,?)", (pid, target))
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("INSERT INTO safety_proposal_scopes VALUES (?,?,1)", (pid, count))
        with pytest.raises(sqlite3.IntegrityError, match="verified sealed scope"):
            db.execute(
                "UPDATE safety_proposals SET status='approved',approver_id=222 WHERE id=?", (pid,)
            )


async def test_seal_failure_rolls_back_entire_proposal(database_runtime: DatabaseRuntime) -> None:
    admin = service(database_runtime)
    await admin.bootstrap((111, 222))
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        before = db.execute("SELECT COUNT(*) FROM safety_access_audit").fetchone()
        db.execute(
            "CREATE TRIGGER injected_seal_failure BEFORE INSERT ON safety_proposal_scopes "
            "BEGIN SELECT RAISE(ABORT,'injected seal failure'); END"
        )
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError, match="injected seal failure"):
        await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123, 456),
            amount=1,
            reason="rollback",
            interaction_id=88,
        )
    with closing(sqlite3.connect(database_runtime.database_path)) as db, db:
        for table in (
            "safety_proposals",
            "safety_proposal_targets",
            "safety_proposal_scopes",
            "operations_transport_requests",
        ):
            assert db.execute(f"SELECT COUNT(*) FROM {table}").fetchone() == (0,)
        assert db.execute("SELECT COUNT(*) FROM safety_access_audit").fetchone() == before
        db.execute("DROP TRIGGER injected_seal_failure")
    assert (
        await admin.propose(
            actor_id=111,
            operation="grant",
            targets=(123, 456),
            amount=1,
            reason="rollback",
            interaction_id=88,
        )
    ).status == "pending"
