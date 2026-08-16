from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager
from datetime import timedelta
from uuid import uuid4

from fastapi import Depends, FastAPI, Header, HTTPException, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .game import GameManager
from .avatar_storage import AvatarStorage
from .models import AnswerPayload, GameSettings, GameStatus, IdentityRequest, JoinRequest, LoginRequest, Question, RoomUpdate, UserProfile, UserProfileUpdate, now
from .repository import FirestoreGameRepository
from .repository.base import GameRepository

manager = GameManager()
repository: GameRepository | None = FirestoreGameRepository() if os.getenv("FIRESTORE_ENABLED", "false").lower() == "true" else None
avatar_storage: AvatarStorage | None = AvatarStorage() if os.getenv("AVATAR_STORAGE_ENABLED", "false").lower() == "true" else None
admin_tokens: set[str] = set()
connections: dict[str, set[WebSocket]] = {}
websocket_players: dict[WebSocket, tuple[str, str]] = {}


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
                current_time = now()
                if room.status == GameStatus.COUNTDOWN and room.countdown_started_at and current_time >= room.countdown_started_at + timedelta(seconds=room.settings.countdown_duration):
                    await manager.begin_question(room)
                    await broadcast(room.id, "game_state", room.snapshot())
                elif room.status == GameStatus.QUESTION and room.question_started_at and current_time >= room.question_started_at + timedelta(seconds=room.settings.question_duration):
                    result = await manager.lock_and_score(room)
                    await broadcast(room.id, "game_state", room.snapshot())
                    await broadcast(room.id, "result", result)
                elif room.status == GameStatus.SHOW_RESULT and room.result_started_at and current_time >= room.result_started_at + timedelta(seconds=room.settings.result_duration):
                    await manager.next(room.id)
                    await broadcast(room.id, "game_state", room.snapshot())
    task = asyncio.create_task(timer())
    yield
    task.cancel()


app = FastAPI(title="Party Quiz API", lifespan=lifespan)
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
    }


@app.get("/api/admin/users")
def admin_users(_: None = Depends(admin)) -> list[dict]:
    if not repository:
        return []
    return [user_snapshot(profile) for profile in repository.list_users()]


@app.put("/api/admin/users/{user_id}")
def update_user(user_id: str, update: UserProfileUpdate, _: None = Depends(admin)) -> dict:
    if not repository:
        raise HTTPException(503, "USER_STORAGE_NOT_AVAILABLE")
    profile = repository.get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    profile.username = update.username.strip()
    repository.save_user(profile)
    return user_snapshot(profile)


@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: str, _: None = Depends(admin)) -> dict:
    if not repository:
        raise HTTPException(503, "USER_STORAGE_NOT_AVAILABLE")
    profile = repository.get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
    repository.delete_user(user_id)
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


@app.post("/api/players/identity")
def identify_player(request: IdentityRequest) -> dict:
    user_id = request.player_id or str(uuid4())
    username = request.username.strip()
    profile = repository.get_user(user_id) if repository else None
    if not profile:
        filename = avatar_storage.ensure_avatar(user_id) if avatar_storage else f"{user_id}.svg"
        profile = UserProfile(id=user_id, username=username, avatar_filename=filename)
        if repository:
            repository.save_user(profile)
    else:
        if avatar_storage:
            filename = avatar_storage.ensure_avatar(user_id)
            if profile.avatar_filename != filename:
                profile.avatar_filename = filename
                if repository:
                    repository.save_user(profile)
        if profile.username != username:
            profile.username = username
            if repository:
                repository.save_user(profile)
    return {"player_id": profile.id, "username": profile.username, "avatar_url": user_snapshot(profile)["avatar_url"]}


@app.get("/api/players/{user_id}/avatar")
def player_avatar(user_id: str) -> Response:
    if not repository or not avatar_storage:
        raise HTTPException(404, "AVATAR_NOT_AVAILABLE")
    profile = repository.get_user(user_id)
    if not profile:
        raise HTTPException(404, "USER_NOT_FOUND")
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
    room = await manager.next(room_id); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


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
    room = await manager.reset(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/admin/rooms/{room_id}/end")
async def end(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.end(room_id)
    snapshot = room.snapshot()
    await broadcast(room.id, "game_state", snapshot)
    return snapshot


@app.post("/api/rooms/{room_id}/join")
async def join(room_id: str, request: JoinRequest) -> dict:
    player = await manager.join(room_id, request.username, request.session_id, request.player_id)
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
        player_id = ws.query_params.get("player_id")
        if not player_id or player_id not in room.players:
            await ws.close(code=1008)
            return
        room = await manager.set_connected(room.id, player_id, True)
        connections.setdefault(room.id, set()).add(ws)
        websocket_players[ws] = (room.id, player_id)
        await broadcast(room.id, "game_state", room.snapshot())
    except HTTPException:
        await ws.close(code=1008)
        return
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") in {"answer", "select_answer"}:
                try:
                    payload = AnswerPayload.model_validate(message.get("payload")); player_id = message.get("player_id")
                    changed = await (manager.answer(room.id, player_id, payload.question_id, payload.choice) if message.get("type") == "answer" else manager.select_answer(room.id, player_id, payload.question_id, payload.choice))
                    if message.get("type") == "answer":
                        await ws.send_json({"type": "answer_saved", "payload": {"choice": payload.choice}})
                    await broadcast(room.id, "answer_count", {"answered": len(changed.draft_answers), "total": len(changed.players)})
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
            if message.get("type") == "ready":
                try:
                    changed = await manager.mark_ready(room.id, message.get("player_id"))
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
                    changed = await manager.set_connected(binding[0], binding[1], False)
                    await broadcast(changed.id, "game_state", changed.snapshot())
                except HTTPException:
                    pass
