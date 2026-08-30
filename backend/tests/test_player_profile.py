import asyncio

from fastapi.testclient import TestClient

from app.main import admin_tokens, app, manager, save_finished_game, saved_game_runs, volatile_history, volatile_users


def test_player_can_update_profile_and_review_finished_game() -> None:
    volatile_users.clear()
    volatile_history.clear()
    saved_game_runs.clear()
    manager.rooms.clear()

    with TestClient(app) as client:
        identity = client.post("/api/players/identity", json={"player_id": "alice", "username": "Alice"}).json()
        assert identity["player_id"] == "alice"

        updated = client.put("/api/players/alice", json={"username": "Alicia", "bio": "直感派", "favorite_choice": "B"})
        assert updated.status_code == 200
        assert updated.json()["bio"] == "直感派"

        async def finish_game() -> None:
            settings = manager.settings.model_copy(update={"countdown_duration": 0})
            room = manager.create_room(settings, 1)
            await manager.join(room.id, "Alicia", None, "alice")
            await manager.join(room.id, "Bob", None, "bob")
            await manager.mark_ready(room.id, "bob")
            await manager.start(room.id, "alice")
            question = room.current_question
            assert question
            await manager.answer(room.id, "alice", question.id, "B")
            await manager.answer(room.id, "bob", question.id, "A")
            await manager.lock_and_score(room)
            await manager.next(room.id)
            save_finished_game(room)
            save_finished_game(room)

        asyncio.run(finish_game())
        profile = client.get("/api/players/alice")
        assert profile.status_code == 200
        payload = profile.json()
        assert payload["username"] == "Alicia"
        assert payload["stats"]["games"] == 1
        assert len(payload["history"]) == 1
        assert payload["history"][0]["answers"][0]["choice"] == "B"

        admin_tokens.add("test-admin-token")
        users = client.get("/api/admin/users", headers={"Authorization": "Bearer test-admin-token"})
        assert users.status_code == 200
        alice = next(user for user in users.json() if user["id"] == "alice")
        assert alice["stats"] == {"games": 1, "wins": 1, "best_rank": 1, "average_rank": 1.0}
        assert alice["last_active_at"] is not None
        assert alice["recent_games"][0]["room_id"] == payload["history"][0]["room_id"]
        assert "answers" not in alice["recent_games"][0]

    manager.rooms.clear()
    admin_tokens.discard("test-admin-token")


def test_joining_a_room_restores_a_missing_persistent_profile() -> None:
    volatile_users.clear()
    manager.rooms.clear()

    try:
        with TestClient(app) as client:
            room = manager.create_room()
            response = client.post(f"/api/rooms/{room.id}/join", json={"player_id": "returning-player", "username": "Returning"})

            assert response.status_code == 200
            assert response.json()["player_id"] == "returning-player"
            assert volatile_users["returning-player"].username == "Returning"
            assert volatile_users["returning-player"].created_at is not None
            assert volatile_users["returning-player"].last_active_at is not None
    finally:
        manager.rooms.clear()
        volatile_users.clear()
