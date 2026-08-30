from __future__ import annotations

import os
from collections.abc import Callable

from google.cloud import firestore

from ..models import GameHistoryRecord, GameSettings, Question, RoomState, UserProfile
from .base import RoomConflictError


class FirestoreGameRepository:
    """Persistent storage for content, users, history, and live room state."""

    def __init__(self, project_id: str | None = None) -> None:
        self.client = firestore.Client(project=project_id or os.getenv("FIRESTORE_PROJECT_ID"))

    def list_questions(self) -> list[Question]:
        documents = self.client.collection("questions").order_by("order").stream()
        return [Question.model_validate({**(document.to_dict() or {}), "id": document.id}) for document in documents]

    def save_questions(self, questions: list[Question]) -> None:
        collection = self.client.collection("questions")
        batch = self.client.batch()
        for document in collection.stream():
            batch.delete(document.reference)
        for question in questions:
            batch.set(collection.document(question.id), question.model_dump(exclude={"id"}))
        batch.commit()

    def get_settings(self) -> GameSettings | None:
        document = self.client.collection("game_settings").document("default").get()
        return GameSettings.model_validate(document.to_dict()) if document.exists else None

    def save_settings(self, settings: GameSettings) -> None:
        self.client.collection("game_settings").document("default").set(settings.model_dump())

    def get_user(self, user_id: str) -> UserProfile | None:
        document = self.client.collection("users").document(user_id).get()
        if not document.exists:
            return None
        return UserProfile.model_validate({**(document.to_dict() or {}), "id": document.id})

    def save_user(self, profile: UserProfile) -> None:
        self.client.collection("users").document(profile.id).set(profile.model_dump(exclude={"id"}))

    def list_users(self) -> list[UserProfile]:
        documents = self.client.collection("users").stream()
        return sorted(
            [UserProfile.model_validate({**(document.to_dict() or {}), "id": document.id}) for document in documents],
            key=lambda profile: (profile.username.casefold(), profile.id),
        )

    def delete_user(self, user_id: str) -> None:
        document = self.client.collection("users").document(user_id)
        for history in document.collection("game_history").stream():
            history.reference.delete()
        document.delete()

    def save_game_history(self, user_id: str, record: GameHistoryRecord) -> None:
        self.client.collection("users").document(user_id).collection("game_history").document(record.id).set(record.model_dump(exclude={"id"}))

    def list_game_history(self, user_id: str) -> list[GameHistoryRecord]:
        documents = self.client.collection("users").document(user_id).collection("game_history").order_by("finished_at", direction=firestore.Query.DESCENDING).stream()
        return [GameHistoryRecord.model_validate({**(document.to_dict() or {}), "id": document.id}) for document in documents]

    def get_room(self, room_id: str) -> RoomState | None:
        document = self.client.collection("rooms").document(room_id.upper()).get()
        if not document.exists:
            return None
        return RoomState.model_validate({**(document.to_dict() or {}), "id": document.id})

    def list_rooms(self) -> list[RoomState]:
        documents = self.client.collection("rooms").stream()
        rooms = [RoomState.model_validate({**(document.to_dict() or {}), "id": document.id}) for document in documents]
        return sorted(rooms, key=lambda room: room.id)

    def save_room(self, room: RoomState, expected_version: int | None) -> RoomState:
        reference = self.client.collection("rooms").document(room.id)
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            if expected_version is None:
                if snapshot.exists:
                    raise RoomConflictError(f"Room {room.id} already exists")
                next_version = 1
            else:
                if not snapshot.exists:
                    raise RoomConflictError(f"Room {room.id} was deleted")
                stored_version = int((snapshot.to_dict() or {}).get("version", 0))
                if stored_version != expected_version:
                    raise RoomConflictError(f"Room {room.id} changed from version {expected_version} to {stored_version}")
                next_version = stored_version + 1
            saved = room.model_copy(update={"version": next_version})
            current_transaction.set(reference, saved.model_dump(mode="python", exclude={"id"}))
            return saved

        return commit(transaction)

    def delete_room(self, room_id: str, expected_version: int | None = None) -> None:
        reference = self.client.collection("rooms").document(room_id.upper())
        transaction = self.client.transaction()

        @firestore.transactional
        def commit(current_transaction):
            snapshot = reference.get(transaction=current_transaction)
            if not snapshot.exists:
                return
            if expected_version is not None:
                stored_version = int((snapshot.to_dict() or {}).get("version", 0))
                if stored_version != expected_version:
                    raise RoomConflictError(f"Room {room_id} changed from version {expected_version} to {stored_version}")
            current_transaction.delete(reference)

        commit(transaction)

    def watch_rooms(self, callback: Callable[[str, RoomState | None], None]):
        def on_snapshot(_documents, changes, _read_time) -> None:
            for change in changes:
                document = change.document
                if change.type.name == "REMOVED":
                    callback(document.id, None)
                else:
                    callback(document.id, RoomState.model_validate({**(document.to_dict() or {}), "id": document.id}))

        return self.client.collection("rooms").on_snapshot(on_snapshot)
