from __future__ import annotations

import os

from google.cloud import storage

from .cute_animal_svg import render_cute_animal_svg


class AvatarStorage:
    """Stores deterministic cute-animal avatar SVG files in Cloud Storage."""

    def __init__(self) -> None:
        self.bucket_name = os.getenv("AVATAR_BUCKET", "majority-main")
        self.client = storage.Client(project=os.getenv("FIRESTORE_PROJECT_ID"))

    @staticmethod
    def filename(user_id: str) -> str:
        prefix = os.getenv("AVATAR_OBJECT_PREFIX", "user-thumbnail").strip("/")
        return f"{prefix}/{user_id}.svg" if prefix else f"{user_id}.svg"

    @property
    def style_version(self) -> str:
        return os.getenv("AVATAR_STYLE_VERSION", "cute-animal-v1")

    @staticmethod
    def svg(user_id: str) -> str:
        """Create a recognisable, stable animal from an opaque user UUID."""
        return render_cute_animal_svg(user_id)

    def ensure_avatar(self, user_id: str) -> str:
        filename = self.filename(user_id)
        bucket = self.client.bucket(self.bucket_name)
        if not bucket.exists():
            self.client.create_bucket(bucket)
        blob = bucket.blob(filename)
        if blob.exists():
            try:
                blob.reload()
                if blob.metadata and blob.metadata.get("avatar-style-version") == self.style_version:
                    return filename
            except Exception:
                return filename
        blob.metadata = {"avatar-style-version": self.style_version}
        blob.upload_from_string(self.svg(user_id), content_type="image/svg+xml")
        return filename

    def read_avatar(self, filename: str) -> bytes:
        return self.client.bucket(self.bucket_name).blob(filename).download_as_bytes()

    def delete_avatar(self, filename: str) -> None:
        self.client.bucket(self.bucket_name).blob(filename).delete()
