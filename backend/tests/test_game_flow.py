import asyncio
from datetime import timedelta

from app.game import GameManager
from app.models import GameSettings, GameStatus, Question


def test_one_round_gives_every_player_one_parent_turn() -> None:
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
        assert all(player.score == 1 for player in room.players.values())
        assert room.clock_version == 1
        assert room.snapshot()["phase_duration"] == 3
        assert room.snapshot()["clock"]["server_time"].endswith("+00:00")
        assert room.snapshot()["clock"]["phase"] == GameStatus.COUNTDOWN
        assert room.snapshot()["clock"]["duration_ms"] == 4000
        assert room.snapshot()["clock"]["running"] is True

        await manager.pause(room.id)
        assert room.status == GameStatus.PAUSED
        assert room.clock_version == 2
        paused_clock = room.snapshot()["clock"]
        assert paused_clock["running"] is False
        assert paused_clock["ends_at"] is None
        assert paused_clock["remaining_ms"] > 0
        await manager.resume(room.id)
        assert room.status == GameStatus.COUNTDOWN
        assert room.clock_version == 3

        await manager.begin_selection(room)
        assert room.status == GameStatus.SELECTING
        assert room.clock_version == 4
        assert room.snapshot()["question_count"] == 2
        assert room.snapshot()["current_parent_id"] == "alice"
        try:
            await manager.choose_question(room.id, "bob", "only")
            assert False, "Only the current parent may choose a question"
        except Exception as error:
            assert getattr(error, "detail", None) == "PARENT_ONLY"
        await manager.choose_question(room.id, "alice", "only")
        assert room.status == GameStatus.PARENT_ANSWERING
        assert room.clock_version == 5
        assert room.snapshot()["question"]["id"] == "only"
        try:
            await manager.answer(room.id, "bob", "only", "A")
            assert False, "Other players must wait for the parent to answer"
        except Exception as error:
            assert getattr(error, "detail", None) == "PARENT_ANSWERS_FIRST"
        await manager.select_answer(room.id, "alice", "only", "B")
        await manager.answer(room.id, "alice", "only", "B")
        assert room.status == GameStatus.QUESTION
        assert room.clock_version == 6
        try:
            await manager.answer(room.id, "alice", "only", "A")
            assert False, "The parent's answer must be locked before other players answer"
        except Exception as error:
            assert getattr(error, "detail", None) == "PARENT_ANSWER_LOCKED"
        await manager.answer(room.id, "bob", "only", "A")
        result = await manager.lock_and_score(room)
        assert room.status == GameStatus.SHOW_RESULT
        assert room.clock_version == 7
        assert result["counts"] == {"A": 1, "B": 1}
        assert result["parent_id"] == "alice"
        assert result["majority_choice"] == "B"
        assert result["scores"] == {"alice": 2, "bob": -1}
        assert room.players["alice"].score == 3
        assert room.players["bob"].score == 0
        assert result["question"] == {"id": "only", "title": "A or B?", "option_a": "A", "option_b": "B"}
        assert result["answers"] == [{"player_id": "alice", "username": "Alice", "choice": "B"}, {"player_id": "bob", "username": "Bob", "choice": "A"}]
        assert room.players["alice"].answer_time_ms >= 0
        assert room.players["bob"].answer_time_ms >= 0
        assert room.history[0]["answers"] == [{"player_id": "alice", "username": "Alice", "choice": "B"}, {"player_id": "bob", "username": "Bob", "choice": "A"}]
        assert room.snapshot()["result"] == result

        await manager.next(room.id)
        assert room.status == GameStatus.SELECTING
        assert room.clock_version == 8
        assert room.snapshot()["current_parent_id"] == "bob"
        await manager.choose_question(room.id, "bob", "only")
        await manager.answer(room.id, "bob", "only", "A")
        await manager.answer(room.id, "alice", "only", "A")
        second_result = await manager.lock_and_score(room)
        assert second_result["parent_id"] == "bob"
        assert second_result["majority_choice"] == "A"
        await manager.next(room.id)
        assert room.status == GameStatus.FINISHED
        assert room.clock_version == 12
        assert room.snapshot()["review"] == room.history
        assert [turn["parent_id"] for turn in room.history] == ["alice", "bob"]

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
        await manager.choose_question(room.id, "alice", "only")
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
        await manager.choose_question(room.id, "alice", "only")
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
        assert room.status == GameStatus.SELECTING
        assert room.current_parent_id == "owner"
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
        room = manager.create_room(round_count=1)
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")

        try:
            await manager.update_room_settings(room.id, "player", 8, 2, 15, 30, 10)
            assert False, "A non-owner must not update room settings"
        except Exception as error:
            assert getattr(error, "detail", None) == "OWNER_ONLY"

        changed = await manager.update_room_settings(room.id, "owner", 8, 2, 25, 30, 10)
        assert changed.settings.max_players == 8
        assert changed.settings.selection_duration == 25
        assert changed.settings.question_duration == 30
        assert changed.settings.result_duration == 10
        assert [question.id for question in changed.questions] == ["one", "two"]
        assert changed.round_count == 2
        assert changed.snapshot()["question_count"] == 4

        try:
            await manager.update_room_settings(room.id, "owner", 1, 2, 15, 30, 10)
            assert False, "The room capacity must cover its current players"
        except Exception as error:
            assert getattr(error, "detail", None) == "MAX_PLAYERS_BELOW_CURRENT_PLAYERS"

        await manager.mark_ready(room.id, "player")
        await manager.start(room.id, "owner")
        try:
            await manager.update_room_settings(room.id, "owner", 8, 2, 15, 30, 10)
            assert False, "Running room settings must be immutable"
        except Exception as error:
            assert getattr(error, "detail", None) == "GAME_ALREADY_STARTED"

    asyncio.run(run())


def test_selection_offers_three_unused_questions_and_auto_selects_on_timeout() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [Question(id=f"q{index}", title=f"Question {index}", option_a="A", option_b="B", order=index) for index in range(1, 5)]
        manager.settings = GameSettings(countdown_duration=0, selection_duration=15)
        room = manager.create_room(round_count=3)
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player", None, "player")
        await manager.mark_ready(room.id, "player")
        await manager.start(room.id, "owner")

        first_options = room.snapshot()["question_options"]
        assert len(first_options) == 3
        assert room.snapshot()["clock"]["phase"] == GameStatus.SELECTING
        assert room.snapshot()["clock"]["duration_ms"] == 15_000

        first_question_id = first_options[0]["id"]
        await manager.choose_question(room.id, "owner", first_question_id)
        assert room.used_question_ids == [first_question_id]
        room.status = GameStatus.SHOW_RESULT
        await manager.next(room.id)
        assert first_question_id not in {item["id"] for item in room.snapshot()["question_options"]}

        timed_options = {item["id"] for item in room.snapshot()["question_options"]}
        room.selection_started_at = now() - timedelta(seconds=16)
        await manager.auto_choose_question(room)
        assert room.status == GameStatus.PARENT_ANSWERING
        assert room.selected_question is not None
        assert room.selected_question.id in timed_options
        assert room.selected_question.id != first_question_id

        selected_ids = {first_question_id, room.selected_question.id}
        for _ in range(2):
            room.status = GameStatus.SHOW_RESULT
            await manager.next(room.id)
            next_options = {item["id"] for item in room.snapshot()["question_options"]}
            assert next_options.isdisjoint(selected_ids)
            next_question_id = next(iter(next_options))
            await manager.choose_question(room.id, room.current_parent_id, next_question_id)
            selected_ids.add(next_question_id)
        assert selected_ids == {"q1", "q2", "q3", "q4"}

        room.status = GameStatus.SHOW_RESULT
        await manager.next(room.id)
        assert len(room.snapshot()["question_options"]) == 3
        assert room.used_question_ids == []

    from app.models import now

    asyncio.run(run())


def test_disconnected_parent_turn_is_deferred_and_restored_after_reconnect() -> None:
    async def run() -> None:
        manager = GameManager()
        manager.questions = [Question(id="only", title="A or B?", option_a="A", option_b="B")]
        manager.settings = GameSettings(countdown_duration=0)
        room = manager.create_room()
        await manager.join(room.id, "Owner", None, "owner")
        await manager.join(room.id, "Player 1", None, "player-1")
        await manager.join(room.id, "Player 2", None, "player-2")
        await manager.mark_ready(room.id, "player-1")
        await manager.mark_ready(room.id, "player-2")
        await manager.start(room.id, "owner")

        await manager.set_connected(room.id, "owner", False)
        room.parent_disconnected_at = now() - timedelta(seconds=9)
        await manager.defer_disconnected_parent(room)
        assert room.current_parent_id == "player-1"
        assert room.parent_turn_order == ["player-1", "player-2", "owner"]

        await manager.set_connected(room.id, "owner", True)
        room.status = GameStatus.SHOW_RESULT
        await manager.next(room.id)
        assert room.current_parent_id == "player-2"
        room.status = GameStatus.SHOW_RESULT
        await manager.next(room.id)
        assert room.current_parent_id == "owner"
        assert room.status == GameStatus.SELECTING
        assert room.selection_started_at is not None

    from app.models import now

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
