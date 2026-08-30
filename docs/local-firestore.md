# Local Firestore and Cloud Storage

`docker compose up --build` starts the API, a Firestore Emulator at `localhost:8081`, and a local Storage emulator. The frontend runs separately on the host with `npm run dev` so Next.js hot reload remains available.

The emulator data is stored in the named Docker volume `firestore-data`. On a graceful Compose shutdown it is exported and automatically imported the next time it starts. To reset only the local Firestore data, run:

```powershell
docker compose down
docker volume rm majority_firestore-data
```

The emulator stores the question bank and the global game settings. Active rooms, answers, and countdowns remain in the API process memory and are deliberately cleared when the backend restarts.

The `storage` service is a GCS-compatible local emulator at `localhost:4443`. A user's Firestore document lives at `users/{user-id}` and includes their nickname plus `avatar_filename`. Their generated SVG thumbnail is stored separately in the `majority-main` bucket as `user-thumbnail/{user-id}.svg`. The `storage-data` Docker volume preserves those files. To reset it, run:

```powershell
docker compose down
docker volume rm majority_storage-data
```

For Cloud Run, set `FIRESTORE_ENABLED=true`, `AVATAR_STORAGE_ENABLED=true`, `FIRESTORE_PROJECT_ID` to the Google Cloud project ID, and `AVATAR_BUCKET` to an existing Cloud Storage bucket. Do not set `FIRESTORE_EMULATOR_HOST` or `STORAGE_EMULATOR_HOST` in production. Grant the Cloud Run API service account `roles/datastore.user` and `roles/storage.objectAdmin` for that bucket.

`AVATAR_OBJECT_PREFIX` controls the folder-like object prefix and defaults to `user-thumbnail`. The provided `.env.example` contains all local storage-related values; Compose reads it automatically when present.
