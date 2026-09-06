"""Exercise Starlette's real state changes when sending hits a closed transport."""
import asyncio
import json
from urllib.parse import urlencode

import pytest
from starlette.websockets import WebSocket, WebSocketState

from app import main
from app.game import GameManager
from app.models import GameSettings


@pytest.mark.parametrize("failed_message", ["game_state", "time_sync"])
def test_send_side_disconnect_exits_receive_loop_and_allows_reconnect(monkeypatch, failed_message):
    async def run():
        manager = GameManager()
        monkeypatch.setattr(main, "manager", manager)
        for name in ("connections", "websocket_players", "websocket_send_locks", "websocket_priority_waiters"):
            monkeypatch.setattr(main, name, {})
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        owner = await manager.join(room.id, "Owner", None, "owner")
        guest = await manager.join(room.id, "Guest", None, "guest")
        await manager.mark_ready(room.id, guest.id)
        await manager.start(room.id, owner.id)
        await manager.advance_intro(room)
        await manager.advance_intro(room)
        await manager.choose_question(room.id, owner.id, room.selection_question_ids[0])
        await manager.advance_intro(room)
        question_id = room.current_question.id
        await manager.select_answer(room.id, owner.id, question_id, "B")
        original_score = owner.score
        query = urlencode({"player_id": owner.id, "session_id": owner.session_id}).encode()

        def socket(fail_on=None):
            incoming = asyncio.Queue()
            incoming.put_nowait({"type": "websocket.connect"})
            incoming.put_nowait({"type": "websocket.receive", "text": json.dumps({
                "type": "time_sync", "payload": {"client_sent_at": 1}})})
            incoming.put_nowait({"type": "websocket.disconnect", "code": 1000})
            messages = []

            async def send(message):
                if message["type"] == "websocket.send":
                    payload = json.loads(message["text"])
                    if payload["type"] == fail_on:
                        # WebSocket.send converts this to WebSocketDisconnect and
                        # marks application_state DISCONNECTED, even before receive.
                        raise OSError("peer closed transport during broadcast")
                    messages.append(payload)

            return WebSocket({"type": "websocket", "path": f"/ws/rooms/{room.id}",
                "query_string": query, "headers": []}, incoming.get, send), messages

        broken, _ = socket(failed_message)
        await asyncio.wait_for(main.websocket(broken, room.id), 2)
        assert broken.application_state == WebSocketState.DISCONNECTED
        assert broken not in main.connections[room.id]
        assert broken not in main.websocket_players
        assert broken not in main.websocket_send_locks
        assert broken not in main.websocket_priority_waiters
        assert room.players[owner.id].connected is False
        assert room.owner_id == owner.id
        assert room.players[owner.id].score == original_score
        assert room.draft_answers[owner.id].choice == "B"

        restored, messages = socket()
        await asyncio.wait_for(main.websocket(restored, room.id), 2)
        snapshot = next(m["payload"] for m in messages if m["type"] == "game_state")
        assert next(p for p in snapshot["players"] if p["id"] == owner.id)["connected"] is True
        assert any(m["type"] == "time_sync" for m in messages)
        assert room.draft_answers[owner.id].choice == "B"
        assert not main.websocket_players

    asyncio.run(run())
