from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal
from uuid import uuid4

from pydantic import AliasChoices, BaseModel, Field


def now() -> datetime:
    return datetime.now(timezone.utc)


class GameStatus(StrEnum):
    WAITING = "WAITING"
    COUNTDOWN = "COUNTDOWN"
    SELECTING = "SELECTING"
    PARENT_ANSWERING = "PARENT_ANSWERING"
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
    session_id: str | None = None
    session_hash: str | None = None
    username: str
    score: int = 0
    connected: bool = True
    ready: bool = False
    answer_time_ms: int = 0

    @staticmethod
    def hash_session(session_id: str) -> str:
        return hashlib.sha256(session_id.encode("utf-8")).hexdigest()

    def matches_session(self, session_id: str | None) -> bool:
        if not session_id:
            return False
        expected = self.session_hash or (self.hash_session(self.session_id) if self.session_id else None)
        return bool(expected and hashlib.sha256(session_id.encode("utf-8")).hexdigest() == expected)


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


class QuestionSelectionPayload(BaseModel):
    question_id: str


class EmojiReactionPayload(BaseModel):
    reaction_id: Literal["clap", "laugh", "wow", "like", "shy"]
    target_player_id: str = Field(min_length=1, max_length=100)
    scope_id: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    password: str


class AdminSession(BaseModel):
    token: str


class GameSettings(BaseModel):
    game_name: str = "マジョリティ"
    selection_duration: int = Field(default=15, ge=5, le=60)
    question_duration: int = Field(default=20, ge=5, le=120)
    result_duration: int = Field(default=5, ge=1, le=60)
    countdown_duration: int = Field(default=3, ge=0, le=10)
    max_players: int = Field(default=12, ge=2, le=100)


class RoomCreateRequest(JoinRequest):
    max_players: int = Field(default=12, ge=2, le=100)
    round_count: int = Field(default=1, ge=1, le=10, validation_alias=AliasChoices("round_count", "question_count"))
    selection_duration: int = Field(default=15, ge=5, le=60, multiple_of=5)
    question_duration: int = Field(default=20, ge=10, le=60, multiple_of=10)
    between_question_duration: int = Field(default=5, ge=5, le=30, multiple_of=5)


class RoomSettingsUpdate(BaseModel):
    max_players: int = Field(ge=2, le=100)
    round_count: int = Field(ge=1, le=10, validation_alias=AliasChoices("round_count", "question_count"))
    selection_duration: int = Field(default=15, ge=5, le=60, multiple_of=5)
    question_duration: int = Field(ge=10, le=60, multiple_of=10)
    between_question_duration: int = Field(ge=5, le=30, multiple_of=5)


class RoomUpdate(BaseModel):
    game_name: str | None = Field(default=None, min_length=1, max_length=80)
    max_players: int | None = Field(default=None, ge=2, le=100)


class RoomState(BaseModel):
    """Serializable, persistent representation of a live game room."""

    id: str
    questions: list[Question]
    settings: GameSettings
    status: GameStatus = GameStatus.WAITING
    players: list[Player] = Field(default_factory=list)
    owner_id: str | None = None
    answers: list[Answer] = Field(default_factory=list)
    draft_answers: list[Answer] = Field(default_factory=list)
    round_count: int = 1
    parent_order: list[str] = Field(default_factory=list)
    parent_turn_order: list[str] = Field(default_factory=list)
    selected_question: Question | None = None
    selection_question_ids: list[str] = Field(default_factory=list)
    used_question_ids: list[str] = Field(default_factory=list)
    selection_started_at: datetime | None = None
    parent_disconnected_at: datetime | None = None
    current_question_index: int = 0
    question_started_at: datetime | None = None
    countdown_started_at: datetime | None = None
    result_started_at: datetime | None = None
    last_result: dict | None = None
    history: list[dict] = Field(default_factory=list)
    previous_game: dict | None = None
    game_run_id: str | None = None
    paused_status: GameStatus | None = None
    paused_remaining_seconds: float | None = None
    clock_version: int = 0
    version: int = 0
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)
