import asyncio

from fastapi.testclient import TestClient

from app.main import app, connections, manager, reaction_history, websocket_players
from app.models import GameStatus


def test_emoji_reactions_are_broadcast_and_validated() -> None:
    manager.rooms.clear()
    connections.clear()
    websocket_players.clear()
    reaction_history.clear()

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
                    "event_id": "reaction-1", "reaction_id": "clap",
                    "target_player_id": "target", "scope_id": "waiting",
                }})
                reaction = socket.receive_json()
                assert reaction["type"] == "emoji_reaction"
                assert reaction["payload"]["sender_username"] == "Sender"
                assert reaction["payload"]["target_username"] == "Target"
                assert reaction["payload"]["reaction_id"] == "clap"

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
