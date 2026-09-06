import asyncio
import json
from urllib.parse import urlencode

import pytest
from fastapi import HTTPException
from starlette.websockets import WebSocket
from app import main
from app.game import GameManager
from app.models import GameSettings

async def setup_game():
    manager = GameManager()
    manager.settings = GameSettings(countdown_duration=0)
    room = manager.create_room()
    owner = await manager.join(room.id, 'Owner', None, 'owner')
    guest = await manager.join(room.id, 'Guest', None, 'guest')
    await manager.mark_ready(room.id, guest.id)
    await manager.start(room.id, owner.id)
    await manager.advance_intro(room)
    await manager.advance_intro(room)
    await manager.choose_question(room.id, owner.id, room.selection_question_ids[0])
    await manager.advance_intro(room)
    return manager, room, owner

@pytest.mark.parametrize('operation', ['answer', 'select_answer'])
def test_stale_turn_with_same_question_is_rejected(operation):
    async def run():
        manager, room, owner = await setup_game()
        question_id = room.current_question.id
        old_turn = room.turn_id
        room.game_run_id = 'another-game'
        with pytest.raises(HTTPException) as error:
            await getattr(manager, operation)(room.id, owner.id, question_id, 'A', turn_id=old_turn)
        assert error.value.detail == 'INVALID_ANSWER'
        assert not room.answers and not room.draft_answers
        await getattr(manager, operation)(room.id, owner.id, question_id, 'B', turn_id=room.turn_id)
        assert room.draft_answers[owner.id].choice == 'B'
    asyncio.run(run())

def test_websocket_receipt_and_error_echo_request_scope(monkeypatch):
    async def run():
        manager, room, owner = await setup_game()
        monkeypatch.setattr(main, 'manager', manager)
        for name in ('connections', 'websocket_players', 'websocket_send_locks', 'websocket_priority_waiters'):
            monkeypatch.setattr(main, name, {})
        scope = {'turn_id': room.turn_id, 'question_id': room.current_question.id}
        incoming = asyncio.Queue()
        incoming.put_nowait({'type': 'websocket.connect'})
        for request_id, turn_id in [('stale', 'old-game:0'), ('current', room.turn_id)]:
            incoming.put_nowait({'type': 'websocket.receive', 'text': json.dumps({'type': 'answer', 'payload': {**scope, 'turn_id': turn_id, 'request_id': request_id, 'choice': 'B'}})})
        incoming.put_nowait({'type': 'websocket.disconnect', 'code': 1000})
        messages = []
        async def send(message):
            if message['type'] == 'websocket.send':
                messages.append(json.loads(message['text']))
        socket = WebSocket({'type': 'websocket', 'path': '/', 'headers': [], 'query_string': urlencode({'player_id': owner.id, 'session_id': owner.session_id}).encode()}, incoming.get, send)
        await main.websocket(socket, room.id)
        receipt = next(m['payload'] for m in messages if m['type'] == 'answer_saved')
        assert receipt == {**scope, 'request_id': 'current', 'choice': 'B'}
        error = next(m['payload'] for m in messages if m['type'] == 'error')
        assert error['request_id'] == 'stale' and error['turn_id'] == 'old-game:0'
        assert room.answers[owner.id].choice == 'B'
    asyncio.run(run())
