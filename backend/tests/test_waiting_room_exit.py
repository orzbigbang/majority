import asyncio
import json
from urllib.parse import urlencode

import pytest
from starlette.websockets import WebSocket

from app import main
from test_room_persistence import MemoryRoomRepository, configured_manager


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize("guest_present", [False, True])
def test_exit_after_renaming_waiting_room(monkeypatch, explicit, guest_present):
    async def run():
        repository = MemoryRoomRepository()
        manager = configured_manager(repository)
        monkeypatch.setattr(main, "manager", manager)
        for name in ("connections", "websocket_players", "websocket_send_locks", "websocket_priority_waiters"):
            monkeypatch.setattr(main, name, {})
        room = manager.create_room()
        owner = await manager.join(room.id, "Owner", None, "owner")
        if guest_present:
            await manager.join(room.id, "Guest", None, "guest")
        incoming = asyncio.Queue()
        incoming.put_nowait({"type": "websocket.connect"})
        incoming.put_nowait({"type": "websocket.receive", "text": json.dumps({
            "type": "update_room_settings", "payload": {
                "title": "Renamed room", "max_players": 12, "round_count": 1,
                "selection_duration": 15, "question_duration": 20,
                "between_question_duration": 5,
            }})})
        if explicit:
            incoming.put_nowait({"type": "websocket.receive", "text": '{"type":"leave_room"}'})
        else:
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
        messages = []

        async def send(message):
            if message["type"] == "websocket.send":
                item = json.loads(message["text"])
                if item["type"] == "room_left":
                    # The acknowledgement must follow durable deletion.
                    assert (repository.get_room(room.id) is not None) == guest_present
                messages.append(item)

        ws = WebSocket({"type": "websocket", "path": f"/ws/rooms/{room.id}",
                        "query_string": urlencode({"player_id": owner.id,
                                                   "session_id": owner.session_id}).encode(),
                        "headers": []}, incoming.get, send)
        await asyncio.wait_for(main.websocket(ws, room.id), 3)
        assert any(item["type"] == "room_settings_saved" for item in messages)
        assert any(item["type"] == "game_state" and item["payload"]["title"] == "Renamed room"
                   for item in messages)
        assert any(item["type"] == "room_left" for item in messages) == explicit
        assert (room.id in manager.rooms) == guest_present
        if guest_present:
            assert manager.room(room.id).owner_id == "guest"
            assert {player.id for player in repository.get_room(room.id).players} == {"guest"}
        else:
            assert repository.get_room(room.id) is None
        assert not main.websocket_players

    asyncio.run(run())
