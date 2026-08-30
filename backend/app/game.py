from __future__ import annotations

import asyncio
import secrets
from copy import deepcopy
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException

from .models import Answer, GameSettings, GameStatus, Player, Question, now
from .repository.base import GameRepository
from .scoring import STRATEGIES

COUNTDOWN_START_CUE_DURATION = 1


class Room:
    def __init__(self, room_id: str, questions: list[Question], settings: GameSettings) -> None:
        self.id, self.questions, self.settings = room_id, questions, settings
        self.status = GameStatus.WAITING
        self.players: dict[str, Player] = {}
        self.owner_id: str | None = None
        self.answers: dict[str, Answer] = {}
        self.draft_answers: dict[str, Answer] = {}
        self.current_question_index = 0
        self.question_started_at = None
        self.countdown_started_at = None
        self.result_started_at = None
        self.last_result: dict | None = None
        self.history: list[dict] = []
        self.previous_game: dict | None = None
        self.game_run_id: str | None = None
        self.paused_status: GameStatus | None = None
        self.paused_remaining_seconds: float | None = None
        self.lock = asyncio.Lock()

    @property
    def current_question(self) -> Question | None:
        return self.questions[self.current_question_index] if self.current_question_index < len(self.questions) else None

    def snapshot(self, include_question: bool = True) -> dict:
        question = self.current_question
        payload = {"room_id": self.id, "status": self.status, "owner_id": self.owner_id, "players": [{"id": p.id, "username": p.username, "score": p.score, "connected": p.connected, "ready": p.ready} for p in self.players.values()], "current_question_index": self.current_question_index, "question_count": len(self.questions), "answered": len(self.draft_answers), "settings": self.settings.model_dump(), "previous_game": self.previous_game}
        if self.status == GameStatus.COUNTDOWN:
            payload.update({"phase_started_at": self.countdown_started_at.isoformat() if self.countdown_started_at else None, "phase_duration": self.settings.countdown_duration})
        if include_question and question and (self.status == GameStatus.QUESTION or (self.status == GameStatus.PAUSED and self.paused_status == GameStatus.QUESTION)):
            payload["question"] = {"id": question.id, "title": question.title, "option_a": question.option_a, "option_b": question.option_b, "duration": self.settings.question_duration, "started_at": self.question_started_at.isoformat() if self.question_started_at else None}
            if self.status == GameStatus.QUESTION:
                payload.update({"phase_started_at": self.question_started_at.isoformat() if self.question_started_at else None, "phase_duration": self.settings.question_duration})
        if self.status == GameStatus.SHOW_RESULT or (self.status == GameStatus.PAUSED and self.paused_status == GameStatus.SHOW_RESULT):
            payload.update({"phase_started_at": self.result_started_at.isoformat() if self.result_started_at else None, "phase_duration": self.settings.result_duration, "result": self.last_result})
        if self.status == GameStatus.PAUSED:
            payload.update({"paused_status": self.paused_status, "phase_duration": self.paused_remaining_seconds})
        if self.status == GameStatus.FINISHED:
            payload["review"] = self.history
        return payload


class GameManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.questions: list[Question] = [
            Question(id="q1", title="猫と犬、どっちが好き？", option_a="猫", option_b="犬", order=1),
            Question(id="q2", title="朝型と夜型、どっち？", option_a="朝型", option_b="夜型", order=2),
            Question(id="q3", title="海と山、どっちへ行きたい？", option_a="海", option_b="山", order=3),
        ]
        self.settings = GameSettings()

    def load_persistent_data(self, repository: GameRepository) -> None:
        questions = repository.list_questions()
        if questions:
            self.questions = questions
            legacy_defaults = {
                ("q1", "你更喜欢猫还是狗？", "猫", "狗"): ("猫と犬、どっちが好き？", "猫", "犬"),
                ("q2", "早起还是熬夜？", "早起", "熬夜"): ("朝型と夜型、どっち？", "朝型", "夜型"),
                ("q3", "海边还是山里？", "海边", "山里"): ("海と山、どっちへ行きたい？", "海", "山"),
            }
            migrated = False
            for question in self.questions:
                translated = legacy_defaults.get((question.id, question.title, question.option_a, question.option_b))
                if translated:
                    question.title, question.option_a, question.option_b = translated
                    migrated = True
            if migrated:
                repository.save_questions(self.questions)
        else:
            repository.save_questions(self.questions)
        settings = repository.get_settings()
        if settings:
            if settings.game_name in {"Party Quiz", "パーティークイズ"}:
                settings.game_name = "マジョリティ"
                repository.save_settings(settings)
            self.settings = settings
        else:
            repository.save_settings(self.settings)

    def create_room(self, settings: GameSettings | None = None, question_count: int | None = None) -> Room:
        if not self.questions:
            raise HTTPException(400, "Add at least one question first")
        ordered_questions = sorted([q.model_copy() for q in self.questions], key=lambda q: q.order)
        if question_count is not None and question_count > len(ordered_questions):
            raise HTTPException(400, "NOT_ENOUGH_QUESTIONS")
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while (room_id := "".join(secrets.choice(alphabet) for _ in range(4))) in self.rooms:
            pass
        room = Room(room_id, ordered_questions[:question_count] if question_count is not None else ordered_questions, (settings or self.settings).model_copy())
        self.rooms[room_id] = room
        return room

    def room(self, room_id: str) -> Room:
        room = self.rooms.get(room_id.upper())
        if not room:
            raise HTTPException(404, "ROOM_NOT_FOUND")
        return room

    async def join(self, room_id: str, username: str, session_id: str | None, player_id: str | None = None) -> Player:
        room = self.room(room_id)
        async with room.lock:
            if player_id and player_id in room.players:
                existing = room.players[player_id]
                if not session_id or session_id != existing.session_id:
                    raise HTTPException(401, "INVALID_SESSION")
                existing.username = username.strip()
                return existing
            if session_id:
                existing = next((p for p in room.players.values() if p.session_id == session_id), None)
                if existing:
                    return existing
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            if len(room.players) >= room.settings.max_players:
                raise HTTPException(409, "ROOM_FULL")
            player = Player(id=player_id or str(uuid4()), session_id=session_id or str(uuid4()), username=username.strip())
            room.players[player.id] = player
            if room.owner_id is None:
                room.owner_id = player.id
            return player

    def lobby(self) -> list[dict]:
        return [
            {
                "room_id": room.id,
                "status": room.status,
                "player_count": len(room.players),
                "max_players": room.settings.max_players,
                "game_name": room.settings.game_name,
            }
            for room in sorted(self.rooms.values(), key=lambda item: item.id)
        ]

    async def update_room(self, room_id: str, game_name: str | None, max_players: int | None) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "Only waiting rooms can be edited")
            if max_players is not None:
                if max_players < len(room.players):
                    raise HTTPException(409, "MAX_PLAYERS_BELOW_CURRENT_PLAYERS")
                room.settings.max_players = max_players
            if game_name is not None:
                room.settings.game_name = game_name.strip()
            return room

    async def update_room_settings(
        self,
        room_id: str,
        requested_by: str,
        max_players: int,
        question_count: int,
        question_duration: int,
        between_question_duration: int,
    ) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            if requested_by != room.owner_id:
                raise HTTPException(403, "OWNER_ONLY")
            if max_players < len(room.players):
                raise HTTPException(409, "MAX_PLAYERS_BELOW_CURRENT_PLAYERS")
            ordered_questions = sorted([question.model_copy() for question in self.questions], key=lambda question: question.order)
            if question_count > len(ordered_questions):
                raise HTTPException(400, "NOT_ENOUGH_QUESTIONS")
            room.questions = ordered_questions[:question_count]
            room.settings.max_players = max_players
            room.settings.question_duration = question_duration
            room.settings.result_duration = between_question_duration
            return room

    async def delete_room(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "Only waiting rooms can be deleted")
            del self.rooms[room.id]
            return room

    async def start(self, room_id: str, requested_by: str | None = None) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "Game is not waiting")
            if requested_by is not None and requested_by != room.owner_id:
                raise HTTPException(403, "OWNER_ONLY")
            participants = [player for player in room.players.values() if player.id != room.owner_id]
            if not participants or any(not player.ready for player in participants):
                raise HTTPException(409, "PLAYERS_NOT_READY")
            room.game_run_id = str(uuid4())
            if room.settings.countdown_duration:
                room.history.clear()
                room.status, room.countdown_started_at = GameStatus.COUNTDOWN, now()
            else:
                room.history.clear()
                room.status, room.question_started_at = GameStatus.QUESTION, now()
            return room

    async def mark_ready(self, room_id: str, player_id: str, ready: bool | None = None) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            player = room.players.get(player_id)
            if not player:
                raise HTTPException(401, "INVALID_SESSION")
            if player_id == room.owner_id:
                raise HTTPException(409, "OWNER_DOES_NOT_READY")
            player.ready = not player.ready if ready is None else ready
            return room

    async def transfer_owner(self, room_id: str, owner_id: str, new_owner_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            if owner_id != room.owner_id:
                raise HTTPException(403, "OWNER_ONLY")
            if new_owner_id == owner_id or new_owner_id not in room.players:
                raise HTTPException(404, "PLAYER_NOT_FOUND")
            room.owner_id = new_owner_id
            room.players[owner_id].ready = False
            room.players[new_owner_id].ready = False
            return room

    async def set_connected(self, room_id: str, player_id: str, connected: bool) -> Room:
        room = self.room(room_id)
        async with room.lock:
            player = room.players.get(player_id)
            if not player:
                raise HTTPException(401, "INVALID_SESSION")
            player.connected = connected
            return room

    async def leave(self, room_id: str, player_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            # Socket cleanup can race when the same player has multiple connections.
            if room.players.pop(player_id, None) is None:
                return room
            room.answers.pop(player_id, None)
            room.draft_answers.pop(player_id, None)
            if room.last_result:
                room.last_result.get("scores", {}).pop(player_id, None)
                room.last_result["leaderboard"] = self.leaderboard(room)
            if not room.players:
                room.owner_id = None
                self.rooms.pop(room.id, None)
            elif player_id == room.owner_id:
                room.owner_id = next(iter(room.players))
                room.players[room.owner_id].ready = False
            return room

    async def begin_question(self, room: Room) -> Room:
        async with room.lock:
            if room.status != GameStatus.COUNTDOWN:
                raise HTTPException(409, "Countdown is not active")
            room.status, room.question_started_at = GameStatus.QUESTION, now()
            return room

    async def pause(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status not in {GameStatus.COUNTDOWN, GameStatus.QUESTION, GameStatus.SHOW_RESULT}:
                raise HTTPException(409, "GAME_NOT_PAUSABLE")
            if room.status == GameStatus.COUNTDOWN:
                started_at, duration = room.countdown_started_at, room.settings.countdown_duration + COUNTDOWN_START_CUE_DURATION
            elif room.status == GameStatus.QUESTION:
                started_at, duration = room.question_started_at, room.settings.question_duration
            else:
                started_at, duration = room.result_started_at, room.settings.result_duration
            elapsed = (now() - started_at).total_seconds() if started_at else 0
            room.paused_remaining_seconds = max(0, duration - elapsed)
            room.paused_status = room.status
            room.status = GameStatus.PAUSED
            return room

    async def resume(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.PAUSED or not room.paused_status or room.paused_remaining_seconds is None:
                raise HTTPException(409, "GAME_NOT_PAUSED")
            resumed_status, remaining = room.paused_status, room.paused_remaining_seconds
            if resumed_status == GameStatus.COUNTDOWN:
                room.countdown_started_at = now() - timedelta(seconds=room.settings.countdown_duration + COUNTDOWN_START_CUE_DURATION - remaining)
            elif resumed_status == GameStatus.QUESTION:
                room.question_started_at = now() - timedelta(seconds=room.settings.question_duration - remaining)
            elif resumed_status == GameStatus.SHOW_RESULT:
                room.result_started_at = now() - timedelta(seconds=room.settings.result_duration - remaining)
            room.status = resumed_status
            room.paused_status = None
            room.paused_remaining_seconds = None
            return room

    async def reset(self, room_id: str, requested_by: str | None = None) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if requested_by is not None and requested_by not in room.players:
                raise HTTPException(401, "INVALID_SESSION")
            if requested_by is not None and room.status != GameStatus.FINISHED:
                raise HTTPException(409, "GAME_NOT_FINISHED")
            if room.status == GameStatus.FINISHED:
                room.previous_game = {"leaderboard": deepcopy(self.leaderboard(room)), "review": deepcopy(room.history)}
            room.status = GameStatus.WAITING
            room.current_question_index = 0
            room.answers.clear()
            room.draft_answers.clear()
            room.question_started_at = None
            room.countdown_started_at = None
            room.result_started_at = None
            room.last_result = None
            room.history.clear()
            room.paused_status = None
            room.paused_remaining_seconds = None
            disconnected_player_ids = [player.id for player in room.players.values() if not player.connected]
            for player_id in disconnected_player_ids:
                room.players.pop(player_id, None)
            if room.owner_id not in room.players:
                room.owner_id = next(iter(room.players), None)
            for player in room.players.values():
                player.score = 0
                player.answer_time_ms = 0
                player.ready = False
            return room

    async def end(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status in {GameStatus.WAITING, GameStatus.FINISHED}:
                raise HTTPException(409, "GAME_NOT_RUNNING")
            room.status = GameStatus.FINISHED
            room.paused_status = None
            room.paused_remaining_seconds = None
            return room

    async def select_answer(self, room_id: str, player_id: str, question_id: str, choice: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.QUESTION or not room.current_question or room.current_question.id != question_id:
                raise HTTPException(409, "INVALID_ANSWER")
            if room.question_started_at and now() > room.question_started_at + timedelta(seconds=room.settings.question_duration):
                raise HTTPException(409, "QUESTION_EXPIRED")
            if player_id not in room.players:
                raise HTTPException(401, "INVALID_SESSION")
            room.draft_answers[player_id] = Answer(player_id=player_id, question_id=question_id, choice=choice)
            return room

    async def answer(self, room_id: str, player_id: str, question_id: str, choice: str) -> Room:
        room = await self.select_answer(room_id, player_id, question_id, choice)
        async with room.lock:
            room.answers[player_id] = room.draft_answers[player_id]
            return room

    async def lock_and_score(self, room: Room) -> dict:
        async with room.lock:
            if room.status != GameStatus.QUESTION:
                raise HTTPException(409, "No active question")
            room.status = GameStatus.LOCK
            question = room.current_question
            assert question
            room.answers = {**room.answers, **room.draft_answers}
            results = STRATEGIES[question.score_strategy].calculate(question, list(room.answers.values()))
            question_started_at = room.question_started_at or now()
            for player in room.players.values():
                answer = room.answers.get(player.id)
                elapsed_ms = int((answer.answered_at - question_started_at).total_seconds() * 1000) if answer else room.settings.question_duration * 1000
                player.answer_time_ms += max(0, elapsed_ms)
            for player_id, score in results.items():
                room.players[player_id].score += score
            counts = {"A": sum(a.choice == "A" for a in room.answers.values()), "B": sum(a.choice == "B" for a in room.answers.values())}
            review = {
                "question": {"id": question.id, "title": question.title, "option_a": question.option_a, "option_b": question.option_b},
                "counts": counts,
                "answers": [{"player_id": player.id, "username": player.username, "choice": room.answers.get(player.id).choice if player.id in room.answers else None} for player in room.players.values()],
                "scores": results,
            }
            room.history.append(review)
            room.status = GameStatus.SHOW_RESULT
            room.result_started_at = now()
            room.last_result = {"question_id": question.id, "question": review["question"], "counts": counts, "answers": review["answers"], "scores": results, "leaderboard": self.leaderboard(room)}
            return room.last_result

    async def next(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status not in {GameStatus.SHOW_RESULT, GameStatus.LOCK}:
                raise HTTPException(409, "Question must be scored first")
            room.current_question_index += 1
            room.answers.clear()
            room.draft_answers.clear()
            room.last_result = None
            room.result_started_at = None
            if room.current_question is None:
                room.status = GameStatus.FINISHED
            else:
                room.status, room.question_started_at = GameStatus.QUESTION, now()
            return room

    def leaderboard(self, room: Room) -> list[dict]:
        return [{"rank": i + 1, "id": p.id, "username": p.username, "score": p.score} for i, p in enumerate(sorted(room.players.values(), key=lambda p: (-p.score, p.answer_time_ms, p.username)))]
