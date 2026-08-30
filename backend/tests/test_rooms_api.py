from fastapi.testclient import TestClient

from app.main import app, manager


def test_any_player_can_create_a_room_without_admin_authentication() -> None:
    manager.rooms.clear()

    try:
        with TestClient(app) as client:
            response = client.post("/api/rooms", json={
                "username": "Owner",
                "player_id": "owner-id",
                "max_players": 6,
                "round_count": 1,
                "selection_duration": 25,
                "question_duration": 30,
                "between_question_duration": 10,
            })

            assert response.status_code == 200
            payload = response.json()
            room = payload["room"]
            assert room["status"] == "WAITING"
            assert payload["player_id"] == "owner-id"
            assert room["owner_id"] == "owner-id"
            assert room["players"][0]["id"] == "owner-id"
            assert room["players"][0]["username"] == "Owner"
            assert room["settings"]["max_players"] == 6
            assert room["settings"]["selection_duration"] == 25
            assert room["settings"]["question_duration"] == 30
            assert room["settings"]["result_duration"] == 10
            assert room["round_count"] == 1
            assert room["question_count"] == 1
            assert room["room_id"] in {item["room_id"] for item in client.get("/api/rooms").json()}
    finally:
        manager.rooms.clear()
