import asyncio
from copy import deepcopy
from threading import Event

from app.game import GameManager
from app.models import GameSettings, GameStatus, Question, RoomState
from app.repository.base import RoomConflictError


class MemoryRoomRepository:
    """Small compare-and-swap room store used to model two Cloud Run instances."""

    def __init__(self) -> None:
        self.rooms: dict[str, RoomState] = {}
        self.conflict_once = False

    def get_room(self, room_id: str) -> RoomState | None:
        room = self.rooms.get(room_id.upper())
        return deepcopy(room) if room else None

    def list_rooms(self) -> list[RoomState]:
        return [deepcopy(room) for room in sorted(self.rooms.values(), key=lambda item: item.id)]

    def save_room(self, room: RoomState, expected_version: int | None) -> RoomState:
        stored = self.rooms.get(room.id)
        if self.conflict_once and stored and expected_version is not None:
            self.conflict_once = False
            self.rooms[room.id] = stored.model_copy(deep=True, update={"version": stored.version + 1})
            raise RoomConflictError("simulated competing instance")
        if expected_version is None:
            if stored:
                raise RoomConflictError("already exists")
            next_version = 1
        else:
            if not stored or stored.version != expected_version:
                raise RoomConflictError("stale room")
            next_version = expected_version + 1
        saved = room.model_copy(deep=True, update={"version": next_version})
        self.rooms[room.id] = saved
        return deepcopy(saved)

    def delete_room(self, room_id: str, expected_version: int | None = None) -> None:
        stored = self.rooms.get(room_id.upper())
        if stored and expected_version is not None and stored.version != expected_version:
            raise RoomConflictError("stale room")
        self.rooms.pop(room_id.upper(), None)


class BlockingRoomRepository(MemoryRoomRepository):
    def __init__(self) -> None:
        super().__init__()
        self.block_next_save = False
        self.save_started = Event()
        self.release_save = Event()

    def save_room(self, room: RoomState, expected_version: int | None) -> RoomState:
        if self.block_next_save:
            self.block_next_save = False
            self.save_started.set()
            if not self.release_save.wait(timeout=0.5):
                raise AssertionError("room save blocked the event loop")
        return super().save_room(room, expected_version)


def configured_manager(repository: MemoryRoomRepository) -> GameManager:
    manager = GameManager(repository)
    manager.questions = [Question(id="only", title="A or B?", option_a="A", option_b="B")]
    manager.settings = GameSettings(countdown_duration=0, question_duration=20, result_duration=5)
    for state in repository.list_rooms():
        manager.accept_remote_state(state.id, state)
    return manager


def test_room_created_on_one_instance_is_visible_and_joinable_on_another() -> None:
    async def run() -> None:
        repository = MemoryRoomRepository()
        first = configured_manager(repository)
        second = configured_manager(repository)

        room = first.create_room(title="Persisted title")
        owner = await first.join(room.id, "Owner", None, "owner")
        # Production instances receive creation and updates through the room watch.
        second.accept_remote_state(room.id, repository.get_room(room.id))

        assert [item["room_id"] for item in second.lobby()] == [room.id]
        assert second.lobby()[0]["title"] == "Persisted title"
        joined = await second.join(room.id, "Player", None, "player")

        # Production instances receive this update through the Firestore room watch.
        first.accept_remote_state(room.id, repository.get_room(room.id))
        refreshed = first.room(room.id)
        assert joined.id == "player"
        assert list(refreshed.players) == ["owner", "player"]
        assert refreshed.players["owner"].session_id == owner.session_id
        assert repository.get_room(room.id).players[0].session_id is None
        assert repository.get_room(room.id).players[0].session_hash is not None

    asyncio.run(run())


def test_running_room_is_restored_after_process_restart() -> None:
    async def run() -> None:
        repository = MemoryRoomRepository()
        first = configured_manager(repository)
        room = first.create_room()
        await first.join(room.id, "Owner", None, "owner")
        await first.join(room.id, "Player", None, "player")
        await first.mark_ready(room.id, "player")
        await first.start(room.id, "owner")
        await first.choose_question(room.id, "owner", "only")
        version_before_answer = repository.get_room(room.id).version
        await first.answer(room.id, "owner", "only", "A")
        assert repository.get_room(room.id).version == version_before_answer + 1

        restarted = configured_manager(repository)
        restored = restarted.room(room.id)

        assert restored.status == GameStatus.QUESTION
        assert restored.owner_id == "owner"
        assert list(restored.players) == ["owner", "player"]
        assert restored.answers["owner"].choice == "A"
        assert restored.question_started_at is not None
        assert restored.game_run_id is not None
        assert restored.clock_version == room.clock_version
        assert restored.snapshot()["clock"]["revision"] == room.clock_version

    asyncio.run(run())


def test_deleting_the_last_player_removes_the_persistent_room() -> None:
    async def run() -> None:
        repository = MemoryRoomRepository()
        first = configured_manager(repository)
        room = first.create_room()
        await first.join(room.id, "Owner", None, "owner")

        await first.leave(room.id, "owner")

        restarted = configured_manager(repository)
        assert restarted.lobby() == []

    asyncio.run(run())


def test_room_command_retries_after_another_instance_wins_the_write() -> None:
    async def run() -> None:
        repository = MemoryRoomRepository()
        manager = configured_manager(repository)
        room = manager.create_room()
        repository.conflict_once = True

        joined = await manager.join(room.id, "Owner", None, "owner")

        assert joined.id == "owner"
        assert repository.get_room(room.id).players[0].id == "owner"
        assert repository.get_room(room.id).version == 3

    asyncio.run(run())


def test_room_save_does_not_block_the_async_event_loop() -> None:
    async def run() -> None:
        repository = BlockingRoomRepository()
        manager = configured_manager(repository)
        room = manager.create_room()
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")
        await manager.mark_ready(room.id, "player")
        await manager.start(room.id, "owner")
        await manager.choose_question(room.id, "owner", "only")

        repository.block_next_save = True
        answer_task = asyncio.create_task(manager.answer(room.id, "owner", "only", "A"))
        for _ in range(100):
            if repository.save_started.is_set():
                break
            await asyncio.sleep(0.001)

        assert repository.save_started.is_set()
        assert not answer_task.done()
        repository.release_save.set()
        await answer_task

    asyncio.run(run())
