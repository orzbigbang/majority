import asyncio
import random
import time
from types import SimpleNamespace

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from loadtest import Player, Run, submission_plan


@pytest.mark.parametrize("planned,transport_error", [(True, True), (False, True), (True, False)])
def test_planned_close_warning_does_not_hide_unexpected_failure(planned, transport_error):
    class Socket:
        def __aiter__(self):
            return self

        async def __anext__(self):
            if transport_error:
                raise ConnectionClosedError(None, Close(1000, ""))
            raise ValueError("invalid message")

    run = SimpleNamespace(errors=[], close_warnings=[])
    player = Player(run, {"player_id": "test"})
    player.ws = Socket()
    player.closing = planned
    asyncio.run(player.receive())
    if planned and transport_error:
        assert len(run.close_warnings) == 1
        assert not run.errors
    else:
        assert run.errors
        assert not run.close_warnings


def test_realistic_plans_have_expected_load_and_repeatable_seed():
    for scenario in ("spread", "deadline", "mixed"):
        plan = submission_plan(11, scenario, random.Random(42), 0)
        assert plan == submission_plan(11, scenario, random.Random(42), 0)
        assert len(plan) == 11
        if scenario == "deadline":
            assert sum(p["cohort"] == "late" for p in plan) == 3
            assert all(9 <= p["offset"] <= 9.15 for p in plan if p["cohort"] == "late")
            assert sum(1 <= p["offset"] <= 8 for p in plan) == 8
        else:
            assert all(1 <= p["offset"] <= 8 for p in plan)
        assert sum(p["change"] for p in plan) == (2 if scenario == "mixed" else 0)
    assert not any(p["change"] for p in submission_plan(11, "mixed", random.Random(42), 1))


def test_scheduler_uses_phase_elapsed_time_and_confirms_changed_choice(monkeypatch):
    plan = [{"offset": .25, "cohort": "spread", "change": True}]
    monkeypatch.setattr("loadtest.submission_plan", lambda *args: plan)

    async def check():
        run = Run(SimpleNamespace(url="http://localhost", seed=42, scenario="mixed"))
        calls = []
        class FakePlayer:
            id = "player"
            state_received_at = time.perf_counter()
            state = {"clock": {"duration_ms": 10000, "remaining_ms": 9750}}
            last_ack_ms = 12

            async def send(self, kind, **payload):
                calls.append((kind, payload["choice"]))

            async def answer(self, question, choice):
                calls.append(("answer", choice))
        await run.scheduled_answers([FakePlayer()], "question", {"player": "A"}, 0, False)
        assert calls == [("select_answer", "B"), ("answer", "A")]
        assert run.draft_changes == 1
        sample, = run.submissions
        assert .25 <= sample["actual_offset_seconds"] < .4
        assert sample["ack_ms"] == 12
    asyncio.run(check())
