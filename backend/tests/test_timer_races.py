import asyncio
from datetime import timedelta
from unittest.mock import patch

import pytest
from fastapi import HTTPException

import app.main as main
from app.game import GameManager
from app.models import GameSettings, GameStatus, IntroKind, now


async def result_room(manager):
    room = manager.create_room()
    await manager.join(room.id, "Owner", None, "owner")
    await manager.join(room.id, "Guest", None, "guest")
    await manager.mark_ready(room.id, "guest", True)
    await manager.start(room.id, "owner")
    room.status = GameStatus.SHOW_RESULT
    room.result_started_at = now() - timedelta(seconds=30)
    return room


def test_timer_does_not_skip_new_intro_in_another_due_room() -> None:
    async def run():
        manager = GameManager()
        manager.settings = GameSettings(countdown_duration=0)
        first = await result_room(manager)
        second = await result_room(manager)
        advanced = asyncio.Event()

        async def broadcast(room_id, *_args):
            if room_id == first.id and not advanced.is_set():
                # An admin advances this room while the timer broadcasts another.
                await manager.next(second.id)
                advanced.set()

        with patch.object(main, "manager", manager), patch.object(main, "repository", None), \
                patch.object(main, "broadcast", broadcast), patch.object(main, "save_finished_game"):
            async with main.lifespan(main.app):
                await asyncio.wait_for(advanced.wait(), timeout=1)
                await asyncio.sleep(0.02)
                assert second.status == GameStatus.TURN_INTRO
                assert second.intro_kind == IntroKind.PARENT_SELECT
                assert second.clock_metadata()["remaining_ms"] > 1000

    asyncio.run(run())


def test_timer_revalidates_after_waiting_for_room_lock() -> None:
    async def run():
        manager = GameManager()
        room = await result_room(manager)
        token = room.timer_token()
        async with room.lock:
            task = asyncio.create_task(manager.next(room.id, expected_clock=token))
            await asyncio.sleep(0)
            # Model a pause/resume completed while the timer waited for this lock.
            room.result_started_at = now()
            room.advance_clock_version()
        with pytest.raises(HTTPException) as error:
            await task
        assert error.value.detail == "ROOM_CLOCK_CHANGED"
        assert room.status == GameStatus.SHOW_RESULT
        assert room.current_question_index == 0

    asyncio.run(run())


def test_timer_rejects_matching_token_before_deadline() -> None:
    async def run():
        manager = GameManager()
        room = await result_room(manager)
        room.result_started_at = now()
        with pytest.raises(HTTPException):
            await manager.next(room.id, expected_clock=room.timer_token())
        assert room.current_question_index == 0

    asyncio.run(run())
