# /// script
# requires-python = ">=3.13"
# dependencies = ["httpx==0.28.1", "websockets==15.0.1"]
# ///
"""Real HTTP/WebSocket game load test. Never imports the game engine."""
import argparse
import asyncio
import json
import math
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from uuid import uuid4

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed


def stats(values):
    ordered = sorted(values)
    return {"count": len(values), **{
        name: round(ordered[max(0, math.ceil(len(ordered) * q) - 1)], 2) if ordered else None
        for name, q in [("p50_ms", .5), ("p95_ms", .95), ("p99_ms", .99), ("max_ms", 1)]}}


class Player:
    def __init__(self, run, identity):
        self.run, self.identity = run, identity
        self.id = identity["player_id"]
        self.state = {}
        self.ws = self.reader = None
        self.pending = None
        self.closing = False

    async def open(self):
        self.closing = False
        self.state = {}
        query = urlencode({k: self.identity[k] for k in ("player_id", "session_id")})
        self.ws = await connect(f"{self.run.ws_url}/ws/rooms/{self.run.room}?{query}", open_timeout=10)
        self.reader = asyncio.create_task(self.receive())
        await self.run.until(lambda: bool(self.state), "initial snapshot")

    async def receive(self):
        try:
            async for raw in self.ws:
                message = json.loads(raw)
                kind, payload = message["type"], message["payload"]
                if kind == "game_state":
                    self.state = payload
                    key = (payload["clock"]["revision"], payload["status"])
                    self.run.arrivals.setdefault(key, {}).setdefault(self.id, time.perf_counter())
                elif kind == "answer_saved" and self.pending:
                    started, choice, future = self.pending
                    if not future.done():
                        if payload["choice"] != choice:
                            future.set_exception(AssertionError("wrong answer acknowledgement"))
                        else:
                            self.run.latencies.append((time.perf_counter() - started) * 1000)
                            future.set_result(None)
                elif kind == "error":
                    self.run.errors.append({"player": self.id, "error": payload})
        except Exception as exc:
            destination = self.run.close_warnings if self.closing and isinstance(exc, ConnectionClosed) else self.run.errors
            destination.append({"player": self.id, "connection": str(exc)})
        finally:
            if not self.closing:
                self.run.errors.append({"player": self.id, "connection": "unexpected connection end"})

    async def send(self, kind, **payload):
        await self.ws.send(json.dumps({"type": kind, "payload": payload}))

    async def answer(self, question, choice):
        future = asyncio.get_running_loop().create_future()
        self.last_sent = time.perf_counter()
        self.pending = (self.last_sent, choice, future)
        try:
            await self.send("answer", question_id=question, choice=choice)
            await asyncio.wait_for(future, 10)
        finally:
            self.pending = None

    async def close(self):
        self.closing = True
        if self.ws:
            await self.ws.close()
        if self.reader:
            await self.reader


class Run:
    def __init__(self, args):
        self.args = args
        self.ws_url = args.url.rstrip("/").replace("http://", "ws://").replace("https://", "wss://")
        self.players, self.errors, self.latencies, self.reconnect_ms = [], [], [], []
        self.close_warnings = []
        self.arrivals, self.expected = {}, {}
        self.room = None
        self.completed = 0
        self.spreads = []
        self.burst_spans = []

    async def until(self, predicate, label, timeout=30):
        async with asyncio.timeout(timeout):
            while not predicate():
                if self.errors:
                    raise AssertionError(f"{label}: {self.errors[-1]}")
                await asyncio.sleep(.01)

    async def request(self, path, payload):
        response = await self.http.post(path, json=payload)
        response.raise_for_status()
        return response.json()

    async def reconnect(self, players):
        await asyncio.gather(*(p.close() for p in players))
        await asyncio.sleep(.5)
        async def restore(p):
            started = time.perf_counter()
            await p.open()
            assert any(x["id"] == p.id and x["connected"] for x in p.state["players"])
            self.reconnect_ms.append((time.perf_counter() - started) * 1000)
        await asyncio.gather(*(restore(p) for p in players))

    async def game(self):
        identity = lambda i: {"username": f"load-{i}", "player_id": str(uuid4()), "session_id": str(uuid4())}
        first = await self.request("/api/rooms", {**identity(0), "max_players": self.args.players,
            "round_count": 1, "selection_duration": 5, "question_duration": 10, "between_question_duration": 5})
        self.room = first["room"]["room_id"]
        others = await asyncio.gather(*(self.request(f"/api/rooms/{self.room}/join", identity(i))
                                       for i in range(1, self.args.players)))
        self.players = [Player(self, x) for x in [first, *others]]
        overflow = await self.http.post(f"/api/rooms/{self.room}/join", json=identity(99))
        assert overflow.status_code == 409 and "full" in str(overflow.json()).lower(), overflow.text
        await asyncio.gather(*(p.open() for p in self.players))
        await asyncio.gather(*(p.send("ready", ready=True) for p in self.players[1:]))
        owner = self.players[0]
        await self.until(lambda: sum(p["ready"] for p in owner.state["players"]) == self.args.players - 1, "ready")
        await owner.send("start")
        actions = set()
        async with asyncio.timeout(self.args.game_timeout):
            while True:
                if self.errors:
                    raise AssertionError(self.errors[-1])
                state = owner.state
                status, turn = state["status"], state["current_question_index"]
                key = (status, turn)
                if status == "FINISHED":
                    break
                if key not in actions and status in {"SELECTING", "PARENT_ANSWERING", "QUESTION"}:
                    actions.add(key)
                    parent = next(p for p in self.players if p.id == state["current_parent_id"])
                    await self.until(lambda: all(p.state.get("status") == status and
                        p.state.get("current_question_index") == turn for p in self.players), "phase convergence")
                    if status == "SELECTING":
                        if self.args.reconnect and turn == 0:
                            await self.reconnect([parent, *[p for p in self.players if p != parent][:2]])
                        await parent.send("select_question", question_id=state["question_options"][0]["id"])
                    else:
                        qid = state["question"]["id"]
                        choices = self.expected.setdefault(qid, {p.id: ("A" if (i + turn) % 3 else "B")
                                                               for i, p in enumerate(self.players)})
                        targets = [parent] if status == "PARENT_ANSWERING" else [p for p in self.players if p != parent]
                        await asyncio.gather(*(p.answer(qid, choices[p.id]) for p in targets))
                        if status == "QUESTION":
                            self.burst_spans.append((max(p.last_sent for p in targets) - min(p.last_sent for p in targets)) * 1000)
                            # Opposite drafts after confirmation must not alter settlement.
                            await asyncio.gather(*(p.send("select_answer", question_id=qid,
                                choice="B" if choices[p.id] == "A" else "A") for p in targets))
                            if self.args.reconnect and turn == 0:
                                await self.reconnect(targets[:3])
                        print(f"room={self.room} turn={turn + 1} phase={status} acknowledged={len(targets)}", flush=True)
                await asyncio.sleep(.01)
        await self.until(lambda: all(p.state.get("status") == "FINISHED" for p in self.players), "finish")
        review = owner.state["review"]
        assert len(review) == self.args.players == len(self.expected), "missing or duplicated turns"
        assert {item["question"]["id"] for item in review} == set(self.expected), "missing or duplicated questions"
        scores = {p.id: owner.state["rules"]["initial_score"] for p in self.players}
        # Independent oracle for the current default rules, not an engine import.
        rules = owner.state["rules"]
        assert rules["parent_collects_only_when_majority"] and rules["parent_collects_when_minority_has_zero"]
        assert rules["parent_collects_from_minority"] and rules["minority_parent_pays_to_table"]
        assert rules["tie_breaker"] == "parent_choice"
        for item in review:
            choices = self.expected[item["question"]["id"]]
            assert len(item["answers"]) == self.args.players, "missing or duplicated player answers"
            assert {a["player_id"]: a["choice"] for a in item["answers"]} == choices, "confirmed answer lost"
            counts = {c: list(choices.values()).count(c) for c in ("A", "B")}
            parent = item["parent_id"]
            majority = choices[parent] if counts["A"] == counts["B"] else max(counts, key=counts.get)
            delta = {pid: rules["majority_reward"] if c == majority else
                     -min(rules["minority_penalty"], max(0, scores[pid] - rules["score_floor"])) for pid, c in choices.items()}
            if choices[parent] == majority:
                delta[parent] += counts["B" if majority == "A" else "A"] * rules["minority_penalty"]
            assert item["counts"] == counts and item["scores"] == delta and item["majority_choice"] == majority, "scoring mismatch"
            scores = {pid: max(rules["score_floor"], score + delta[pid]) for pid, score in scores.items()}
        for p in self.players:
            assert p.state["review"] == review, "client review mismatch"
            assert {x["id"]: x["score"] for x in p.state["players"]} == scores, "final scores mismatch"
        assert all(len(arrivals) == self.args.players for (_, phase), arrivals in self.arrivals.items()
                   if phase in {"QUESTION", "SHOW_RESULT", "FINISHED"}), "critical phase not delivered to all players"
        self.completed += 1

    async def execute(self):
        started = time.perf_counter()
        started_at = datetime.now(timezone.utc).isoformat()
        failure = None
        try:
            async with httpx.AsyncClient(base_url=self.args.url.rstrip("/"), timeout=20) as self.http:
                for _ in range(self.args.games):
                    self.expected, self.arrivals = {}, {}
                    try:
                        await self.game()
                    finally:
                        await asyncio.gather(*(p.close() for p in self.players), return_exceptions=True)
                    spreads = [(max(x.values()) - min(x.values())) * 1000 for x in self.arrivals.values()
                               if len(x) == self.args.players]
                    self.spreads.extend(spreads)
        except Exception as exc:
            failure = f"{type(exc).__name__}: {exc}"
        server_check = {"checked": False}
        if self.args.container:
            try:
                result = await asyncio.to_thread(subprocess.run,
                    ["docker", "logs", "--since", started_at, self.args.container],
                    capture_output=True, text=True, timeout=20)
                lines = (result.stdout + result.stderr).splitlines()
                signatures = [line for line in lines if line.startswith(("ERROR:", "RuntimeError:", "Traceback"))]
                server_check = {"checked": result.returncode == 0, "error_lines": signatures}
                if result.returncode != 0 or signatures:
                    failure = failure or "Server log check failed"
            except (OSError, subprocess.TimeoutExpired) as exc:
                server_check = {"checked": False, "failure": str(exc)}
                failure = failure or "Cannot inspect server logs"
        metrics = {"answer_ack": stats(self.latencies), "phase_arrival_spread": stats(self.spreads),
                   "reconnect": stats(self.reconnect_ms), "burst_send_span": stats(self.burst_spans)}
        gates = {"ack_p95": metrics["answer_ack"]["p95_ms"] is not None and metrics["answer_ack"]["p95_ms"] <= 500,
                 "ack_p99": metrics["answer_ack"]["p99_ms"] is not None and metrics["answer_ack"]["p99_ms"] <= 1000,
                 "spread_p95": metrics["phase_arrival_spread"]["p95_ms"] is not None and metrics["phase_arrival_spread"]["p95_ms"] <= 300,
                 "burst_within_100ms": bool(self.burst_spans) and max(self.burst_spans) <= 100,
                 "reconnect": not self.args.reconnect or bool(self.reconnect_ms) and max(self.reconnect_ms) <= 5000}
        report = {"passed": not failure and not self.errors and all(gates.values()), "failure": failure,
                  "url": self.args.url, "players": self.args.players, "games_completed": self.completed,
                  "elapsed_seconds": round(time.perf_counter() - started, 2), "last_room": self.room,
                  "started_at": started_at, "server_logs": server_check,
                  "metrics": metrics, "gates": gates, "errors": self.errors,
                  "planned_close_warnings": self.close_warnings,
                  "last_states": {p.id: {"status": p.state.get("status"), "turn": p.state.get("current_question_index")} for p in self.players}}
        self.args.output.parent.mkdir(parents=True, exist_ok=True)
        self.args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(report, indent=2), flush=True)
        return 0 if report["passed"] else 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://localhost:8002")
    parser.add_argument("--players", type=int, choices=range(2, 13), default=12)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--game-timeout", type=float, default=900)
    parser.add_argument("--reconnect", action="store_true")
    parser.add_argument("--container", help="Optional isolated Docker container; fail on server ERROR/traceback logs")
    parser.add_argument("--output", type=Path, default=Path("loadtest-report.json"))
    args = parser.parse_args()
    if args.games < 1 or args.game_timeout <= 0:
        parser.error("games and game-timeout must be positive")
    run = Run(args)
    raise SystemExit(asyncio.run(run.execute()))


if __name__ == "__main__":
    main()
