from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .game import GameManager
from .avatar_storage import AvatarStorage
from .models import AnswerPayload, EmojiReactionPayload, GameHistoryAnswer, GameHistoryRecord, GameSettings, GameStatus, IdentityRequest, JoinRequest, LoginRequest, PlayerProfileUpdate, Question, QuestionSelectionPayload, RoomCreateRequest, RoomSettingsUpdate, RoomUpdate, UserProfile, UserProfileUpdate, now
from .repository import FirestoreGameRepository
from .repository.base import GameRepository

manager = GameManager()
repository: GameRepository | None = FirestoreGameRepository() if os.getenv("FIRESTORE_ENABLED", "false").lower() == "true" else None
avatar_storage: AvatarStorage | None = AvatarStorage() if os.getenv("AVATAR_STORAGE_ENABLED", "false").lower() == "true" else None
connections: dict[str, set[WebSocket]] = {}
websocket_players: dict[WebSocket, tuple[str, str]] = {}
websocket_send_locks: dict[WebSocket, asyncio.Lock] = {}
websocket_priority_waiters: dict[WebSocket, int] = {}
volatile_users: dict[str, UserProfile] = {}
volatile_history: dict[str, list[GameHistoryRecord]] = {}
saved_game_runs: set[str] = set()
reaction_history: dict[tuple[str, str], list[float]] = {}
room_reaction_history: dict[str, list[float]] = {}
logger = logging.getLogger(__name__)

WEBSOCKET_SEND_TIMEOUT_SECONDS = 1.5
ROOM_REACTION_LIMIT_PER_SECOND = 20
ADMIN_TOKEN_TTL_SECONDS = int(os.getenv("ADMIN_TOKEN_TTL_SECONDS", "43200"))


def record_reaction(room_id: str, player_id: str) -> None:
    current_time = time.monotonic()
    key = (room_id, player_id)
    history = [sent_at for sent_at in reaction_history.get(key, []) if current_time - sent_at < 60]
    room_history = [sent_at for sent_at in room_reaction_history.get(room_id, []) if current_time - sent_at < 1]
    if history and current_time - history[-1] < 0.8:
        raise HTTPException(429, "REACTION_RATE_LIMITED")
    if sum(current_time - sent_at < 5 for sent_at in history) >= 3 or len(history) >= 12:
        raise HTTPException(429, "REACTION_RATE_LIMITED")
    if len(room_history) >= ROOM_REACTION_LIMIT_PER_SECOND:
        raise HTTPException(429, "ROOM_REACTION_RATE_LIMITED")
    history.append(current_time)
    room_history.append(current_time)
    reaction_history[key] = history
    room_reaction_history[room_id] = room_history


def clear_room_reactions(room_id: str) -> None:
    reaction_history_keys = [key for key in reaction_history if key[0] == room_id]
    for key in reaction_history_keys:
        reaction_history.pop(key, None)
    room_reaction_history.pop(room_id, None)


def get_user(user_id: str) -> UserProfile | None:
    return repository.get_user(user_id) if repository else volatile_users.get(user_id)


def save_user(profile: UserProfile) -> None:
    if repository:
        repository.save_user(profile)
    else:
        volatile_users[profile.id] = profile


def ensure_user_profile(user_id: str, username: str) -> UserProfile:
    timestamp = now()
    profile = get_user(user_id)
    if not profile:
        filename = avatar_storage.ensure_avatar(user_id) if avatar_storage else f"{user_id}.svg"
        profile = UserProfile(id=user_id, username=username.strip(), avatar_filename=filename, created_at=timestamp, last_active_at=timestamp)
    else:
        if avatar_storage:
            filename = avatar_storage.ensure_avatar(user_id)
            if profile.avatar_filename != filename:
                profile.avatar_filename = filename
        profile.username = username.strip()
        profile.created_at = profile.created_at or timestamp
        profile.last_active_at = timestamp
    save_user(profile)
    return profile


def list_history(user_id: str) -> list[GameHistoryRecord]:
    return repository.list_game_history(user_id) if repository else list(volatile_history.get(user_id, []))


def save_finished_game(room) -> None:
    if room.status != GameStatus.FINISHED or not room.game_run_id or room.game_run_id in saved_game_runs:
        return
    leaderboard = manager.leaderboard(room)
    rank_by_player = {entry["id"]: entry for entry in leaderboard}
    for player in room.players.values():
        board_entry = rank_by_player[player.id]
        answers: list[GameHistoryAnswer] = []
        for review in room.history:
            player_answer = next((answer for answer in review["answers"] if answer["player_id"] == player.id), None)
            question = review["question"]
            answers.append(GameHistoryAnswer(
                question_id=question["id"], question=question["title"], option_a=question["option_a"], option_b=question["option_b"],
                choice=player_answer["choice"] if player_answer else None,
                a_count=review["counts"]["A"], b_count=review["counts"]["B"], score=review.get("scores", {}).get(player.id, 0),
            ))
        record = GameHistoryRecord(
            id=room.game_run_id, room_id=room.id, game_name=room.settings.game_name,
            player_count=len(room.players), rank=board_entry["rank"], score=board_entry["score"], answers=answers,
        )
        if repository:
            repository.save_game_history(player.id, record)
        else:
            volatile_history.setdefault(player.id, []).insert(0, record)
    saved_game_runs.add(room.game_run_id)


async def send_message(ws: WebSocket, message_type: str, payload: dict, *, droppable: bool = False) -> bool:
    lock = websocket_send_locks.setdefault(ws, asyncio.Lock())
    if droppable and (lock.locked() or websocket_priority_waiters.get(ws, 0) > 0):
        return True
    if not droppable:
        websocket_priority_waiters[ws] = websocket_priority_waiters.get(ws, 0) + 1

    async def send_in_order() -> None:
        async with lock:
            await ws.send_json({"type": message_type, "payload": payload})

    try:
        await asyncio.wait_for(send_in_order(), timeout=WEBSOCKET_SEND_TIMEOUT_SECONDS)
        return True
    except Exception:
        binding = websocket_players.get(ws)
        if binding:
            connections.get(binding[0], set()).discard(ws)
        return False
    finally:
        if not droppable:
            remaining_waiters = websocket_priority_waiters.get(ws, 1) - 1
            if remaining_waiters > 0:
                websocket_priority_waiters[ws] = remaining_waiters
            else:
                websocket_priority_waiters.pop(ws, None)


async def broadcast(room_id: str, message_type: str, payload: dict) -> None:
    targets = tuple(connections.get(room_id, set()))
    if not targets:
        return
    droppable = message_type == "emoji_reaction"
    await asyncio.gather(*(send_message(ws, message_type, payload, droppable=droppable) for ws in targets))


def _token_part(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _admin_signing_key() -> bytes:
    password = os.getenv("ADMIN_PASSWORD", "change-me").encode("utf-8")
    return hashlib.sha256(b"majority-admin-session\0" + password).digest()


def create_admin_token(ttl_seconds: int = ADMIN_TOKEN_TTL_SECONDS) -> str:
    payload = json.dumps(
        {"v": 1, "exp": int(time.time()) + ttl_seconds, "nonce": secrets.token_urlsafe(12)},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    encoded_payload = _token_part(payload)
    signature = hmac.new(_admin_signing_key(), encoded_payload.encode("ascii"), hashlib.sha256).digest()
    return f"{encoded_payload}.{_token_part(signature)}"


def verify_admin_token(token: str) -> bool:
    try:
        encoded_payload, encoded_signature = token.split(".", 1)
        expected = _token_part(hmac.new(_admin_signing_key(), encoded_payload.encode("ascii"), hashlib.sha256).digest())
        if not hmac.compare_digest(encoded_signature, expected):
            return False
        padding = "=" * (-len(encoded_payload) % 4)
        payload = json.loads(base64.urlsafe_b64decode(encoded_payload + padding))
        return payload.get("v") == 1 and isinstance(payload.get("exp"), int) and payload["exp"] > int(time.time())
    except (ValueError, TypeError, binascii.Error, json.JSONDecodeError):
        return False


def admin(authorization: str | None = Header(default=None)) -> None:
    if not authorization or not verify_admin_token(authorization.removeprefix("Bearer ")):
        raise HTTPException(401, "ADMIN_UNAUTHORIZED")


@asynccontextmanager
async def lifespan(_: FastAPI):
    room_watch = None
    if repository:
        manager.load_persistent_data(repository)
        event_loop = asyncio.get_running_loop()

        async def apply_remote_room(room_id: str, state) -> None:
            had_room = room_id in manager.rooms
            changed = manager.accept_remote_state(room_id, state)
            if changed:
                await broadcast(room_id, "game_state", changed.snapshot())
            elif state is None and had_room:
                await broadcast(room_id, "room_deleted", {"room_id": room_id})

        def on_room_change(room_id: str, state) -> None:
            event_loop.call_soon_threadsafe(asyncio.create_task, apply_remote_room(room_id, state))

        room_watch = repository.watch_rooms(on_room_change)
    async def timer() -> None:
        while True:
            manager.clock_changed.clear()
            current_time = now()
            active_rooms = [(room, deadline) for room in list(manager.rooms.values()) if (deadline := room.clock_deadline()) is not None]
            due_rooms = [room for room, deadline in active_rooms if deadline <= current_time]
            for room in due_rooms:
                try:
                    if room.status == GameStatus.COUNTDOWN:
                        changed = await manager.begin_selection(room)
                        await broadcast(changed.id, "game_state", changed.snapshot())
                    elif room.status in {GameStatus.SELECTING, GameStatus.PARENT_ANSWERING} and room.parent_disconnected_at and (current_parent := room.players.get(room.current_parent_id or "")) and not current_parent.connected:
                        changed = await manager.defer_disconnected_parent(room)
                        await broadcast(changed.id, "game_state", changed.snapshot())
                    elif room.status == GameStatus.SELECTING:
                        changed = await manager.auto_choose_question(room)
                        await broadcast(changed.id, "game_state", changed.snapshot())
                    elif room.status == GameStatus.QUESTION:
                        result = await manager.lock_and_score(room)
                        changed = manager.room(room.id)
                        await broadcast(changed.id, "game_state", changed.snapshot())
                        await broadcast(changed.id, "result", result)
                    elif room.status == GameStatus.SHOW_RESULT:
                        changed = await manager.next(room.id)
                        await asyncio.to_thread(save_finished_game, changed)
                        await broadcast(changed.id, "game_state", changed.snapshot())
                except HTTPException as exc:
                    if exc.status_code != 409:
                        logger.warning("Could not advance room %s: %s", room.id, exc.detail)
                except Exception:
                    logger.exception("Could not advance room %s", room.id)
            if due_rooms:
                continue
            nearest_deadline = min((deadline for _, deadline in active_rooms), default=None)
            wait_seconds = max(0.01, (nearest_deadline - current_time).total_seconds()) if nearest_deadline else 60.0
            try:
                await asyncio.wait_for(manager.clock_changed.wait(), timeout=wait_seconds)
            except TimeoutError:
                pass
    task = asyncio.create_task(timer())
    try:
        yield
    finally:
        task.cancel()
        if room_watch:
            room_watch.unsubscribe()


app = FastAPI(title="マジョリティ API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict: return {"ok": True}


@app.post("/api/admin/login")
def login(body: LoginRequest) -> dict:
    if not secrets.compare_digest(body.password, os.getenv("ADMIN_PASSWORD", "change-me")): raise HTTPException(401, "ADMIN_UNAUTHORIZED")
    return {"token": create_admin_token()}


@app.get("/api/admin/questions")
def questions(_: None = Depends(admin)) -> list[Question]: return manager.questions


@app.post("/api/admin/questions")
def create_question(question: Question, _: None = Depends(admin)) -> Question:
    if "しかし" not in question.title:
        raise HTTPException(422, "QUESTION_REQUIRES_SHIKASHI")
    question.order = len(manager.questions) + 1; manager.questions.append(question)
    if repository: repository.save_questions(manager.questions)
    return question


@app.put("/api/admin/questions/{question_id}")
def update_question(question_id: str, value: Question, _: None = Depends(admin)) -> Question:
    if "しかし" not in value.title:
        raise HTTPException(422, "QUESTION_REQUIRES_SHIKASHI")
    for i, q in enumerate(manager.questions):
        if q.id == question_id:
            manager.questions[i] = value
            if repository: repository.save_questions(manager.questions)
            return value
    raise HTTPException(404, "QUESTION_NOT_FOUND")


@app.delete("/api/admin/questions/{question_id}")
def delete_question(question_id: str, _: None = Depends(admin)) -> None:
    manager.questions = [q for q in manager.questions if q.id != question_id]
    if repository: repository.save_questions(manager.questions)


@app.get("/api/admin/game")
def game_settings(_: None = Depends(admin)) -> GameSettings: return manager.settings


@app.put("/api/admin/game")
def update_settings(settings: GameSettings, _: None = Depends(admin)) -> GameSettings:
    manager.settings = settings
    if repository: repository.save_settings(settings)
    return settings


def user_snapshot(profile: UserProfile) -> dict:
    avatar_version = avatar_storage.style_version if avatar_storage else "v1"
    return {
        "id": profile.id,
        "username": profile.username,
        "avatar_url": f"/api/players/{profile.id}/avatar?v={avatar_version}",
        "bio": profile.bio,
        "favorite_choice": profile.favorite_choice,
        "created_at": profile.created_at.isoformat() if profile.created_at else None,
        "last_active_at": profile.last_active_at.isoformat() if profile.last_active_at else None,
    }


def admin_user_snapshot(profile: UserProfile) -> dict:
    history = list_history(profile.id)
    games = len(history)
    recent_games = sorted(history, key=lambda record: record.finished_at, reverse=True)[:3]
    latest_activity = profile.last_active_at or (recent_games[0].finished_at if recent_games else profile.created_at)
    return {
        **user_snapshot(profile),
        "last_active_at": latest_activity.isoformat() if latest_activity else None,
        "stats": {
            "games": games,
            "wins": sum(record.rank == 1 for record in history),
            "best_rank": min((record.rank for record in history), default=None),
            "average_rank": round(sum(record.rank for record in history) / games, 1) if games else None,
        },
        "recent_games": [record.model_dump(mode="json", exclude={"answers"}) for record in recent_games],
    }


@app.get("/api/admin/users")
def admin_users(_: None = Depends(admin)) -> list[dict]:
    profiles = repository.list_users() if repository else sorted(volatile_users.values(), key=lambda profile: (profile.username.casefold(), profile.id))
    return sorted(
        [admin_user_snapshot(profile) for profile in profiles],
        key=lambda item: item["last_active_at"] or "",
        reverse=True,
    )


@app.put("/api/admin/users/{user_id}")
def update_user(user_id: str, update: UserProfileUpdate, _: None = Depends(admin)) -> dict:
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    profile.username = update.username.strip()
    save_user(profile)
    return admin_user_snapshot(profile)


@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: str, _: None = Depends(admin)) -> dict:
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    if repository:
        repository.delete_user(user_id)
    else:
        volatile_users.pop(user_id, None)
        volatile_history.pop(user_id, None)
    if avatar_storage:
        try:
            avatar_storage.delete_avatar(profile.avatar_filename)
        except Exception:
            pass
    return {"ok": True}


@app.post("/api/admin/rooms")
def create_room(_: None = Depends(admin)) -> dict:
    room = manager.create_room(); return room.snapshot()


@app.get("/api/admin/rooms")
def admin_rooms(_: None = Depends(admin)) -> list[dict]:
    return [room.snapshot() for room in sorted(manager.rooms.values(), key=lambda item: item.id)]


@app.put("/api/admin/rooms/{room_id}")
async def update_room(room_id: str, update: RoomUpdate, _: None = Depends(admin)) -> dict:
    room = await manager.update_room(room_id, update.game_name, update.max_players)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.delete("/api/admin/rooms/{room_id}")
async def delete_room(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.delete_room(room_id)
    await broadcast(room.id, "room_deleted", {"room_id": room.id})
    for websocket in connections.pop(room.id, set()):
        try: await websocket.close(code=1000)
        except Exception: pass
        websocket_send_locks.pop(websocket, None)
        websocket_priority_waiters.pop(websocket, None)
    clear_room_reactions(room.id)
    return {"ok": True}


@app.get("/api/rooms")
def rooms() -> list[dict]:
    return manager.lobby()


@app.get("/api/room-options")
def room_options() -> dict:
    available_question_count = min(30, len(manager.questions))
    return {
        "available_question_count": available_question_count,
        "defaults": {
            "max_players": manager.settings.max_players,
            "round_count": 1,
            "selection_duration": min(60, max(5, round(manager.settings.selection_duration / 5) * 5)),
            "question_duration": min(60, max(10, round(manager.settings.question_duration / 10) * 10)),
            "between_question_duration": min(30, max(5, round(manager.settings.result_duration / 5) * 5)),
        },
    }


@app.post("/api/rooms")
async def create_public_room(request: RoomCreateRequest) -> dict:
    settings = manager.settings.model_copy(update={
        "max_players": request.max_players,
        "selection_duration": request.selection_duration,
        "question_duration": request.question_duration,
        "result_duration": request.between_question_duration,
    })
    room = await asyncio.to_thread(manager.create_room, settings, request.round_count)
    try:
        profile = await asyncio.to_thread(ensure_user_profile, request.player_id or str(uuid4()), request.username)
        player = await manager.join(room.id, profile.username, request.session_id, profile.id)
    except Exception:
        await asyncio.to_thread(manager.discard_room, room.id)
        raise
    return {
        "player_id": player.id,
        "session_id": player.session_id,
        "room": room.snapshot(),
        "draft_choice": None,
        "confirmed_choice": None,
    }


@app.post("/api/players/identity")
def identify_player(request: IdentityRequest) -> dict:
    profile = ensure_user_profile(request.player_id or str(uuid4()), request.username)
    return {"player_id": profile.id, "username": profile.username, "avatar_url": user_snapshot(profile)["avatar_url"]}


@app.get("/api/players/{user_id}")
def player_profile(user_id: str) -> dict:
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    history = list_history(user_id)
    games = len(history)
    questions = sum(len(record.answers) for record in history)
    answered = sum(answer.choice is not None for record in history for answer in record.answers)
    return {
        **user_snapshot(profile),
        "stats": {
            "games": games,
            "wins": sum(record.rank == 1 for record in history),
            "average_rank": round(sum(record.rank for record in history) / games, 1) if games else None,
            "answer_rate": round(answered / questions * 100) if questions else None,
        },
        "history": [record.model_dump(mode="json") for record in history],
    }


@app.put("/api/players/{user_id}")
def update_player_profile(user_id: str, update: PlayerProfileUpdate) -> dict:
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    profile.username = update.username.strip()
    profile.bio = update.bio.strip()
    profile.favorite_choice = update.favorite_choice
    save_user(profile)
    return user_snapshot(profile)


@app.get("/api/players/{user_id}/avatar")
def player_avatar(user_id: str) -> Response:
    profile = get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    if not avatar_storage:
        return Response(AvatarStorage.svg(user_id), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=86400"})
    try:
        avatar_storage.ensure_avatar(user_id)
        return Response(avatar_storage.read_avatar(profile.avatar_filename), media_type="image/svg+xml", headers={"Cache-Control": "public, max-age=31536000, immutable"})
    except Exception as exc:
        raise HTTPException(404, "AVATAR_NOT_FOUND") from exc


@app.post("/api/admin/rooms/{room_id}/start")
async def start(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.start(room_id); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/next")
async def next_question(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.next(room_id); await asyncio.to_thread(save_finished_game, room); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/lock")
async def lock(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.ensure_room(room_id); result = await manager.lock_and_score(room); await broadcast(room.id, "game_state", room.snapshot()); await broadcast(room.id, "result", result); return result


@app.post("/api/admin/rooms/{room_id}/pause")
async def pause(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.pause(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/admin/rooms/{room_id}/resume")
async def resume(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.resume(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/admin/rooms/{room_id}/reset")
async def reset(room_id: str, _: None = Depends(admin)) -> dict:
    existing = await manager.ensure_room(room_id)
    await asyncio.to_thread(save_finished_game, existing)
    room = await manager.reset(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/admin/rooms/{room_id}/end")
async def end(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.end(room_id)
    await asyncio.to_thread(save_finished_game, room)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/join")
async def join(room_id: str, request: JoinRequest) -> dict:
    await manager.ensure_room(room_id)
    profile = await asyncio.to_thread(ensure_user_profile, request.player_id or str(uuid4()), request.username)
    player = await manager.join(room_id, profile.username, request.session_id, profile.id)
    room = manager.room(room_id)
    await broadcast(room.id, "game_state", room.snapshot())
    return {
        "player_id": player.id,
        "session_id": player.session_id,
        "room": room.snapshot(),
        "draft_choice": room.draft_answers.get(player.id).choice if player.id in room.draft_answers else None,
        "confirmed_choice": room.answers.get(player.id).choice if player.id in room.answers else None,
    }


@app.get("/api/rooms/{room_id}")
async def room(room_id: str) -> dict: return (await manager.ensure_room(room_id)).snapshot()


@app.websocket("/ws/rooms/{room_id}")
async def websocket(ws: WebSocket, room_id: str) -> None:
    await ws.accept()
    try:
        room = await manager.ensure_room(room_id.upper())
        connected_player_id = ws.query_params.get("player_id")
        connected_session_id = ws.query_params.get("session_id")
        player = room.players.get(connected_player_id or "")
        if not player or not player.matches_session(connected_session_id):
            await ws.close(code=1008)
            return
        player.session_id = connected_session_id
        room = await manager.set_connected(room.id, connected_player_id, True)
        connections.setdefault(room.id, set()).add(ws)
        websocket_players[ws] = (room.id, connected_player_id)
        await broadcast(room.id, "game_state", room.snapshot())
    except HTTPException:
        await ws.close(code=1008)
        return
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "time_sync":
                client_sent_at = (message.get("payload") or {}).get("client_sent_at")
                client_monotonic = (message.get("payload") or {}).get("client_monotonic")
                if isinstance(client_sent_at, (int, float)):
                    await send_message(ws, "time_sync", {"client_sent_at": client_sent_at, "client_monotonic": client_monotonic, "server_time": now().isoformat()}, droppable=True)
            if message.get("type") in {"answer", "select_answer"}:
                try:
                    payload = AnswerPayload.model_validate(message.get("payload"))
                    parent_was_answering = room.status == GameStatus.PARENT_ANSWERING
                    changed = await (manager.answer(room.id, connected_player_id, payload.question_id, payload.choice) if message.get("type") == "answer" else manager.select_answer(room.id, connected_player_id, payload.question_id, payload.choice))
                    if message.get("type") == "answer":
                        await send_message(ws, "answer_saved", {"choice": payload.choice})
                    if parent_was_answering and message.get("type") == "answer":
                        await broadcast(room.id, "game_state", changed.snapshot())
                    else:
                        await broadcast(room.id, "answer_count", {"answered": len(changed.draft_answers), "total": len(changed.players)})
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
                except ValidationError: await send_message(ws, "error", {"code": "INVALID_ANSWER", "message": "INVALID_ANSWER"})
            if message.get("type") == "select_question":
                try:
                    payload = QuestionSelectionPayload.model_validate(message.get("payload"))
                    changed = await manager.choose_question(room.id, connected_player_id, payload.question_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
                except ValidationError: await send_message(ws, "error", {"code": "QUESTION_NOT_FOUND", "message": "QUESTION_NOT_FOUND"})
            if message.get("type") == "emoji_reaction":
                try:
                    payload = EmojiReactionPayload.model_validate(message.get("payload"))
                    if room.status == GameStatus.WAITING:
                        expected_scope = "waiting"
                    elif room.status == GameStatus.SHOW_RESULT and room.current_question:
                        expected_scope = room.current_question.id
                    else:
                        raise HTTPException(409, "REACTIONS_NOT_AVAILABLE")
                    if payload.scope_id != expected_scope:
                        raise HTTPException(409, "REACTION_SCOPE_EXPIRED")
                    if payload.target_player_id == connected_player_id:
                        raise HTTPException(400, "SELF_REACTION_NOT_ALLOWED")
                    target = room.players.get(payload.target_player_id)
                    sender = room.players.get(connected_player_id)
                    if not target or not target.connected or not sender:
                        raise HTTPException(404, "REACTION_TARGET_UNAVAILABLE")
                    record_reaction(room.id, connected_player_id)
                    await broadcast(room.id, "emoji_reaction", {
                        "event_id": str(uuid4()),
                        "reaction_id": payload.reaction_id,
                        "sender_id": sender.id,
                        "sender_username": sender.username,
                        "target_player_id": target.id,
                        "target_username": target.username,
                        "scope_id": expected_scope,
                        "sent_at": now().isoformat(),
                    })
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
                except ValidationError: await send_message(ws, "error", {"code": "INVALID_REACTION", "message": "INVALID_REACTION"})
            if message.get("type") == "ready":
                try:
                    requested_ready = (message.get("payload") or {}).get("ready")
                    changed = await manager.mark_ready(room.id, connected_player_id, requested_ready if isinstance(requested_ready, bool) else None)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
            if message.get("type") == "start":
                try:
                    changed = await manager.start(room.id, connected_player_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
            if message.get("type") == "transfer_owner":
                try:
                    new_owner_id = str((message.get("payload") or {}).get("player_id", ""))
                    changed = await manager.transfer_owner(room.id, connected_player_id, new_owner_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
            if message.get("type") == "update_room_settings":
                try:
                    settings = RoomSettingsUpdate.model_validate(message.get("payload"))
                    changed = await manager.update_room_settings(
                        room.id,
                        connected_player_id,
                        settings.max_players,
                        settings.round_count,
                        settings.selection_duration,
                        settings.question_duration,
                        settings.between_question_duration,
                    )
                    await send_message(ws, "room_settings_saved", {"ok": True})
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
                except ValidationError: await send_message(ws, "error", {"code": "INVALID_ROOM_SETTINGS", "message": "INVALID_ROOM_SETTINGS"})
            if message.get("type") == "return_to_room":
                try:
                    await asyncio.to_thread(save_finished_game, room)
                    changed = await manager.reset(room.id, connected_player_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await send_message(ws, "error", {"code": str(exc.detail), "message": str(exc.detail)})
    except WebSocketDisconnect: pass
    finally:
        connections.get(room.id, set()).discard(ws)
        websocket_send_locks.pop(ws, None)
        websocket_priority_waiters.pop(ws, None)
        binding = websocket_players.pop(ws, None)
        if binding:
            active_for_player = any(current_room == binding[0] and current_player == binding[1] for current_room, current_player in websocket_players.values())
            if not active_for_player:
                try:
                    disconnected_room = await manager.ensure_room(binding[0])
                    if disconnected_room.status == GameStatus.WAITING:
                        changed = await manager.leave(binding[0], binding[1])
                    else:
                        changed = await manager.set_connected(binding[0], binding[1], False)
                    await broadcast(changed.id, "game_state", changed.snapshot())
                    if changed.id not in manager.rooms:
                        clear_room_reactions(changed.id)
                except HTTPException:
                    clear_room_reactions(binding[0])
                    pass
