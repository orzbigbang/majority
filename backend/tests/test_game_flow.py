import asyncio

from app.game import GameManager
from app.models import GameSettings, GameStatus, Question


def test_game_progresses_from_countdown_to_result_to_finished() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [Question(id="only", title="A or B?", option_a="A", option_b="B")]
        manager.settings = GameSettings(countdown_duration=3, question_duration=20, result_duration=5)
        room = manager.create_room()
        await manager.join(room.id, "Alice", None, "alice")
        await manager.join(room.id, "Bob", None, "bob")

        try:
            await manager.start(room.id)
            assert False, "The game must not start while players are unready"
        except Exception as error:
            assert getattr(error, "detail", None) == "PLAYERS_NOT_READY"
        await manager.mark_ready(room.id, "bob")
        await manager.start(room.id, "alice")
        assert room.status == GameStatus.COUNTDOWN
        assert room.snapshot()["phase_duration"] == 3

        await manager.pause(room.id)
        assert room.status == GameStatus.PAUSED
        await manager.resume(room.id)
        assert room.status == GameStatus.COUNTDOWN

        await manager.begin_question(room)
        assert room.status == GameStatus.QUESTION
        await manager.answer(room.id, "alice", "only", "A")
        await manager.select_answer(room.id, "alice", "only", "B")
        await manager.answer(room.id, "bob", "only", "A")
        result = await manager.lock_and_score(room)
        assert room.status == GameStatus.SHOW_RESULT
        assert result["counts"] == {"A": 1, "B": 1}
        assert result["question"] == {"id": "only", "title": "A or B?", "option_a": "A", "option_b": "B"}
        assert result["answers"] == [{"player_id": "alice", "username": "Alice", "choice": "B"}, {"player_id": "bob", "username": "Bob", "choice": "A"}]
        assert room.players["alice"].answer_time_ms >= 0
        assert room.players["bob"].answer_time_ms >= 0
        assert room.history[0]["answers"] == [{"player_id": "alice", "username": "Alice", "choice": "B"}, {"player_id": "bob", "username": "Bob", "choice": "A"}]
        assert room.snapshot()["result"] == result

        await manager.next(room.id)
        assert room.status == GameStatus.FINISHED
        assert room.snapshot()["review"] == room.history

        await manager.reset(room.id)
        assert room.status == GameStatus.WAITING
        assert all(not player.ready and player.score == 0 for player in room.players.values())

        await manager.mark_ready(room.id, "bob")
        await manager.start(room.id, "alice")
        await manager.end(room.id)
        assert room.status == GameStatus.FINISHED

    asyncio.run(run())


def test_leaving_removes_the_player_and_their_current_answers() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [Question(id="only", title="A or B?", option_a="A", option_b="B")]
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        await manager.join(room.id, "Alice", None, "alice")
        await manager.join(room.id, "Bob", None, "bob")
        await manager.mark_ready(room.id, "bob")
        await manager.start(room.id, "alice")
        await manager.answer(room.id, "alice", "only", "A")

        await manager.leave(room.id, "alice")

        assert [player["id"] for player in room.snapshot()["players"]] == ["bob"]
        assert room.owner_id == "bob"
        assert room.snapshot()["answered"] == 0
        assert "alice" not in room.answers
        assert "alice" not in room.draft_answers

    asyncio.run(run())


def test_running_player_can_disconnect_and_rejoin_without_losing_game_state() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [Question(id="only", title="A or B?", option_a="A", option_b="B")]
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        alice = await manager.join(room.id, "Alice", None, "alice")
        await manager.join(room.id, "Bob", None, "bob")
        await manager.mark_ready(room.id, "bob")
        await manager.start(room.id, "alice")
        await manager.answer(room.id, "alice", "only", "A")

        await manager.set_connected(room.id, "alice", False)

        assert room.players["alice"].connected is False
        assert room.answers["alice"].choice == "A"
        assert room.owner_id == "alice"

        restored = await manager.join(room.id, "Alice", alice.session_id, "alice")
        await manager.set_connected(room.id, "alice", True)

        assert restored is room.players["alice"]
        assert restored.connected is True
        assert room.answers["alice"].choice == "A"

        try:
            await manager.join(room.id, "Impostor", "wrong-session", "alice")
            assert False, "A player ID alone must not be enough to resume a game"
        except Exception as error:
            assert getattr(error, "detail", None) == "INVALID_SESSION"

    asyncio.run(run())


def test_reset_removes_players_who_remained_offline_after_the_game() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")
        await manager.mark_ready(room.id, "player")
        await manager.start(room.id, "owner")
        await manager.set_connected(room.id, "player", False)
        await manager.end(room.id)

        await manager.reset(room.id, "owner")

        assert list(room.players) == ["owner"]
        assert room.owner_id == "owner"

    asyncio.run(run())


def test_owner_can_transfer_ownership_and_the_last_player_destroys_the_room() -> None:
    async def run() -> None:
        manager = GameManager()
        room = manager.create_room()
        await manager.join(room.id, "Alice", None, "alice")
        await manager.join(room.id, "Bob", None, "bob")
        await manager.join(room.id, "Carol", None, "carol")
        assert room.owner_id == "alice"

        try:
            await manager.mark_ready(room.id, "alice")
            assert False, "The owner must not have a ready state"
        except Exception as error:
            assert getattr(error, "detail", None) == "OWNER_DOES_NOT_READY"

        await manager.transfer_owner(room.id, "alice", "bob")
        assert room.owner_id == "bob"
        assert room.players["alice"].ready is False
        assert room.players["bob"].ready is False

        await manager.leave(room.id, "bob")
        assert room.owner_id == "alice"
        await manager.leave(room.id, "carol")
        assert room.id in manager.rooms
        await manager.leave(room.id, "alice")
        assert room.id not in manager.rooms

    asyncio.run(run())


def test_only_owner_can_start_after_every_other_player_is_ready() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")
        await manager.mark_ready(room.id, "player")

        try:
            await manager.start(room.id, "player")
            assert False, "A non-owner must not start the game"
        except Exception as error:
            assert getattr(error, "detail", None) == "OWNER_ONLY"

        await manager.start(room.id, "owner")
        assert room.status == GameStatus.QUESTION
        await manager.end(room.id)

        await manager.reset(room.id, "player")
        assert room.status == GameStatus.WAITING
        assert room.previous_game is not None
        assert [entry["id"] for entry in room.previous_game["leaderboard"]] == ["owner", "player"]

    asyncio.run(run())


def test_only_owner_can_update_waiting_room_settings() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [
            Question(id="one", title="One?", option_a="A", option_b="B", order=1),
            Question(id="two", title="Two?", option_a="A", option_b="B", order=2),
        ]
        room = manager.create_room(question_count=1)
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")

        try:
            await manager.update_room_settings(room.id, "player", 8, 2, 30, 10)
            assert False, "A non-owner must not update room settings"
        except Exception as error:
            assert getattr(error, "detail", None) == "OWNER_ONLY"

        changed = await manager.update_room_settings(room.id, "owner", 8, 2, 30, 10)
        assert changed.settings.max_players == 8
        assert changed.settings.question_duration == 30
        assert changed.settings.result_duration == 10
        assert [question.id for question in changed.questions] == ["one", "two"]
        assert changed.snapshot()["question_count"] == 2

        try:
            await manager.update_room_settings(room.id, "owner", 1, 2, 30, 10)
            assert False, "The room capacity must cover its current players"
        except Exception as error:
            assert getattr(error, "detail", None) == "MAX_PLAYERS_BELOW_CURRENT_PLAYERS"

        await manager.mark_ready(room.id, "player")
        await manager.start(room.id, "owner")
        try:
            await manager.update_room_settings(room.id, "owner", 8, 2, 30, 10)
            assert False, "Running room settings must be immutable"
        except Exception as error:
            assert getattr(error, "detail", None) == "GAME_ALREADY_STARTED"

    asyncio.run(run())


def test_player_can_toggle_and_explicitly_set_ready_state() -> None:
    async def run() -> None:
        manager = GameManager()
        room = manager.create_room()
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")

        await manager.mark_ready(room.id, "player")
        assert room.players["player"].ready is True
        await manager.mark_ready(room.id, "player")
        assert room.players["player"].ready is False

        await manager.mark_ready(room.id, "player", True)
        await manager.mark_ready(room.id, "player", True)
        assert room.players["player"].ready is True
        await manager.mark_ready(room.id, "player", False)
        assert room.players["player"].ready is False

    asyncio.run(run())
