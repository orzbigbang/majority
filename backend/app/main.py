from __future__ import annotations

import asyncio
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .game import GameManager
from .models import AnswerPayload, GameSettings, JoinRequest, LoginRequest, Question

manager = GameManager()
admin_tokens: set[str] = set()
connections: dict[str, set[WebSocket]] = {}


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
    async def timer() -> None:
        while True:
            await asyncio.sleep(1)
            for room in list(manager.rooms.values()):
                if room.status.value == "QUESTION" and room.question_started_at and (room.question_started_at.timestamp() + room.settings.question_duration) <= __import__("time").time():
                    result = await manager.lock_and_score(room)
                    await broadcast(room.id, "result", result)
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
    question.order = len(manager.questions) + 1; manager.questions.append(question); return question


@app.put("/api/admin/questions/{question_id}")
def update_question(question_id: str, value: Question, _: None = Depends(admin)) -> Question:
    for i, q in enumerate(manager.questions):
        if q.id == question_id: manager.questions[i] = value; return value
    raise HTTPException(404, "QUESTION_NOT_FOUND")


@app.delete("/api/admin/questions/{question_id}")
def delete_question(question_id: str, _: None = Depends(admin)) -> None:
    manager.questions = [q for q in manager.questions if q.id != question_id]


@app.get("/api/admin/game")
def game_settings(_: None = Depends(admin)) -> GameSettings: return manager.settings


@app.put("/api/admin/game")
def update_settings(settings: GameSettings, _: None = Depends(admin)) -> GameSettings: manager.settings = settings; return settings


@app.post("/api/admin/rooms")
def create_room(_: None = Depends(admin)) -> dict:
    room = manager.create_room(); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/start")
async def start(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.start(room_id); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/next")
async def next_question(room_id: str, _: None = Depends(admin)) -> dict:
    room = await manager.next(room_id); await broadcast(room.id, "game_state", room.snapshot()); return room.snapshot()


@app.post("/api/admin/rooms/{room_id}/lock")
async def lock(room_id: str, _: None = Depends(admin)) -> dict:
    room = manager.room(room_id); result = await manager.lock_and_score(room); await broadcast(room.id, "result", result); return result


@app.post("/api/rooms/{room_id}/join")
async def join(room_id: str, request: JoinRequest) -> dict:
    player = await manager.join(room_id, request.username, request.session_id); room = manager.room(room_id); await broadcast(room.id, "game_state", room.snapshot()); return {"player_id": player.id, "session_id": player.session_id, "room": room.snapshot()}


@app.get("/api/rooms/{room_id}")
def room(room_id: str) -> dict: return manager.room(room_id).snapshot()


@app.websocket("/ws/rooms/{room_id}")
async def websocket(ws: WebSocket, room_id: str) -> None:
    await ws.accept(); room = manager.room(room_id.upper()); connections.setdefault(room.id, set()).add(ws)
    await ws.send_json({"type": "game_state", "payload": room.snapshot()})
    try:
        while True:
            message = await ws.receive_json()
            if message.get("type") == "answer":
                try:
                    payload = AnswerPayload.model_validate(message.get("payload")); player_id = message.get("player_id")
                    changed = await manager.answer(room.id, player_id, payload.question_id, payload.choice)
                    await broadcast(room.id, "answer_count", {"answered": len(changed.answers), "total": len(changed.players)})
                except HTTPException as exc: await ws.send_json({"type": "error", "payload": {"code": str(exc.detail), "message": str(exc.detail)}})
    except WebSocketDisconnect: pass
    finally: connections.get(room.id, set()).discard(ws)
