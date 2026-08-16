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
        await manager.mark_ready(room.id, "alice")
        await manager.mark_ready(room.id, "bob")
        await manager.set_connected(room.id, "alice", False)
        assert room.snapshot()["players"][0]["connected"] is False
        await manager.set_connected(room.id, "alice", True)
        await manager.start(room.id)
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

        await manager.mark_ready(room.id, "alice")
        await manager.mark_ready(room.id, "bob")
        await manager.start(room.id)
        await manager.end(room.id)
        assert room.status == GameStatus.FINISHED

    asyncio.run(run())
