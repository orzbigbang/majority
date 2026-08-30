import asyncio
import time
from uuid import UUID

from fastapi.testclient import TestClient
from fastapi import HTTPException

from app.main import (
    ROOM_REACTION_LIMIT_PER_SECOND,
    app,
    broadcast,
    clear_room_reactions,
    connections,
    manager,
    reaction_history,
    record_reaction,
    room_reaction_history,
    websocket_players,
    websocket_priority_waiters,
    websocket_send_locks,
)
import app.main as main_module
from app.models import GameStatus


def test_emoji_reactions_are_broadcast_and_validated() -> None:
    manager.rooms.clear()
    connections.clear()
    websocket_players.clear()
    reaction_history.clear()
    room_reaction_history.clear()

    async def prepare_room():
        room = manager.create_room()
        sender = await manager.join(room.id, "Sender", None, "sender")
        await manager.join(room.id, "Target", None, "target")
        return room, sender

    room, sender = asyncio.run(prepare_room())
    websocket_url = f"/ws/rooms/{room.id}?player_id={sender.id}&session_id={sender.session_id}"

    try:
        with TestClient(app) as client:
            with client.websocket_connect(websocket_url) as socket:
                assert socket.receive_json()["type"] == "game_state"

                socket.send_json({"type": "emoji_reaction", "payload": {
                    "event_id": "client-controlled-id", "reaction_id": "clap",
                    "target_player_id": "target", "scope_id": "waiting",
                }})
                reaction = socket.receive_json()
                assert reaction["type"] == "emoji_reaction"
                assert reaction["payload"]["sender_username"] == "Sender"
                assert reaction["payload"]["target_username"] == "Target"
                assert reaction["payload"]["reaction_id"] == "clap"
                UUID(reaction["payload"]["event_id"])
                assert reaction["payload"]["event_id"] != "client-controlled-id"

                socket.send_json({"type": "emoji_reaction", "payload": {
                    "event_id": "reaction-self", "reaction_id": "like",
                    "target_player_id": "sender", "scope_id": "waiting",
                }})
                assert socket.receive_json()["payload"]["code"] == "SELF_REACTION_NOT_ALLOWED"

                socket.send_json({"type": "emoji_reaction", "payload": {
                    "event_id": "reaction-fast", "reaction_id": "laugh",
                    "target_player_id": "target", "scope_id": "waiting",
                }})
                assert socket.receive_json()["payload"]["code"] == "REACTION_RATE_LIMITED"

                reaction_history.clear()
                room.status = GameStatus.QUESTION
                socket.send_json({"type": "emoji_reaction", "payload": {
                    "event_id": "reaction-question", "reaction_id": "wow",
                    "target_player_id": "target", "scope_id": "waiting",
                }})
                assert socket.receive_json()["payload"]["code"] == "REACTIONS_NOT_AVAILABLE"
    finally:
        manager.rooms.clear()
        connections.clear()
        websocket_players.clear()
        reaction_history.clear()
        room_reaction_history.clear()


def test_room_reaction_limit_and_cleanup() -> None:
    reaction_history.clear()
    room_reaction_history.clear()
    room_id = "RATE"
    for index in range(ROOM_REACTION_LIMIT_PER_SECOND):
        record_reaction(room_id, f"player-{index}")

    try:
        record_reaction(room_id, "one-too-many")
        assert False, "The room-wide burst limit must reject excess reactions"
    except HTTPException as error:
        assert error.detail == "ROOM_REACTION_RATE_LIMITED"

    clear_room_reactions(room_id)
    assert room_id not in room_reaction_history
    assert all(key[0] != room_id for key in reaction_history)


def test_broadcast_sends_to_connections_concurrently() -> None:
    class SlowSocket:
        def __init__(self) -> None:
            self.messages = []

        async def send_json(self, message) -> None:
            await asyncio.sleep(0.05)
            self.messages.append(message)

    async def run() -> None:
        sockets = [SlowSocket() for _ in range(3)]
        connections["FAST"] = set(sockets)
        started_at = time.monotonic()
        await broadcast("FAST", "emoji_reaction", {"event_id": "fast"})
        elapsed = time.monotonic() - started_at
        assert elapsed < 0.12
        assert all(socket.messages[0]["type"] == "emoji_reaction" for socket in sockets)

    try:
        asyncio.run(run())
    finally:
        connections.pop("FAST", None)
        websocket_send_locks.clear()
        websocket_priority_waiters.clear()


def test_concurrent_broadcasts_do_not_overlap_on_one_connection() -> None:
    class GuardedSocket:
        def __init__(self) -> None:
            self.active_sends = 0
            self.max_active_sends = 0
            self.messages = []

        async def send_json(self, message) -> None:
            self.active_sends += 1
            self.max_active_sends = max(self.max_active_sends, self.active_sends)
            await asyncio.sleep(0.02)
            self.messages.append(message)
            self.active_sends -= 1

    async def run() -> None:
        socket = GuardedSocket()
        connections["ORDERED"] = {socket}
        await asyncio.gather(
            broadcast("ORDERED", "first", {}),
            broadcast("ORDERED", "second", {}),
        )
        assert socket.max_active_sends == 1
        assert len(socket.messages) == 2

    try:
        asyncio.run(run())
    finally:
        connections.pop("ORDERED", None)
        websocket_send_locks.clear()
        websocket_priority_waiters.clear()


def test_busy_connection_drops_reactions_without_delaying_priority_messages() -> None:
    class BusySocket:
        def __init__(self) -> None:
            self.started = asyncio.Event()
            self.messages = []

        async def send_json(self, message) -> None:
            self.started.set()
            await asyncio.sleep(0.05)
            self.messages.append(message)

    async def run() -> None:
        socket = BusySocket()
        connections["BUSY"] = {socket}
        priority_send = asyncio.create_task(broadcast("BUSY", "game_state", {"revision": 1}))
        await socket.started.wait()
        started_at = time.monotonic()
        await broadcast("BUSY", "emoji_reaction", {"event_id": "drop-me"})
        assert time.monotonic() - started_at < 0.02
        await priority_send
        assert [message["type"] for message in socket.messages] == ["game_state"]

    try:
        asyncio.run(run())
    finally:
        connections.pop("BUSY", None)
        websocket_send_locks.clear()
        websocket_priority_waiters.clear()


def test_send_timeout_includes_time_waiting_for_connection_lock() -> None:
    class WaitingSocket:
        async def send_json(self, message) -> None:
            raise AssertionError("The occupied connection lock should time out before sending")

    async def run() -> None:
        socket = WaitingSocket()
        occupied_lock = asyncio.Lock()
        await occupied_lock.acquire()
        websocket_send_locks[socket] = occupied_lock
        websocket_players[socket] = ("TIMEOUT", "player")
        connections["TIMEOUT"] = {socket}
        original_timeout = main_module.WEBSOCKET_SEND_TIMEOUT_SECONDS
        main_module.WEBSOCKET_SEND_TIMEOUT_SECONDS = 0.03
        try:
            started_at = time.monotonic()
            sent = await main_module.send_message(socket, "game_state", {})
            assert sent is False
            assert time.monotonic() - started_at < 0.1
            assert socket not in connections["TIMEOUT"]
        finally:
            main_module.WEBSOCKET_SEND_TIMEOUT_SECONDS = original_timeout
            occupied_lock.release()

    try:
        asyncio.run(run())
    finally:
        connections.pop("TIMEOUT", None)
        websocket_players.clear()
        websocket_send_locks.clear()
        websocket_priority_waiters.clear()
