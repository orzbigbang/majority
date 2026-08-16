from __future__ import annotations

import hashlib
import os

from google.cloud import storage


class AvatarStorage:
    """Stores deterministic Party Token avatar SVG files in Cloud Storage."""

    palettes = (
        ("#8067ff", "#5a46be", "#ffcf70", "#fff7dd"),
        ("#ff5d8f", "#bc3f6c", "#8be6d3", "#effffb"),
        ("#35b9df", "#2567b5", "#ffd36b", "#effcff"),
        ("#f8954b", "#bf4a49", "#a7ef9c", "#f7fff1"),
        ("#a66bef", "#6644b9", "#ff9f86", "#fff5ef"),
        ("#4dd39b", "#177c78", "#ffcf69", "#f5ffce"),
    )

    def __init__(self) -> None:
        self.bucket_name = os.getenv("AVATAR_BUCKET", "majority-main")
        self.client = storage.Client(project=os.getenv("FIRESTORE_PROJECT_ID"))

    @staticmethod
    def filename(user_id: str) -> str:
        prefix = os.getenv("AVATAR_OBJECT_PREFIX", "user-thumbnail").strip("/")
        return f"{prefix}/{user_id}.svg" if prefix else f"{user_id}.svg"

    @property
    def style_version(self) -> str:
        return os.getenv("AVATAR_STYLE_VERSION", "party-token-v1")

    @staticmethod
    def svg(user_id: str) -> str:
        """Create a recognisable, stable game token from an opaque user UUID."""
        digest = hashlib.sha256(user_id.encode()).digest()
        base, shadow, accent, light = AvatarStorage.palettes[digest[0] % len(AvatarStorage.palettes)]
        pip_sets = (
            ((80, 80),),
            ((62, 62), (98, 98)),
            ((62, 62), (80, 80), (98, 98)),
            ((62, 62), (98, 62), (62, 98), (98, 98)),
            ((62, 62), (98, 62), (80, 80), (62, 98), (98, 98)),
            ((62, 60), (98, 60), (62, 80), (98, 80), (62, 100), (98, 100)),
        )
        pips = "".join(f'<circle cx="{x}" cy="{y}" r="7" fill="{shadow}"/>' for x, y in pip_sets[digest[1] % len(pip_sets)])
        rotation = (digest[2] % 21) - 10
        confetti = (digest[3] % 3) * 8
        return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 160" role="img" aria-labelledby="title">
  <title id="title">Party Quiz player token</title>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop stop-color="{base}"/><stop offset="1" stop-color="{shadow}"/></linearGradient>
  </defs>
  <rect width="160" height="160" rx="36" fill="url(#bg)"/>
  <circle cx="18" cy="32" r="28" fill="{light}" opacity=".18"/>
  <circle cx="145" cy="132" r="36" fill="{accent}" opacity=".25"/>
  <path d="M23 {46 + confetti}l8-15 8 15-8 15zM124 30l6-12 6 12-6 12zM31 129l5-10 5 10-5 10z" fill="{light}" opacity=".85"/>
  <g transform="rotate({rotation} 80 80)">
    <rect x="38" y="38" width="84" height="84" rx="28" fill="{accent}" opacity=".38"/>
    <circle cx="80" cy="80" r="43" fill="{light}"/>
    <circle cx="80" cy="80" r="35" fill="{accent}" opacity=".26"/>
    {pips}
  </g>
</svg>'''

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
