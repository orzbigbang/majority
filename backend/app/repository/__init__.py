"""Persistence adapters belong here; the real-time game engine stays storage-independent."""
from .firestore import FirestoreGameRepository

__all__ = ["FirestoreGameRepository"]
