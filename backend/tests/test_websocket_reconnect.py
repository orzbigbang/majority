import asyncio

from fastapi.testclient import TestClient

from app.main import app, connections, manager, websocket_players
from app.models import GameSettings


def test_websocket_disconnect_during_game_preserves_player_for_reconnect() -> None:
    manager.rooms.clear()
    connections.clear()
    websocket_players.clear()

    async def prepare_room():
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        owner = await manager.join(room.id, "Owner", None, "owner")
        player = await manager.join(room.id, "Player", None, "player")
        await manager.mark_ready(room.id, player.id)
        await manager.start(room.id, owner.id)
        return room, owner

    room, owner = asyncio.run(prepare_room())
    websocket_url = f"/ws/rooms/{room.id}?player_id={owner.id}&session_id={owner.session_id}"

    try:
        with TestClient(app) as client:
            with client.websocket_connect(websocket_url) as socket:
                connected_state = socket.receive_json()
                assert connected_state["type"] == "game_state"
                assert connected_state["payload"]["status"] == "QUESTION"

            assert owner.id in room.players
            assert room.players[owner.id].connected is False

            restored = client.post(
                f"/api/rooms/{room.id}/join",
                json={"username": owner.username, "player_id": owner.id, "session_id": owner.session_id},
            )
            assert restored.status_code == 200

            with client.websocket_connect(websocket_url) as socket:
                reconnected_state = socket.receive_json()
                restored_owner = next(
                    player for player in reconnected_state["payload"]["players"] if player["id"] == owner.id
                )
                assert restored_owner["connected"] is True
    finally:
        manager.rooms.clear()
        connections.clear()
        websocket_players.clear()
