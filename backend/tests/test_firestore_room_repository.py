import os
from threading import Event
from uuid import uuid4

import pytest

from app.models import GameSettings, Question, RoomState
from app.repository.base import RoomConflictError
from app.repository.firestore import FirestoreGameRepository


@pytest.mark.skipif(not os.getenv("FIRESTORE_EMULATOR_HOST"), reason="Firestore emulator is not running")
def test_firestore_room_round_trip_and_compare_and_swap() -> None:
    repository = FirestoreGameRepository(project_id=os.getenv("FIRESTORE_PROJECT_ID", "party-quiz-local"))
    room_id = f"T{uuid4().hex[:7]}".upper()
    initial = RoomState(
        id=room_id,
        questions=[Question(id="q1", title="A or B?", option_a="A", option_b="B")],
        settings=GameSettings(),
    )
    observed_version_two = Event()

    def observe(changed_room_id: str, state: RoomState | None) -> None:
        if changed_room_id == room_id and state and state.version == 2:
            observed_version_two.set()

    watch = repository.watch_rooms(observe)

    try:
        created = repository.save_room(initial, expected_version=None)
        assert created.version == 1
        stale = created.model_copy(deep=True)

        changed = created.model_copy(deep=True)
        changed.owner_id = "owner"
        saved = repository.save_room(changed, expected_version=created.version)

        assert saved.version == 2
        assert repository.get_room(room_id).owner_id == "owner"
        assert room_id in {room.id for room in repository.list_rooms()}
        assert observed_version_two.wait(timeout=5)

        with pytest.raises(RoomConflictError):
            repository.save_room(stale, expected_version=stale.version)
    finally:
        watch.unsubscribe()
        repository.delete_room(room_id)

    assert repository.get_room(room_id) is None
