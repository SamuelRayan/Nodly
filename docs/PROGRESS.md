# Progress

## Phase 2 — Auth, families, invites, elder pairing ✅ (2026-09-25; real-user run pending, see below)

### Done
- **Supabase project `nodly-dev`** (ref `hlfxdejxdbukuyekqrjc`, Mumbai, free plan), created through the connector. It uses ES256 signing keys, and its URL and publishable key are in `backend/.env`.
- **Sign-in:**
  - Supabase JWT verification against the project JWKS, asymmetric keys only.
  - A JWKS cache with early refresh on key rotation and a stale-on-outage fallback.
  - `GET /v1/me` creates the account on first call; `PATCH /v1/me` does onboarding (name, timezone, country, 16+).
- **Families:**
  - create, list mine, get, rename
  - transfer organizer, remove a member, leave
- **Invites:**
  - 10-character single-use codes, stored as HMAC, with a link and QR payload, valid 48 hours
  - list, revoke, preview, accept
- **Elders:**
  - create (the first becomes primary and sets the family clock), get, update
  - pause/resume check-ins
  - set primary (organizer only)
- **Pairing:**
  - 8-character codes valid 15 minutes; a new code revokes the old ones
  - an unauthenticated, throttled claim that returns a 256-bit `ndt_` device token once
  - list and revoke devices
- **Device API:** `GET /v1/device/me`, and `POST /v1/device/token/rotate` with a 10-minute grace window.
- **Brute-force protection:** failed code attempts are counted per IP, per user and globally in Postgres; over the limit returns 429 with `Retry-After`.
- **Audit log** entries for users, families, members, invites, elders, pairing codes and devices.
- **OpenAPI:**
  - operationIds are handler names
  - errors are documented as problem+json
  - `scripts/export_openapi.py` writes `backend/openapi.json`, with a test that fails if it's stale
- **Dev scripts:**
  - `scripts/dev_login.py` gets a real Supabase token (click the email link; it's caught on localhost:3000)
  - `scripts/demo_flow.py` runs the whole flow against a running API
- **Tests:** 283 passing; ruff clean. They include:
  - the authorization matrix: 31 operations × 10 kinds of caller, and a check that every route is covered
  - cross-family id mixing
  - JWT attacks: alg none, HS256 confusion, wrong key/issuer/audience, expired, anonymous
  - JWKS rotation and outage
  - code expiry, single use, throttling, token rotation grace, revocation
- **Checked against the real project:** the running API fetched nodly-dev's JWKS, loaded its ES256 key, and rejected a token with a forged signature and one with an unknown key id.

### Decisions
D33–D48 in [DECISIONS.md](DECISIONS.md). The main ones:
- Only asymmetric JWTs are accepted.
- Outsiders get 404.
- Organizer-only actions: rename, transfer, remove, set primary elder.
- Codes are stored as HMAC.
- Brute-force counters live in Postgres.
- Device tokens are `ndt_`-prefixed and rotate with a grace window.
- The first elder becomes primary automatically.

### Known issues / follow-ups
- **The real-user run is still to do.** Supabase's built-in email hit its hourly limit during setup, after two sign-in links were opened by the browser first. To finish:
  1. Run `& $py scripts/dev_login.py samuelrayan10@gmail.com` and click the link.
  2. Run `& $py scripts/demo_flow.py --token <token> --timezone <yours> --country <yours>`, or use /docs (SETUP.md step 10).
- **Email:**
  - Built-in Supabase email sends only a few emails per hour, and only to project team addresses.
  - Real users (and a second test member) need custom SMTP; that's a new provider, so it needs your OK.
  - The Magic Link template needs `{{ .Token }}` for six-digit codes in the mobile app (Phase 3). The connector can't edit auth templates, so that's a dashboard change.
- **Auth settings:** the Site URL is still `http://localhost:3000`. Phase 3 needs the app's deep-link redirect URLs added.
- **Free-plan projects pause after a week of inactivity**; restore them from the dashboard.
- **Not enforced yet:** the 6-member free limit (Phase 7), account and family deletion (Phase 16).
- **Cleanup:** used and expired invite/pairing rows are kept forever (retention job later). Throttle counters are cleaned up as they're written.
- **Timezone list:** `GET /v1/meta/timezones` takes about 0.1s per call; cache it if it's ever hot.

### Next
**Phase 3 — Mobile foundation:**
- Expo app with both modes
- Supabase sign-in in the app
- pairing screen
- i18n, theme, push
- EAS Android build

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
