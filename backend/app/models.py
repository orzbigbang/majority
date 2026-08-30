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
    PAUSED = "PAUSED"
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
    ready: bool = False
    answer_time_ms: int = 0


class Answer(BaseModel):
    player_id: str
    question_id: str
    choice: Literal["A", "B"]
    answered_at: datetime = Field(default_factory=now)


class JoinRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    session_id: str | None = None
    player_id: str | None = None


class IdentityRequest(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    player_id: str | None = None


class UserProfile(BaseModel):
    id: str
    username: str
    avatar_filename: str
    bio: str = ""
    favorite_choice: Literal["A", "B"] | None = None
    created_at: datetime | None = None
    last_active_at: datetime | None = None


class UserProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=30)


class PlayerProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=30)
    bio: str = Field(default="", max_length=120)
    favorite_choice: Literal["A", "B"] | None = None


class GameHistoryAnswer(BaseModel):
    question_id: str
    question: str
    option_a: str
    option_b: str
    choice: Literal["A", "B"] | None = None
    a_count: int = 0
    b_count: int = 0
    score: int = 0


class GameHistoryRecord(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    room_id: str
    game_name: str
    finished_at: datetime = Field(default_factory=now)
    player_count: int
    rank: int
    score: int
    answers: list[GameHistoryAnswer] = Field(default_factory=list)


class AnswerPayload(BaseModel):
    question_id: str
    choice: Literal["A", "B"]


class EmojiReactionPayload(BaseModel):
    event_id: str = Field(min_length=1, max_length=64)
    reaction_id: Literal["clap", "laugh", "wow", "like", "shy"]
    target_player_id: str = Field(min_length=1, max_length=100)
    scope_id: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    password: str


class AdminSession(BaseModel):
    token: str


class GameSettings(BaseModel):
    game_name: str = "マジョリティ"
    question_duration: int = Field(default=20, ge=5, le=120)
    result_duration: int = Field(default=5, ge=1, le=60)
    countdown_duration: int = Field(default=3, ge=0, le=10)
    max_players: int = Field(default=12, ge=2, le=100)


class RoomCreateRequest(JoinRequest):
    max_players: int = Field(default=12, ge=2, le=100)
    question_count: int = Field(default=3, ge=1, le=30)
    question_duration: int = Field(default=20, ge=10, le=60, multiple_of=10)
    between_question_duration: int = Field(default=5, ge=5, le=30, multiple_of=5)


class RoomSettingsUpdate(BaseModel):
    max_players: int = Field(ge=2, le=100)
    question_count: int = Field(ge=1, le=30)
    question_duration: int = Field(ge=10, le=60, multiple_of=10)
    between_question_duration: int = Field(ge=5, le=30, multiple_of=5)


class RoomUpdate(BaseModel):
    game_name: str | None = Field(default=None, min_length=1, max_length=80)
    max_players: int | None = Field(default=None, ge=2, le=100)
