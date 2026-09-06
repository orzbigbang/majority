import asyncio
import json
import logging

import pytest

from app.game import GameManager
from app.timing import command_timing, count, measured_room_lock


def records(caplog):
    return [json.loads(record.message.split(" ", 1)[1]) for record in caplog.records
            if record.message.startswith("room_command_timing ")]


@pytest.mark.parametrize("fails", [False, True])
def test_persistence_timing_preserves_result_rollback_and_privacy(monkeypatch, caplog, fails):
    monkeypatch.setenv("ROOM_TIMING_ENABLED", "true")
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    class Repository:
        def save_room(self, state, version):
            if fails:
                raise OSError("private storage error")
            return state.model_copy(update={"version": version + 1})

    async def run():
        manager = GameManager()
        room = manager.create_room()
        manager.repository = Repository()
        async def join():
            with command_timing(room.id, "join"):
                return await manager.join(room.id, "PrivateName", "PrivateSession", "PrivatePlayer")
        if fails:
            with pytest.raises(OSError):
                await join()
            assert not room.players
        else:
            assert (await join()).username == "PrivateName"
        assert not room.lock.locked()

    asyncio.run(run())
    record, = records(caplog)
    assert record["outcome"] == ("OSError" if fails else "ok")
    assert record["persistence_count"] == 1
    assert record["room_lock_hold_ms"] >= record["persistence_ms"]
    assert record["room_lock_wait_count"] == 1
    assert "Private" not in caplog.text and "private storage error" not in caplog.text


def test_concurrent_timing_contexts_and_cancelled_waiter_are_isolated(monkeypatch, caplog):
    monkeypatch.setenv("ROOM_TIMING_ENABLED", "true")
    caplog.set_level(logging.INFO, logger="uvicorn.error")

    async def run():
        lock = asyncio.Lock()
        await lock.acquire()
        entered = asyncio.Event()
        async def waiter():
            with command_timing("WAIT", "answer"):
                entered.set()
                async with measured_room_lock(lock):
                    pytest.fail("must not acquire occupied lock")
        task = asyncio.create_task(waiter())
        await entered.wait()
        with command_timing("OTHER", "answer"):
            count("conflict_retries")
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        assert lock.locked()
        lock.release()
        count("outside_trace")

    asyncio.run(run())
    by_room = {record["room_id"]: record for record in records(caplog)}
    assert by_room["WAIT"]["outcome"] == "CancelledError"
    assert "conflict_retries" not in by_room["WAIT"]
    assert by_room["OTHER"]["conflict_retries"] == 1
    assert all("outside_trace" not in record for record in by_room.values())


def test_timing_is_disabled_by_default(monkeypatch, caplog):
    monkeypatch.delenv("ROOM_TIMING_ENABLED", raising=False)
    caplog.set_level(logging.INFO, logger="uvicorn.error")
    with command_timing("ROOM", "answer"):
        count("conflict_retries")
    assert not records(caplog)
