import asyncio
from types import SimpleNamespace

import pytest
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from loadtest import Player


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
