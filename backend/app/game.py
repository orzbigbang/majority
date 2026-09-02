from __future__ import annotations

import asyncio
import secrets
from copy import deepcopy
from datetime import timedelta
from functools import wraps
from uuid import uuid4

from fastapi import HTTPException

from .models import Answer, GameSettings, GameStatus, Player, Question, RoomState, now
from .question_bank import default_questions
from .repository.base import GameRepository, RoomConflictError
from .rules import MAJORITY_PARTY_RULES, MajorityPartyRules, RoundInput

COUNTDOWN_START_CUE_DURATION = 1
QUESTION_OPTION_COUNT = 3
PARENT_DISCONNECT_GRACE_SECONDS = 8


def retry_room_conflicts(operation):
    """Replay an idempotent room command when another instance wins the CAS."""

    @wraps(operation)
    async def wrapped(self, room_or_id, *args, **kwargs):
        room_id = room_or_id.id if isinstance(room_or_id, Room) else str(room_or_id)
        normalized_id = room_id.upper()
        if normalized_id not in self.rooms and self.repository:
            state = await asyncio.to_thread(self.repository.get_room, normalized_id)
            if state:
                self._cache_state(state)
        for attempt in range(4):
            try:
                return await operation(self, room_or_id, *args, **kwargs)
            except RoomConflictError:
                self.rooms.pop(normalized_id, None)
                if self.repository:
                    state = await asyncio.to_thread(self.repository.get_room, room_id)
                    if state:
                        self._cache_state(state)
                if attempt == 3:
                    raise HTTPException(409, "ROOM_STATE_CHANGED")
        raise HTTPException(409, "ROOM_STATE_CHANGED")

    return wrapped


class Room:
    def __init__(self, room_id: str, questions: list[Question], settings: GameSettings, round_count: int = 1, rule_spec: dict | None = None, title: str | None = None) -> None:
        self.id, self.questions, self.settings = room_id, questions, settings
        self.title = title
        self.round_count = round_count
        self.status = GameStatus.WAITING
        self.players: dict[str, Player] = {}
        self.owner_id: str | None = None
        self.answers: dict[str, Answer] = {}
        self.draft_answers: dict[str, Answer] = {}
        self.parent_order: list[str] = []
        self.parent_turn_order: list[str] = []
        self.selected_question: Question | None = None
        self.selection_question_ids: list[str] = []
        self.used_question_ids: list[str] = []
        self.selection_started_at = None
        self.parent_answer_started_at = None
        self.parent_disconnected_at = None
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
        self.clock_version = 0
        self.version = 0
        self.created_at = now()
        self.updated_at = self.created_at
        self.rule_spec = rule_spec or MAJORITY_PARTY_RULES.spec.as_dict()
        self.lock = asyncio.Lock()

    @classmethod
    def from_state(cls, state: RoomState, rule_spec: dict | None = None) -> Room:
        room = cls(state.id, [question.model_copy(deep=True) for question in state.questions], state.settings.model_copy(deep=True), state.round_count, rule_spec, state.title)
        room.apply_state(state)
        return room

    def apply_state(self, state: RoomState) -> None:
        local_sessions = {player.id: player.session_id for player in self.players.values() if player.session_id}
        self.questions = [question.model_copy(deep=True) for question in state.questions]
        self.title = state.title
        self.settings = state.settings.model_copy(deep=True)
        self.status = state.status
        self.players = {}
        for stored_player in state.players:
            player = stored_player.model_copy(deep=True)
            local_session = local_sessions.get(player.id)
            if local_session and player.matches_session(local_session):
                player.session_id = local_session
            self.players[player.id] = player
        self.owner_id = state.owner_id
        self.answers = {answer.player_id: answer.model_copy(deep=True) for answer in state.answers}
        self.draft_answers = {answer.player_id: answer.model_copy(deep=True) for answer in state.draft_answers}
        self.round_count = state.round_count
        self.parent_order = list(state.parent_order)
        self.parent_turn_order = list(state.parent_turn_order)
        self.selected_question = state.selected_question.model_copy(deep=True) if state.selected_question else None
        self.selection_question_ids = list(state.selection_question_ids)
        self.used_question_ids = list(state.used_question_ids)
        self.selection_started_at = state.selection_started_at
        self.parent_answer_started_at = state.parent_answer_started_at
        self.parent_disconnected_at = state.parent_disconnected_at
        self.current_question_index = state.current_question_index
        self.question_started_at = state.question_started_at
        self.countdown_started_at = state.countdown_started_at
        self.result_started_at = state.result_started_at
        self.last_result = deepcopy(state.last_result)
        self.history = deepcopy(state.history)
        self.previous_game = deepcopy(state.previous_game)
        self.game_run_id = state.game_run_id
        self.paused_status = state.paused_status
        self.paused_remaining_seconds = state.paused_remaining_seconds
        self.clock_version = state.clock_version
        self.version = state.version
        self.created_at = state.created_at
        self.updated_at = state.updated_at

    def to_state(self) -> RoomState:
        return RoomState(
            id=self.id,
            title=self.title,
            questions=[question.model_copy(deep=True) for question in self.questions],
            settings=self.settings.model_copy(deep=True),
            status=self.status,
            players=[
                player.model_copy(
                    deep=True,
                    update={
                        "session_id": None,
                        "session_hash": player.session_hash or (Player.hash_session(player.session_id) if player.session_id else None),
                    },
                )
                for player in self.players.values()
            ],
            owner_id=self.owner_id,
            answers=[answer.model_copy(deep=True) for answer in self.answers.values()],
            draft_answers=[answer.model_copy(deep=True) for answer in self.draft_answers.values()],
            round_count=self.round_count,
            parent_order=list(self.parent_order),
            parent_turn_order=list(self.parent_turn_order),
            selected_question=self.selected_question.model_copy(deep=True) if self.selected_question else None,
            selection_question_ids=list(self.selection_question_ids),
            used_question_ids=list(self.used_question_ids),
            selection_started_at=self.selection_started_at,
            parent_answer_started_at=self.parent_answer_started_at,
            parent_disconnected_at=self.parent_disconnected_at,
            current_question_index=self.current_question_index,
            question_started_at=self.question_started_at,
            countdown_started_at=self.countdown_started_at,
            result_started_at=self.result_started_at,
            last_result=deepcopy(self.last_result),
            history=deepcopy(self.history),
            previous_game=deepcopy(self.previous_game),
            game_run_id=self.game_run_id,
            paused_status=self.paused_status,
            paused_remaining_seconds=self.paused_remaining_seconds,
            clock_version=self.clock_version,
            version=self.version,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )

    @property
    def current_question(self) -> Question | None:
        return self.selected_question

    @property
    def current_parent_id(self) -> str | None:
        if self.parent_turn_order:
            if self.current_question_index >= len(self.parent_turn_order):
                return None
            return self.parent_turn_order[self.current_question_index]
        if not self.parent_order:
            return None
        return self.parent_order[self.current_question_index % len(self.parent_order)]

    @property
    def total_turns(self) -> int:
        return len(self.parent_turn_order) if self.parent_turn_order else self.round_count * len(self.parent_order or self.players)

    def advance_clock_version(self) -> None:
        self.clock_version += 1

    def clock_metadata(self) -> dict:
        """Return the authoritative virtual clock shared by every room client."""
        server_time = now()
        clock_started_at = None
        clock_duration = None
        clock_phase = self.paused_status if self.status == GameStatus.PAUSED and self.paused_status else self.status
        if clock_phase == GameStatus.COUNTDOWN:
            clock_started_at, clock_duration = self.countdown_started_at, self.settings.countdown_duration + COUNTDOWN_START_CUE_DURATION
        elif clock_phase == GameStatus.SELECTING:
            clock_started_at, clock_duration = self.selection_started_at, self.settings.selection_duration
        elif clock_phase == GameStatus.PARENT_ANSWERING:
            clock_started_at, clock_duration = self.parent_answer_started_at, self.settings.question_duration
        elif clock_phase == GameStatus.QUESTION:
            clock_started_at, clock_duration = self.question_started_at, self.settings.question_duration
        elif clock_phase == GameStatus.SHOW_RESULT:
            clock_started_at, clock_duration = self.result_started_at, self.settings.result_duration
        clock_ends_at = clock_started_at + timedelta(seconds=clock_duration) if clock_started_at and clock_duration is not None and self.status != GameStatus.PAUSED else None
        clock_remaining_ms = (
            max(0, int(self.paused_remaining_seconds * 1000))
            if self.status == GameStatus.PAUSED and self.paused_remaining_seconds is not None
            else max(0, int((clock_ends_at - server_time).total_seconds() * 1000)) if clock_ends_at else 0
        )
        return {
            "revision": self.clock_version,
            "phase": clock_phase,
            "server_time": server_time.isoformat(),
            "running": clock_ends_at is not None and self.status != GameStatus.PAUSED,
            "started_at": clock_started_at.isoformat() if clock_started_at else None,
            "ends_at": clock_ends_at.isoformat() if clock_ends_at else None,
            "duration_ms": int(clock_duration * 1000) if clock_duration is not None else None,
            "remaining_ms": clock_remaining_ms,
        }

    def clock_deadline(self):
        deadlines = []
        current_parent = self.players.get(self.current_parent_id or "")
        if self.status == GameStatus.COUNTDOWN and self.countdown_started_at:
            deadlines.append(self.countdown_started_at + timedelta(seconds=self.settings.countdown_duration + COUNTDOWN_START_CUE_DURATION))
        if self.status == GameStatus.SELECTING and self.selection_started_at and (not current_parent or current_parent.connected):
            deadlines.append(self.selection_started_at + timedelta(seconds=self.settings.selection_duration))
        if self.status == GameStatus.PARENT_ANSWERING and self.parent_answer_started_at and (not current_parent or current_parent.connected):
            deadlines.append(self.parent_answer_started_at + timedelta(seconds=self.settings.question_duration))
        if self.status in {GameStatus.SELECTING, GameStatus.PARENT_ANSWERING} and self.parent_disconnected_at:
            deadlines.append(self.parent_disconnected_at + timedelta(seconds=PARENT_DISCONNECT_GRACE_SECONDS))
        if self.status == GameStatus.QUESTION and self.question_started_at:
            deadlines.append(self.question_started_at + timedelta(seconds=self.settings.question_duration))
        if self.status == GameStatus.SHOW_RESULT and self.result_started_at:
            deadlines.append(self.result_started_at + timedelta(seconds=self.settings.result_duration))
        return min(deadlines) if deadlines else None

    def snapshot(self, include_question: bool = True) -> dict:
        question = self.current_question
        current_parent_id = self.current_parent_id
        current_round = min(self.round_count, self.parent_turn_order[:self.current_question_index + 1].count(current_parent_id)) if current_parent_id and self.parent_turn_order else (min(self.round_count, self.current_question_index // len(self.parent_order) + 1) if self.parent_order else 1)
        payload = {"room_id": self.id, "title": self.title, "status": self.status, "owner_id": self.owner_id, "players": [{"id": p.id, "username": p.username, "score": p.score, "connected": p.connected, "ready": p.ready} for p in self.players.values()], "current_question_index": self.current_question_index, "question_count": self.total_turns, "round_count": self.round_count, "current_round": current_round, "current_parent_id": self.current_parent_id, "answered": len(self.draft_answers), "settings": self.settings.model_dump(), "rules": self.rule_spec, "previous_game": self.previous_game, "clock": self.clock_metadata()}
        if self.status == GameStatus.COUNTDOWN:
            payload.update({"phase_started_at": self.countdown_started_at.isoformat() if self.countdown_started_at else None, "phase_duration": self.settings.countdown_duration})
        if self.status == GameStatus.SELECTING:
            questions_by_id = {item.id: item for item in self.questions}
            payload["question_options"] = [{"id": questions_by_id[item_id].id, "title": questions_by_id[item_id].title} for item_id in self.selection_question_ids if item_id in questions_by_id]
            payload.update({"phase_started_at": self.selection_started_at.isoformat() if self.selection_started_at else None, "phase_duration": self.settings.selection_duration})
        if self.status == GameStatus.PARENT_ANSWERING:
            payload.update({"phase_started_at": self.parent_answer_started_at.isoformat() if self.parent_answer_started_at else None, "phase_duration": self.settings.question_duration})
        if include_question and question and (self.status in {GameStatus.PARENT_ANSWERING, GameStatus.QUESTION} or (self.status == GameStatus.PAUSED and self.paused_status == GameStatus.QUESTION)):
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
    def __init__(self, repository: GameRepository | None = None, rules: MajorityPartyRules | None = None) -> None:
        self.rooms: dict[str, Room] = {}
        self.repository = repository
        self.rules = rules or MAJORITY_PARTY_RULES
        self.clock_changed = asyncio.Event()
        self.questions: list[Question] = default_questions()
        self.settings = GameSettings()

    def _advance_clock(self, room: Room) -> None:
        room.advance_clock_version()
        self.clock_changed.set()

    def _prepare_selection(self, room: Room) -> None:
        available = [question for question in room.questions if question.id not in room.used_question_ids]
        if not available:
            room.used_question_ids.clear()
            available = list(room.questions)
        candidates = list(available)
        selected_ids: list[str] = []
        while candidates and len(selected_ids) < QUESTION_OPTION_COUNT:
            question = secrets.choice(candidates)
            selected_ids.append(question.id)
            candidates.remove(question)
        room.status = GameStatus.SELECTING
        room.selected_question = None
        room.selection_question_ids = selected_ids
        room.selection_started_at = now()
        current_parent = room.players.get(room.current_parent_id or "")
        room.parent_disconnected_at = now() if current_parent and not current_parent.connected else None
        self._advance_clock(room)

    @staticmethod
    def _select_question(room: Room, question_id: str) -> None:
        question = next((item for item in room.questions if item.id == question_id), None)
        if not question or question_id not in room.selection_question_ids:
            raise HTTPException(404, "QUESTION_NOT_FOUND")
        room.selected_question = question.model_copy(deep=True)
        if question_id not in room.used_question_ids:
            room.used_question_ids.append(question_id)
        room.selection_question_ids.clear()
        room.selection_started_at = None
        room.parent_answer_started_at = now()
        room.parent_disconnected_at = None
        room.answers.clear()
        room.draft_answers.clear()
        room.last_result = None
        room.question_started_at = None
        room.status = GameStatus.PARENT_ANSWERING

    def load_persistent_data(self, repository: GameRepository) -> None:
        self.repository = repository
        questions = repository.list_questions()
        if questions:
            self.questions = questions
            old_button_questions = {
                "毎朝、好きな時間まで眠れる。でも、毎晩必ず怖い夢を見る。",
                "一生、どんな料理も無料で食べられる。でも、同じ料理は二度と食べられない。",
                "大切な人の願いが一つ叶う。でも、自分の秘密が一つみんなに知られる。",
            }
            legacy_defaults = {
                ("q1", "你更喜欢猫还是狗？", "猫", "狗"): ("毎朝、好きな時間まで眠れる。でも、毎晩必ず怖い夢を見る。", "押す", "押さない"),
                ("q2", "早起还是熬夜？", "早起", "熬夜"): ("一生、どんな料理も無料で食べられる。でも、同じ料理は二度と食べられない。", "押す", "押さない"),
                ("q3", "海边还是山里？", "海边", "山里"): ("大切な人の願いが一つ叶う。でも、自分の秘密が一つみんなに知られる。", "押す", "押さない"),
                ("q1", "猫と犬、どっちが好き？", "猫", "犬"): ("毎朝、好きな時間まで眠れる。でも、毎晩必ず怖い夢を見る。", "押す", "押さない"),
                ("q2", "朝型と夜型、どっち？", "朝型", "夜型"): ("一生、どんな料理も無料で食べられる。でも、同じ料理は二度と食べられない。", "押す", "押さない"),
                ("q3", "海と山、どっちへ行きたい？", "海", "山"): ("大切な人の願いが一つ叶う。でも、自分の秘密が一つみんなに知られる。", "押す", "押さない"),
            }
            migrated = False
            for question in self.questions:
                translated = legacy_defaults.get((question.id, question.title, question.option_a, question.option_b))
                if translated:
                    question.title, question.option_a, question.option_b = translated
                    migrated = True
            if migrated:
                repository.save_questions(self.questions)
            if len(self.questions) == 3 and {question.title for question in self.questions} == old_button_questions:
                self.questions = default_questions()
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
        for state in repository.list_rooms():
            self.rooms[state.id] = Room.from_state(state, self.rules.spec.as_dict())

    def _cache_state(self, state: RoomState) -> Room:
        room = self.rooms.get(state.id)
        if room:
            room.apply_state(state)
        else:
            room = Room.from_state(state, self.rules.spec.as_dict())
            self.rooms[state.id] = room
        return room

    def _persist_room(self, room: Room, *, create: bool = False) -> Room:
        room.updated_at = now()
        if not self.repository:
            return room
        expected_version = None if create else room.version
        saved = self.repository.save_room(room.to_state(), expected_version)
        room.apply_state(saved)
        return room

    async def _persist_room_async(self, room: Room) -> Room:
        room.updated_at = now()
        if not self.repository:
            return room
        state = room.to_state()
        saved = await asyncio.to_thread(self.repository.save_room, state, room.version)
        # A watch callback can apply a newer version while this write is in flight.
        if room.version <= saved.version:
            room.apply_state(saved)
        return room

    async def _delete_room_async(self, room: Room) -> None:
        if self.repository:
            await asyncio.to_thread(self.repository.delete_room, room.id, room.version)

    def discard_room(self, room_id: str) -> None:
        room = self.rooms.pop(room_id.upper(), None)
        if self.repository:
            self.repository.delete_room(room_id, room.version if room else None)

    def accept_remote_state(self, room_id: str, state: RoomState | None) -> Room | None:
        """Apply a newer Firestore watch event, ignoring our own echoed writes."""
        normalized_id = room_id.upper()
        cached = self.rooms.get(normalized_id)
        if state is None:
            self.rooms.pop(normalized_id, None)
            return None if cached else cached
        if cached and state.version <= cached.version:
            return None
        previous_clock_version = cached.clock_version if cached else None
        changed = self._cache_state(state)
        if previous_clock_version is None or changed.clock_version != previous_clock_version:
            self.clock_changed.set()
        return changed

    def create_room(self, settings: GameSettings | None = None, round_count: int | None = None, title: str | None = None) -> Room:
        if not self.questions:
            raise HTTPException(400, "Add at least one question first")
        ordered_questions = sorted([q.model_copy() for q in self.questions], key=lambda q: q.order)
        room_settings = (settings or self.settings).model_copy()
        room_round_count = round_count if round_count is not None else room_settings.default_round_count
        alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
        for _ in range(20):
            room_id = "".join(secrets.choice(alphabet) for _ in range(4))
            if room_id in self.rooms or (self.repository and self.repository.get_room(room_id)):
                continue
            room = Room(room_id, ordered_questions, room_settings, room_round_count, self.rules.spec.as_dict(), title)
            self.rooms[room_id] = room
            try:
                return self._persist_room(room, create=True)
            except RoomConflictError:
                self.rooms.pop(room_id, None)
        raise HTTPException(503, "ROOM_ID_ALLOCATION_FAILED")

    def room(self, room_id: str) -> Room:
        normalized_id = room_id.upper()
        room = self.rooms.get(normalized_id)
        if not room:
            raise HTTPException(404, "ROOM_NOT_FOUND")
        return room

    async def ensure_room(self, room_id: str) -> Room:
        normalized_id = room_id.upper()
        room = self.rooms.get(normalized_id)
        if room:
            return room
        if self.repository:
            state = await asyncio.to_thread(self.repository.get_room, normalized_id)
            if state:
                return self._cache_state(state)
        raise HTTPException(404, "ROOM_NOT_FOUND")

    @retry_room_conflicts
    async def join(self, room_id: str, username: str, session_id: str | None, player_id: str | None = None) -> Player:
        room = self.room(room_id)
        async with room.lock:
            if player_id and player_id in room.players:
                existing = room.players[player_id]
                if not existing.matches_session(session_id):
                    raise HTTPException(401, "INVALID_SESSION")
                existing.session_id = session_id
                existing.username = username.strip()
                await self._persist_room_async(room)
                return existing
            if session_id:
                existing = next((p for p in room.players.values() if p.matches_session(session_id)), None)
                if existing:
                    existing.session_id = session_id
                    return existing
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "GAME_ALREADY_STARTED")
            if len(room.players) >= room.settings.max_players:
                raise HTTPException(409, "ROOM_FULL")
            raw_session = session_id or str(uuid4())
            player = Player(id=player_id or str(uuid4()), session_id=raw_session, session_hash=Player.hash_session(raw_session), username=username.strip())
            room.players[player.id] = player
            if room.owner_id is None:
                room.owner_id = player.id
            await self._persist_room_async(room)
            return player

    def lobby(self) -> list[dict]:
        return [
            {
                "room_id": room.id,
                "title": room.title,
                "status": room.status,
                "player_count": len(room.players),
                "max_players": room.settings.max_players,
                "game_name": room.settings.game_name,
            }
            for room in sorted(self.rooms.values(), key=lambda item: item.id)
        ]

    @retry_room_conflicts
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
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def update_room_settings(
        self,
        room_id: str,
        requested_by: str,
        max_players: int,
        round_count: int,
        selection_duration: int,
        question_duration: int,
        between_question_duration: int,
        title: str | None = None,
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
            room.questions = ordered_questions
            room.title = title
            room.round_count = round_count
            room.settings.max_players = max_players
            room.settings.selection_duration = selection_duration
            room.settings.question_duration = question_duration
            room.settings.result_duration = between_question_duration
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def delete_room(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.WAITING:
                raise HTTPException(409, "Only waiting rooms can be deleted")
            await self._delete_room_async(room)
            del self.rooms[room.id]
            return room

    @retry_room_conflicts
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
            room.parent_order = list(room.players)
            room.parent_turn_order = [player_id for _ in range(room.round_count) for player_id in room.parent_order]
            room.selected_question = None
            room.selection_question_ids.clear()
            room.used_question_ids.clear()
            room.selection_started_at = None
            room.parent_disconnected_at = None
            room.current_question_index = 0
            room.answers.clear()
            room.draft_answers.clear()
            room.last_result = None
            room.history.clear()
            starting_scores = self.rules.starting_scores(list(room.players))
            for player in room.players.values():
                player.score = starting_scores[player.id]
                player.answer_time_ms = 0
            if room.settings.countdown_duration:
                room.status, room.countdown_started_at = GameStatus.COUNTDOWN, now()
                self._advance_clock(room)
            else:
                self._prepare_selection(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
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
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
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
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def set_connected(self, room_id: str, player_id: str, connected: bool) -> Room:
        room = self.room(room_id)
        async with room.lock:
            player = room.players.get(player_id)
            if not player:
                raise HTTPException(401, "INVALID_SESSION")
            player.connected = connected
            if room.status in {GameStatus.SELECTING, GameStatus.PARENT_ANSWERING}:
                current_parent = room.players.get(room.current_parent_id or "")
                if player_id == room.current_parent_id:
                    if connected:
                        room.parent_disconnected_at = None
                        if room.status == GameStatus.SELECTING:
                            room.selection_started_at = now()
                    else:
                        room.parent_disconnected_at = now()
                    self._advance_clock(room)
                elif connected and current_parent and not current_parent.connected and room.parent_disconnected_at is None:
                    room.parent_disconnected_at = now()
                    self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def leave(self, room_id: str, player_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            # Socket cleanup can race when the same player has multiple connections.
            if room.players.pop(player_id, None) is None:
                return room
            room.parent_order = [item for item in room.parent_order if item != player_id]
            room.parent_turn_order = [item for item in room.parent_turn_order if item != player_id]
            room.answers.pop(player_id, None)
            room.draft_answers.pop(player_id, None)
            if room.last_result:
                room.last_result.get("scores", {}).pop(player_id, None)
                room.last_result["leaderboard"] = self.leaderboard(room)
            if not room.players:
                room.owner_id = None
                self.rooms.pop(room.id, None)
                await self._delete_room_async(room)
            elif player_id == room.owner_id:
                room.owner_id = next(iter(room.players))
                room.players[room.owner_id].ready = False
                await self._persist_room_async(room)
            else:
                await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def begin_selection(self, room: Room) -> Room:
        room = self.room(room.id)
        async with room.lock:
            if room.status != GameStatus.COUNTDOWN:
                raise HTTPException(409, "Countdown is not active")
            room.status = GameStatus.SELECTING
            room.countdown_started_at = None
            self._prepare_selection(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def choose_question(self, room_id: str, player_id: str, question_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status != GameStatus.SELECTING:
                raise HTTPException(409, "QUESTION_SELECTION_NOT_ACTIVE")
            if player_id != room.current_parent_id:
                raise HTTPException(403, "PARENT_ONLY")
            if room.selection_started_at and now() >= room.selection_started_at + timedelta(seconds=room.settings.selection_duration):
                raise HTTPException(409, "QUESTION_SELECTION_EXPIRED")
            self._select_question(room, question_id)
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def auto_choose_question(self, room: Room) -> Room:
        room = self.room(room.id)
        async with room.lock:
            if room.status != GameStatus.SELECTING or not room.selection_question_ids:
                raise HTTPException(409, "QUESTION_SELECTION_NOT_ACTIVE")
            self._select_question(room, secrets.choice(room.selection_question_ids))
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def defer_disconnected_parent(self, room: Room) -> Room:
        room = self.room(room.id)
        async with room.lock:
            if room.status not in {GameStatus.SELECTING, GameStatus.PARENT_ANSWERING}:
                raise HTTPException(409, "PARENT_NOT_SELECTING")
            current_parent = room.players.get(room.current_parent_id or "")
            if not current_parent or current_parent.connected or not room.parent_disconnected_at:
                raise HTTPException(409, "PARENT_NOT_DISCONNECTED")
            if now() < room.parent_disconnected_at + timedelta(seconds=PARENT_DISCONNECT_GRACE_SECONDS):
                raise HTTPException(409, "PARENT_RECONNECT_GRACE_ACTIVE")
            remaining = room.parent_turn_order[room.current_question_index:]
            next_online_offset = next((index for index, player_id in enumerate(remaining[1:], start=1) if room.players.get(player_id) and room.players[player_id].connected), None)
            if next_online_offset is None:
                room.parent_disconnected_at = None
                room.selection_started_at = None
                self._advance_clock(room)
                await self._persist_room_async(room)
                return room
            deferred = remaining[:next_online_offset]
            room.parent_turn_order = room.parent_turn_order[:room.current_question_index] + remaining[next_online_offset:] + deferred
            if room.selected_question and room.selected_question.id in room.used_question_ids:
                room.used_question_ids.remove(room.selected_question.id)
            room.answers.clear()
            room.draft_answers.clear()
            room.last_result = None
            room.question_started_at = None
            room.parent_answer_started_at = None
            self._prepare_selection(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
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
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
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
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
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
            room.parent_order.clear()
            room.parent_turn_order.clear()
            room.selected_question = None
            room.selection_question_ids.clear()
            room.used_question_ids.clear()
            room.selection_started_at = None
            room.parent_disconnected_at = None
            room.answers.clear()
            room.draft_answers.clear()
            room.question_started_at = None
            room.parent_answer_started_at = None
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
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def end(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status in {GameStatus.WAITING, GameStatus.FINISHED}:
                raise HTTPException(409, "GAME_NOT_RUNNING")
            room.status = GameStatus.FINISHED
            room.paused_status = None
            room.paused_remaining_seconds = None
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def select_answer(self, room_id: str, player_id: str, question_id: str, choice: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            answer = self._validated_answer(room, player_id, question_id, choice)
            room.draft_answers[player_id] = answer
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def answer(self, room_id: str, player_id: str, question_id: str, choice: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            answer = self._validated_answer(room, player_id, question_id, choice)
            room.draft_answers[player_id] = answer
            room.answers[player_id] = answer
            if room.status == GameStatus.PARENT_ANSWERING:
                room.status = GameStatus.QUESTION
                room.parent_answer_started_at = None
                room.question_started_at = now()
                self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @staticmethod
    def _validated_answer(room: Room, player_id: str, question_id: str, choice: str) -> Answer:
        if room.status not in {GameStatus.PARENT_ANSWERING, GameStatus.QUESTION} or not room.current_question or room.current_question.id != question_id:
            raise HTTPException(409, "INVALID_ANSWER")
        if room.status == GameStatus.PARENT_ANSWERING and player_id != room.current_parent_id:
            raise HTTPException(403, "PARENT_ANSWERS_FIRST")
        if room.status == GameStatus.PARENT_ANSWERING and room.parent_answer_started_at and now() >= room.parent_answer_started_at + timedelta(seconds=room.settings.question_duration):
            raise HTTPException(409, "PARENT_ANSWER_EXPIRED")
        if room.status == GameStatus.QUESTION and player_id == room.current_parent_id and player_id in room.answers:
            raise HTTPException(409, "PARENT_ANSWER_LOCKED")
        if room.question_started_at and now() > room.question_started_at + timedelta(seconds=room.settings.question_duration):
            raise HTTPException(409, "QUESTION_EXPIRED")
        if player_id not in room.players:
            raise HTTPException(401, "INVALID_SESSION")
        return Answer(player_id=player_id, question_id=question_id, choice=choice)

    @retry_room_conflicts
    async def auto_answer_parent(self, room: Room) -> Room:
        room = self.room(room.id)
        async with room.lock:
            if room.status != GameStatus.PARENT_ANSWERING or not room.current_question or not room.current_parent_id:
                raise HTTPException(409, "PARENT_ANSWER_NOT_ACTIVE")
            parent_id = room.current_parent_id
            answer = room.draft_answers.get(parent_id) or Answer(
                player_id=parent_id,
                question_id=room.current_question.id,
                choice=secrets.choice(("A", "B")),
            )
            room.draft_answers[parent_id] = answer
            room.answers[parent_id] = answer
            room.status = GameStatus.QUESTION
            room.parent_answer_started_at = None
            room.question_started_at = now()
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room

    @retry_room_conflicts
    async def lock_and_score(self, room: Room) -> dict:
        room = self.room(room.id)
        async with room.lock:
            if room.status != GameStatus.QUESTION:
                raise HTTPException(409, "No active question")
            room.status = GameStatus.LOCK
            question = room.current_question
            assert question
            room.answers = {**room.answers, **room.draft_answers}
            parent_id = room.current_parent_id
            assert parent_id
            resolution = self.rules.settle_round(RoundInput(
                player_ids=tuple(room.players),
                parent_id=parent_id,
                choices={player_id: answer.choice for player_id, answer in room.answers.items()},
                scores={player.id: player.score for player in room.players.values()},
            ))
            counts = resolution.counts
            majority_choice = resolution.majority_choice
            results = resolution.score_changes
            question_started_at = room.question_started_at or now()
            for player in room.players.values():
                answer = room.answers.get(player.id)
                elapsed_ms = int((answer.answered_at - question_started_at).total_seconds() * 1000) if answer else room.settings.question_duration * 1000
                player.answer_time_ms += max(0, elapsed_ms)
            for player_id, score in resolution.scores_after.items():
                room.players[player_id].score = score
            review = {
                "question": {"id": question.id, "title": question.title, "option_a": question.option_a, "option_b": question.option_b},
                "counts": counts,
                "answers": [{"player_id": player.id, "username": player.username, "choice": room.answers.get(player.id).choice if player.id in room.answers else None} for player in room.players.values()],
                "scores": results,
                "parent_id": parent_id,
                "majority_choice": majority_choice,
            }
            room.history.append(review)
            room.status = GameStatus.SHOW_RESULT
            room.result_started_at = now()
            room.last_result = {"question_id": question.id, "question": review["question"], "counts": counts, "answers": review["answers"], "scores": results, "parent_id": parent_id, "majority_choice": majority_choice, "leaderboard": self.leaderboard(room)}
            self._advance_clock(room)
            await self._persist_room_async(room)
            return room.last_result

    @retry_room_conflicts
    async def next(self, room_id: str) -> Room:
        room = self.room(room_id)
        async with room.lock:
            if room.status not in {GameStatus.SHOW_RESULT, GameStatus.LOCK}:
                raise HTTPException(409, "Question must be scored first")
            room.current_question_index += 1
            room.answers.clear()
            room.draft_answers.clear()
            room.selected_question = None
            room.last_result = None
            room.result_started_at = None
            room.question_started_at = None
            if room.current_question_index >= room.total_turns:
                room.status = GameStatus.FINISHED
                room.selection_question_ids.clear()
                room.selection_started_at = None
                room.parent_disconnected_at = None
                self._advance_clock(room)
            else:
                self._prepare_selection(room)
            await self._persist_room_async(room)
            return room

    def leaderboard(self, room: Room) -> list[dict]:
        return [{"rank": i + 1, "id": p.id, "username": p.username, "score": p.score} for i, p in enumerate(sorted(room.players.values(), key=lambda p: (-p.score, p.answer_time_ms, p.username)))]
