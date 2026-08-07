from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class GameStatus(StrEnum):
    WAITING = "WAITING"
    COUNTDOWN = "COUNTDOWN"
    QUESTION = "QUESTION"
    LOCK = "LOCK"
    SHOW_RESULT = "SHOW_RESULT"
    FINISHED = "FINISHED"


class Question(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    title: str
    option_a: str
    option_b: str
    score_strategy: Literal["majority", "minority", "fixed"] = "majority"
    score_config: dict[str, int | str] = Field(default_factory=lambda: {"winner_score": 1, "loser_score": 0})
    order: int = 0


class Player(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str
    username: str
    score: int = 0
    connected: bool = True
    answer_time_ms: int = 0


class Answer(BaseModel):
    player_id: str
    question_id: str
    choice: Literal["A", "B"]
    answered_at: datetime = Field(default_factory=now)


class JoinRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    session_id: str | None = None


class AnswerPayload(BaseModel):
    question_id: str
    choice: Literal["A", "B"]


class LoginRequest(BaseModel):
    password: str


class AdminSession(BaseModel):
    token: str


class GameSettings(BaseModel):
    game_name: str = "Party Quiz"
    question_duration: int = Field(default=20, ge=5, le=120)
    result_duration: int = Field(default=5, ge=1, le=60)
    countdown_duration: int = Field(default=3, ge=0, le=10)
    max_players: int = Field(default=10, ge=2, le=100)
