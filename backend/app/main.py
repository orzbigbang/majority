from __future__ import annotations

import asyncio
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError

from .game import COUNTDOWN_START_CUE_DURATION, GameManager
from .avatar_storage import AvatarStorage
from .models import AnswerPayload, EmojiReactionPayload, GameHistoryAnswer, GameHistoryRecord, GameSettings, GameStatus, IdentityRequest, JoinRequest, LoginRequest, PlayerProfileUpdate, Question, RoomCreateRequest, RoomSettingsUpdate, RoomUpdate, UserProfile, UserProfileUpdate, now
from .repository import FirestoreGameRepository
from .repository.base import GameRepository

manager = GameManager()
repository: GameRepository | None = FirestoreGameRepository() if os.getenv("FIRESTORE_ENABLED", "false").lower() == "true" else None
avatar_storage: AvatarStorage | None = AvatarStorage() if os.getenv("AVATAR_STORAGE_ENABLED", "false").lower() == "true" else None
admin_tokens: set[str] = set()
connections: dict[str, set[WebSocket]] = {}
websocket_players: dict[WebSocket, tuple[str, str]] = {}
volatile_users: dict[str, UserProfile] = {}
volatile_history: dict[str, list[GameHistoryRecord]] = {}
saved_game_runs: set[str] = set()
reaction_history: dict[tuple[str, str], list[float]] = {}


def record_reaction(room_id: str, player_id: str) -> None:
    current_time = time.monotonic()
    key = (room_id, player_id)
    history = [sent_at for sent_at in reaction_history.get(key, []) if current_time - sent_at < 60]
    if history and current_time - history[-1] < 0.8:
        raise HTTPException(429, "REACTION_RATE_LIMITED")
    if sum(current_time - sent_at < 5 for sent_at in history) >= 3 or len(history) >= 12:
        raise HTTPException(429, "REACTION_RATE_LIMITED")
    history.append(current_time)
    reaction_history[key] = history


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


async def broadcast(room_id: str, message_type: str, payload: dict) -> None:
    dead: list[WebSocket] = []
    for ws in connections.get(room_id, set()).copy():
        try: await ws.send_json({"type": message_type, "payload": payload})
        except Exception: dead.append(ws)
    for ws in dead: connections.get(room_id, set()).discard(ws)


def admin(authorization: str | None = Header(default=None)) -> None:
    if not authorization or authorization.removeprefix("Bearer ") not in admin_tokens:
        raise HTTPException(401, "ADMIN_UNAUTHORIZED")


@asynccontextmanager
async def lifespan(_: FastAPI):
    if repository:
        manager.load_persistent_data(repository)
    async def timer() -> None:
        while True:
            await asyncio.sleep(1)
            for room in list(manager.rooms.values()):
                if manager.rooms.get(room.id) is not room:
                    continue
                current_time = now()
                if room.status == GameStatus.COUNTDOWN and room.countdown_started_at and current_time >= room.countdown_started_at + timedelta(seconds=room.settings.countdown_duration + COUNTDOWN_START_CUE_DURATION):
                    await manager.begin_question(room)
                    await broadcast(room.id, "game_state", room.snapshot())
                elif room.status == GameStatus.QUESTION and room.question_started_at and current_time >= room.question_started_at + timedelta(seconds=room.settings.question_duration):
                    result = await manager.lock_and_score(room)
                    await broadcast(room.id, "game_state", room.snapshot())
                    await broadcast(room.id, "result", result)
                elif room.status == GameStatus.SHOW_RESULT and room.result_started_at and current_time >= room.result_started_at + timedelta(seconds=room.settings.result_duration):
                    await manager.next(room.id)
                    save_finished_game(room)
                    await broadcast(room.id, "game_state", room.snapshot())
    task = asyncio.create_task(timer())
    yield
    task.cancel()


app = FastAPI(title="マジョリティ API", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:3000").split(","), allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


@app.get("/health")
def health() -> dict: return {"ok": True}


@app.post("/api/admin/login")
def login(body: LoginRequest) -> dict:
    if not secrets.compare_digest(body.password, os.getenv("ADMIN_PASSWORD", "change-me")): raise HTTPException(401, "ADMIN_UNAUTHORIZED")
    token = secrets.token_urlsafe(32); admin_tokens.add(token)
    return {"token": token}


@app.get("/api/admin/questions")
def questions(_: None = Depends(admin)) -> list[Question]: return manager.questions


@app.post("/api/admin/questions")
def create_question(question: Question, _: None = Depends(admin)) -> Question:
    question.order = len(manager.questions) + 1; manager.questions.append(question)
    if repository: repository.save_questions(manager.questions)
    return question


@app.put("/api/admin/questions/{question_id}")
def update_question(question_id: str, value: Question, _: None = Depends(admin)) -> Question:
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
            "question_count": min(3, available_question_count),
            "question_duration": min(60, max(10, round(manager.settings.question_duration / 10) * 10)),
            "between_question_duration": min(30, max(5, round(manager.settings.result_duration / 5) * 5)),
        },
    }


@app.post("/api/rooms")
async def create_public_room(request: RoomCreateRequest) -> dict:
    settings = manager.settings.model_copy(update={
        "max_players": request.max_players,
        "question_duration": request.question_duration,
        "result_duration": request.between_question_duration,
    })
    room = manager.create_room(settings, request.question_count)
    try:
        profile = ensure_user_profile(request.player_id or str(uuid4()), request.username)
        player = await manager.join(room.id, profile.username, request.session_id, profile.id)
    except Exception:
        manager.rooms.pop(room.id, None)
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
    room = await manager.next(room_id); save_finished_game(room); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/lock")
async def lock(room_id: str, _: None = Depends(admin)) -> dict:
    room = manager.room(room_id); result = await manager.lock_and_score(room); await broadcast(room.id, "game_state", room.snapshot()); await broadcast(room.id, "result", result); return result


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
    save_finished_game(manager.room(room_id))
    room = await manager.reset(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/admin/rooms/{room_id}/end")
async def end(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.end(room_id)
    save_finished_game(room)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/join")
async def join(room_id: str, request: JoinRequest) -> dict:
    manager.room(room_id)
    profile = ensure_user_profile(request.player_id or str(uuid4()), request.username)
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
def room(room_id: str) -> dict: return manager.room(room_id).snapshot()


@app.websocket("/ws/rooms/{room_id}")
async def websocket(ws: WebSocket, room_id: str) -> None:
    await ws.accept()
    try:
        room = manager.room(room_id.upper())
        connected_player_id = ws.query_params.get("player_id")
        connected_session_id = ws.query_params.get("session_id")
        player = room.players.get(connected_player_id or "")
        if not player or not connected_session_id or connected_session_id != player.session_id:
            await ws.close(code=1008)
            return
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
            if message.get("type") in {"answer", "select_answer"}:
                try:
                    payload = AnswerPayload.model_validate(message.get("payload"))
                    changed = await (manager.answer(room.id, connected_player_id, payload.question_id, payload.choice) if message.get("type") == "answer" else manager.select_answer(room.id, connected_player_id, payload.question_id, payload.choice))
                    if message.get("type") == "answer":
                        await ws.send_json({"type": "answer_saved", "payload": {"choice": payload.choice}})
                    await broadcast(room.id, "answer_count", {"answered": len(changed.draft_answers), "total": len(changed.players)})
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
                except ValidationError: await ws.send_json({"type": "error", "payload": {"code": "INVALID_ANSWER", "message": "INVALID_ANSWER"}})
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
                        "event_id": payload.event_id,
                        "reaction_id": payload.reaction_id,
                        "sender_id": sender.id,
                        "sender_username": sender.username,
                        "target_player_id": target.id,
                        "target_username": target.username,
                        "scope_id": expected_scope,
                        "sent_at": now().isoformat(),
                    })
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
                except ValidationError: await ws.send_json({"type": "error", "payload": {"code": "INVALID_REACTION", "message": "INVALID_REACTION"}})
            if message.get("type") == "ready":
                try:
                    requested_ready = (message.get("payload") or {}).get("ready")
                    changed = await manager.mark_ready(room.id, connected_player_id, requested_ready if isinstance(requested_ready, bool) else None)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
            if message.get("type") == "start":
                try:
                    changed = await manager.start(room.id, connected_player_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
            if message.get("type") == "transfer_owner":
                try:
                    new_owner_id = str((message.get("payload") or {}).get("player_id", ""))
                    changed = await manager.transfer_owner(room.id, connected_player_id, new_owner_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
            if message.get("type") == "update_room_settings":
                try:
                    settings = RoomSettingsUpdate.model_validate(message.get("payload"))
                    changed = await manager.update_room_settings(
                        room.id,
                        connected_player_id,
                        settings.max_players,
                        settings.question_count,
                        settings.question_duration,
                        settings.between_question_duration,
                    )
                    await ws.send_json({"type": "room_settings_saved", "payload": {"ok": True}})
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
                except ValidationError: await ws.send_json({"type": "error", "payload": {"code": "INVALID_ROOM_SETTINGS", "message": "INVALID_ROOM_SETTINGS"}})
            if message.get("type") == "return_to_room":
                try:
                    save_finished_game(room)
                    changed = await manager.reset(room.id, connected_player_id)
                    await broadcast(room.id, "game_state", changed.snapshot())
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
    except WebSocketDisconnect: pass
    finally:
        connections.get(room.id, set()).discard(ws)
        binding = websocket_players.pop(ws, None)
        if binding:
            active_for_player = any(current_room == binding[0] and current_player == binding[1] for current_room, current_player in websocket_players.values())
            if not active_for_player:
                try:
                    disconnected_room = manager.room(binding[0])
                    if disconnected_room.status == GameStatus.WAITING:
                        changed = await manager.leave(binding[0], binding[1])
                    else:
                        changed = await manager.set_connected(binding[0], binding[1], False)
                    await broadcast(changed.id, "game_state", changed.snapshot())
                except HTTPException:
                    pass
