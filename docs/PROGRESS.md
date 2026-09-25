# Progress

## Phase 1 — Foundation ✅ (2026-09-25)

### Done
- **Repo:** monorepo per CLAUDE.md §3, `.gitignore` (Python, Node/Expo, Android/iOS output, secrets, `.env`), `.gitattributes`, and placeholder READMEs for `mobile/` and `design/`.
- **Backend core** (`backend/src/nodly`):
  - `create_app()` factory, with settings from `backend/.env` via pydantic-settings
  - JSON logging with request IDs (`X-Request-ID`)
  - RFC 9457 problem+json errors
  - `GET /healthz` (liveness) and `GET /readyz` (a DB ping with a timeout; 503 when the DB is down)
- **Database:**
  - async SQLAlchemy 2.1 with asyncpg
  - async Alembic
  - migration `0001` creates the identity tables: `families`, `users`, `family_members`, `elders`, `elder_devices`, `invites`, `push_tokens`, `audit_log`
  - migration `0002` creates `jobs`
- **Job queue and worker** (`python -m nodly.worker`):
  - idempotent enqueue inside the caller's transaction
  - SKIP LOCKED claims, retries with capped exponential backoff, a dead-letter state and manual requeue
  - stale-lock reclaim and handler timeouts
  - graceful shutdown, plus a forced shutdown on a second Ctrl+C
  - `debug.echo` and `debug.fail` handlers for trying it by hand
- **Services:**
  - IANA timezone validation and canonical names (`Asia/Calcutta` → `Asia/Kolkata`)
  - the picker list with the current UTC offset and a label
  - suggestions from the device timezone and phone number
  - ISO-3166 validation and flag emoji
  - E.164 normalisation
- **Public reference endpoints:** `GET /v1/meta/timezones`, `/v1/meta/timezones/suggest` and `/v1/meta/countries`.
- **Dev-only router** `/dev/*` (only when `ENV=dev`): create and list families, users, members and elders; enqueue, list and requeue jobs. Every write is audited.
- **Tests:** 152 passing, and ruff is clean. They cover:
  - health and errors
  - schema constraints, a models-vs-migrations drift check, and a migration round trip
  - timezones, including +91/+44/+1/+61 suggestions and DST offsets
  - countries and phones
  - the job queue: retry, dead-letter, idempotency, stale locks, concurrent claims and shutdown
  - the dev router
- **Docs:** [SETUP.md](SETUP.md), [DECISIONS.md](DECISIONS.md).

### Decisions
All recorded in [DECISIONS.md](DECISIONS.md) (D1–D32). The main ones:
- `ENV` is required.
- Errors are problem+json with a stable `code`.
- Enum-like columns are text with CHECK constraints.
- The primary elder (via `is_primary`) is the family clock.
- `tzdata` is pinned for all zone data.
- Pickable zones are zone.tab plus UTC.
- Jobs are enqueued in the caller's transaction.

### Known issues / follow-ups
- **No auth anywhere yet** (Phase 2). `/v1/meta` is public by design; `/dev` must never be mounted outside dev.
- **Invite/pairing codes:** Phase 2 should hash short codes with HMAC and a server secret, not plain SHA-256 (see D17).
- **The jobs table grows forever.** It needs a retention job (for example, pruning succeeded jobs older than 30 days) before launch.
- **The worker has no periodic scheduler yet.** Phase 4 adds the 60-second check-in tick.
- **No dependency lock file.** pyproject has lower bounds only. Pin versions (pip-tools or uv, which needs approval) before the first deploy.
- **Supabase-hosted Postgres via the transaction pooler** needs asyncpg's statement cache turned off. Handle it when we deploy (Phase 16).
- **Country names** are IANA's English names (e.g. "Britain (UK)"). The apps should localise from the code.
- **Worker signals** were tested on Windows (Ctrl+Break); SIGTERM on Linux gets tested at deploy.
- ffmpeg is installed but not used until Phase 6.

### Next
**Phase 2 — Auth, families, invites, elder pairing (API):**
- Supabase email-OTP auth for family members (16+)
- family create/transfer
- invite links and codes
- elder pairing with hashed device tokens
