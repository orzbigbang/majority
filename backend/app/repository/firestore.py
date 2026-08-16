from __future__ import annotations

import os

from google.cloud import firestore

from ..models import GameSettings, Question, UserProfile


class FirestoreGameRepository:
    """Persistent storage for content and configuration, not live room state."""

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
        self.client.collection("users").document(user_id).delete()
