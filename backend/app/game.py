from __future__ import annotations

import asyncio
import secrets
from datetime import timedelta
from uuid import uuid4

from fastapi import HTTPException

from .models import Answer, GameSettings, GameStatus, Player, Question, now
from .scoring import STRATEGIES


class Room:
    def __init__(self, room_id: str, questions: list[Question], settings: GameSettings) -> None:
        self.id, self.questions, self.settings = room_id, questions, settings
        self.status = GameStatus.WAITING
        self.players: dict[str, Player] = {}
        self.answers: dict[str, Answer] = {}
        self.current_question_index = 0
        self.question_started_at = None
        self.lock = asyncio.Lock()

    @property
    def current_question(self) -> Question | None:
        return self.questions[self.current_question_index] if self.current_question_index < len(self.questions) else None

    def snapshot(self, include_question: bool = True) -> dict:
        question = self.current_question
        payload = {"room_id": self.id, "status": self.status, "players": [{"id": p.id, "username": p.username, "score": p.score, "connected": p.connected} for p in self.players.values()], "current_question_index": self.current_question_index, "question_count": len(self.questions), "answered": len(self.answers), "settings": self.settings.model_dump()}
        if include_question and question and self.status == GameStatus.QUESTION:
            payload["question"] = {"id": question.id, "title": question.title, "option_a": question.option_a, "option_b": question.option_b, "duration": self.settings.question_duration, "started_at": self.question_started_at.isoformat() if self.question_started_at else None}
        return payload


class GameManager:
    def __init__(self) -> None:
        self.rooms: dict[str, Room] = {}
        self.questions: list[Question] = [
            Question(id="q1", title="你更喜欢猫还是狗？", option_a="猫", option_b="狗", order=1),
            Question(id="q2", title="早起还是熬夜？", option_a="早起", option_b="熬夜", order=2),
            Question(id="q3", title="海边还是山里？", option_a="海边", option_b="山里", order=3),
        ]
        self.settings = GameSettings()

    def create_room(self) -> Room:
        if not self.questions:
            raise HTTPException(400, "Add at least one question first")
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        while (room_id := "".join(secrets.choice(alphabet) for _ in range(4))) in self.rooms:
            pass
        room = Room(room_id, sorted([q.model_copy() for q in self.questions], key=lambda q: q.order), self.settings.model_copy())
        self.rooms[room_id] = room
        return room

    def room(self, room_id: str) -> Room:
        room = self.rooms.get(room_id.upper())
        if not room:
            raise HTTPException(404, "ROOM_NOT_FOUND")
        return room

    async def join(self, room_id: str, username: str, session_id: str | None) -> Player:
        room = self.room(room_id)
        async with room.lock:
            if session_id:
                existing = next((p for p in room.players.values() if p.session_id == session_id), None)
                if existing:
                    existing.connected = True
                    return existing
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            if len(room.players) >= room.settings.max_players:
                raise HTTPException(409, "ROOM_FULL")
            player = Player(session_id=session_id or str(uuid4()), username=username.strip())
            room.players[player.id] = player
            return player

    async def start(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "Game is not waiting")
            room.status, room.question_started_at = GameStatus.QUESTION, now()
            return room

    async def answer(self, room_id: str, player_id: str, question_id: str, choice: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.QUESTION or not room.current_question or room.current_question.id != question_id:
                raise HTTPException(409, "INVALID_ANSWER")
            if room.question_started_at and now() > room.question_started_at + timedelta(seconds=room.settings.question_duration):
                raise HTTPException(409, "QUESTION_EXPIRED")
            if player_id not in room.players:
                raise HTTPException(401, "INVALID_SESSION")
            if player_id in room.answers:
                raise HTTPException(409, "ALREADY_ANSWERED")
            room.answers[player_id] = Answer(player_id=player_id, question_id=question_id, choice=choice)
            return room

    async def lock_and_score(self, room: Room) -> dict:
        async with room.lock:
            if room.status != GameStatus.QUESTION:
                raise HTTPException(409, "No active question")
            room.status = GameStatus.LOCK
            question = room.current_question
            assert question
            results = STRATEGIES[question.score_strategy].calculate(question, list(room.answers.values()))
            for player_id, score in results.items():
                room.players[player_id].score += score
            counts = {"A": sum(a.choice == "A" for a in room.answers.values()), "B": sum(a.choice == "B" for a in room.answers.values())}
            room.status = GameStatus.SHOW_RESULT
            return {"question_id": question.id, "counts": counts, "scores": results, "leaderboard": self.leaderboard(room)}

    async def next(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status not in {GameStatus.SHOW_RESULT, GameStatus.LOCK}:
                raise HTTPException(409, "Question must be scored first")
            room.current_question_index += 1
            room.answers.clear()
            if room.current_question is None:
                room.status = GameStatus.FINISHED
            else:
                room.status, room.question_started_at = GameStatus.QUESTION, now()
            return room

    def leaderboard(self, room: Room) -> list[dict]:
        return [{"rank": i + 1, "id": p.id, "username": p.username, "score": p.score} for i, p in enumerate(sorted(room.players.values(), key=lambda p: (-p.score, p.answer_time_ms, p.username)))]
