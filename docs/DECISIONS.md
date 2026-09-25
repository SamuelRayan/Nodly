# Decisions

Short records of choices that aren't obvious from the code. Newest phase at the bottom.
Format: **what** we decided, then *why*.

## Phase 1 — Foundation (2026-09-25)

### Repo & tooling
- **D1. Backend is an installable package `nodly` in `backend/src/`** (setuptools, `pip install -e ".[dev]"`).
  *The API, worker, Alembic and tests all import the same code from any folder.*
- **D2. Dependencies added beyond CLAUDE.md §4 (approved): `tzdata`, `uvicorn[standard]`.** We did **not** add `email-validator`: the dev routes do a basic email check, and Supabase validates properly from Phase 2.
  *uvicorn is the server FastAPI needs. tzdata is explained in D14.*
- **D3. `ENV` is required and has no default.** The `/dev` routes are mounted only when `ENV=dev`, and `/docs` + `/openapi.json` are hidden when `ENV=prod`.
  *A forgotten variable must never expose unauthenticated dev routes.*

### API conventions
- **D4. Errors are RFC 9457 problem details** (`application/problem+json`) with `type` (`urn:nodly:problem:<code>`), `title`, `status`, `detail`, `instance`, `code` and `request_id`. Validation errors add `errors[]` with `loc`/`msg`/`type` but **not the rejected input**.
  *Apps switch on the stable `code` and show their own translated text; `detail` is English for developers. The rejected input can contain tokens or codes.*
- **D5. Only unique violations become 409s** (with the constraint name). Other integrity errors are 500s.
  *Other integrity errors mean our own validation missed something, which is a bug.*
- **D6. Public API lives under `/v1`.** Health probes are at the root. `/v1/meta/*` (timezones, countries) is public reference data with no auth.
- **D7. The dev-only router is at `/dev`, not `/admin`.** It has no auth, and every write is audited with actor `dev`.
  *`/admin` is kept for the real protected moderation queue (Phase 12).*

### Logging
- **D8. JSON lines on stdout with the standard library** (no structlog). Context such as `request_id`, `job_id` and `job_type` is kept in contextvars and added to every line. uvicorn's access log is off because our middleware writes one line per request with the request ID.
- **D9. `X-Request-ID` from the caller is kept only if it is 8–128 characters from `[A-Za-z0-9._-]`**; otherwise we generate one. It is echoed on every response, including 500s.

### Database
- **D10. Primary keys are UUIDs**, generated in Python (`uuid4`) with `gen_random_uuid()` as the server default. Append-only tables (`audit_log`, `jobs`) use bigint identity instead. All timestamps are `timestamptz` in UTC.
- **D11. Enum-like columns are `text` with CHECK constraints**, not Postgres enum types.
  *Adding a value is a one-line migration; Postgres enums are awkward to change.*
- **D12. Constraint names follow a naming convention** (`ck_`, `uq_`, `ix_`, `fk_`, `pk_`) and are asserted in tests.
- **D13. The current time comes from `nodly.clock.utcnow()` and is passed into SQL**, not taken from the database's `now()`, for anything the logic depends on. `created_at`/`updated_at` still use server defaults.
  *Tests can freeze or advance time without the database disagreeing.*

### Identity schema
- **D14. The family clock is the primary elder**: `elders.is_primary` with a partial unique index (at most one per family). We did not use a `families.primary_elder_id` FK. Phase 2 decides whether a family must always have a primary elder.
  *A families↔elders FK would be circular.*
- **D15. `elders.country_code` is required; `users.country_code` is optional.** Timezones are required on both, with no default.
  *The Help screen shows the elder's local emergency number.*
- **D16. Check-in settings live on `elders` as `checkin_*` columns** with the §7 defaults: 09:00, 12:00, 60 minutes grace, activity counts as OK. There is a DB check that `remind_at ≤ due_by`, and grace must be 0–720.
- **D17. One `invites` table holds both member invites and elder pairing codes** (`kind`, with a CHECK that pairing rows have an `elder_id`). Device tokens and invite codes are stored only as SHA-256 hex.
  - **For Phase 2:** hash the *short* invite/pairing codes with HMAC-SHA256 and a server secret. A leaked database must not let anyone brute-force live short codes. Device tokens are 256-bit random, so plain SHA-256 is fine for them.
- **D18. `push_tokens` belong to exactly one user or one elder device** (`num_nonnulls(...) = 1`). The provider (`expo`/`fcm`/`apns`) is chosen in Phase 3.
- **D19. `audit_log` has no foreign keys**, so history outlives deleted rows. Personal data in it is scrubbed on account deletion (Phase 16).
- **D20. Emails are unique case-insensitively** (unique index on `lower(email)`); the dev routes also store them lowercased. Phase 2 should store the address Supabase Auth reports.

### Job queue
- **D21. `enqueue()` writes in the caller's transaction and does not commit.** A job exists if and only if the caller's own change was committed.
- **D22. Idempotency is unique on `(type, idempotency_key)` while the row exists, whatever its state.** Re-enqueueing returns the original job. Jobs without a key never conflict.
- **D23. Claims use `FOR UPDATE SKIP LOCKED`.** Retries back off with `min(base·2^(n-1), cap)` plus up to 10% jitter. Out of attempts → `dead`. `PermanentJobError` or an unregistered type → `dead` immediately.
- **D24. A job still `running` past `JOB_LOCK_TIMEOUT_SECONDS` is reclaimed.** The crash counts as an attempt, and the job is retried immediately. Finishing a job requires still holding its lock, so a slow worker can't overwrite a job that was re-run elsewhere. Settings reject a lock timeout that isn't longer than the job timeout.
- **D25. Shutdown:** the first Ctrl+C (or SIGTERM/SIGBREAK) drains running jobs for up to `WORKER_SHUTDOWN_GRACE_SECONDS`. A second one cancels them, and each cancelled job is recorded as a failed attempt.
  *`signal.signal` is used because `loop.add_signal_handler` doesn't exist on Windows.*

### Time, countries, phones
- **D26. All zone data comes from the pinned `tzdata` pip package.** `nodly/__init__.py` calls `zoneinfo.reset_tzpath(to=[])`.
  *Conda, Windows and Linux would otherwise each use their own tz database version. Bump `tzdata` when IANA releases.*
- **D27. Pickable timezones are IANA `zone.tab` (real places, one row per country) plus `Etc/UTC`.** Old or alternative names are accepted and stored as their link target, using the `L` lines in `tzdata.zi`: `Asia/Calcutta` → `Asia/Kolkata`, `US/Eastern` → `America/New_York`, and `UTC`/`GMT` → `Etc/UTC`. `Etc/GMT±N`, `Factory` and other names that aren't places are rejected.
  *libphonenumber itself returns `Asia/Calcutta` for +91, and old devices report old names.*
- **D28. Timezone suggestions come in this order: the device's zone, then zones for the phone number's area (libphonenumber), then the rest of the number's country.** No input means no suggestions, because we never default. A device zone we can't use is ignored silently; an invalid phone number is a 422.
- **D29. Countries are IANA `iso3166.tab` (249 codes) plus `XK` (Kosovo).** The English names come from that file, e.g. "Britain (UK)". Apps should localise names from the code.
  *libphonenumber and CLDR support `XK`.*
- **D30. Phones must pass libphonenumber's `is_valid_number` and are stored as E.164.** A number without `+` needs a country the user picked; there is no default region.

### Tests
- **D31. Tests build the schema with the real migrations**, check that models match migrations (autogenerate diff is empty), and do a downgrade/upgrade round trip.
- **D32. The test database name must end in `_test`.** Tables are emptied with `DELETE` after each DB test, not wrapped in a rolled-back transaction.
  *Code under test can then commit and use several connections, like the worker does. `DELETE` is about 2× faster than `TRUNCATE` on near-empty tables.*

## Phase 2 — Auth, families, invites, elder pairing (2026-09-25)

### Sign-in (Supabase)
- **D33. Only asymmetric Supabase tokens (ES256/RS256) are accepted.** They're checked against `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. The checks are: `iss = <SUPABASE_URL>/auth/v1`, `aud = authenticated`, `exp`/`iat` with 30s leeway, `role = authenticated`, `sub` is a UUID, and not `is_anonymous`. Symmetric keys in the JWKS are ignored, so HS256 and `alg: none` are always rejected. There is no support for the legacy shared JWT secret.
  *Supabase itself marks the shared secret "not recommended"; asymmetric keys rotate without deploys. https://supabase.com/docs/guides/auth/signing-keys*
- **D34. The JWKS is cached for 10 minutes.** A token with an unknown `kid` triggers an early refresh (key rotation). Fetches happen at most every 30s: during a Supabase outage the cached keys keep working, and with no keys at all requests fail fast with `503 auth_unavailable`. Without `SUPABASE_URL`, user endpoints answer `503 auth_not_configured`; staging/prod refuse to start without it.
- **D35. Accounts are created on the first `GET /v1/me`, keyed by the token's `sub`** (`users.auth_user_id`). The email follows what Supabase reports. If the email already belongs to another row, the answer is `409 email_in_use`; we never link accounts by email.
- **D36. Onboarding requires a display name, a user-picked timezone, a country and an "I'm 16 or older" confirmation** (`age_confirmed_at`). A DB CHECK enforces the full profile once `onboarded_at` is set. Every family endpoint answers `403 onboarding_required` until then. `locale` was renamed to `language` on users and elders.

### Who can do what
- **D37. Outsiders get 404 for anything in a family they don't belong to**, the same answer as an id that doesn't exist.
  - **Organizer only:** rename the family, transfer the organizer role, remove a member, set the primary elder. The primary elder changes the family clock, and so billing days.
  - **Any member:** invite, add/edit/pause elders, create pairing codes, list and revoke devices. Revoking is open to all because a lost phone is a safety issue.
  - **Invites:** only their creator or the organizer can revoke one.
  - **Leaving:** the organizer must transfer the role before leaving. A member who leaves or is removed has their open invites revoked.
- **D38. The family's first elder becomes primary automatically.** The family clock is `null` until there's an elder.

### Codes
- **D39. Invite and pairing codes use Crockford base32.** Typing is forgiving: case, spaces and dashes are ignored and O/I/L are read as 0/1/1.
  - Invites are 10 characters (50 bits), last 48 hours, and are shared as a link.
  - Pairing codes are 8 characters (40 bits) and last 15 minutes. A new pairing code revokes that elder's older open codes.
  - Codes are stored as **HMAC-SHA256 with `CODE_HASH_SECRET`**, namespaced by kind, and shown only once.
  - Links and QR payloads are `INVITE_LINK_BASE_URL` / `PAIRING_QR_BASE_URL` + the code (`nodly://…` for now).
- **D40. Answers for bad codes:** `422 invalid_code` (unknown), `410 code_expired`, `410 code_used` (used or cancelled). `409 already_member` doesn't use the code up. Previewing an invite doesn't use it either, and works before onboarding.
- **D41. Brute-force protection counts failed code attempts** (claim, preview, accept) in Postgres fixed windows: per client IP, per signed-in user, and globally (10/10/500 per 15 minutes by default). Over the limit is `429` with `Retry-After`, even for a correct code.
  - The global limit trades a brief pairing lockout during a flood for resistance to distributed guessing.
  - Behind a proxy, uvicorn needs `--proxy-headers` so the IP is the client's.

### Elder devices
- **D42. A device token is `ndt_` + 256 random bits.** It's returned once by the claim and stored as SHA-256.
  - It has its own OpenAPI scheme (DeviceToken) and works only on `/v1/device/*`, which take no elder or family ids. A device can only ever see its own elder. User tokens are rejected there, and device tokens on user endpoints.
  - A revoked device gets `401 device_revoked`.
  - `last_seen_at` is written at most every 5 minutes.
- **D43. Token rotation keeps the token the phone presented valid for 10 minutes.** It's stored as `previous_token_hash`. A lost response, or a retry with the old token, can never lock the elder's phone out.
- **D44. Pausing an elder (`paused_at`, optional `paused_until`) stops check-in reminders and missed-check-in alerts** (Phase 4). A pause past its `paused_until` has ended by itself. **Help is never paused** (Phase 5 must keep that).

### API shape
- **D45. OpenAPI:**
  - `operationId`s are handler names (`create_family`); dev routes get a `dev_` prefix.
  - Every 4xx/5xx is documented as `application/problem+json` with the `Problem` schema.
  - `scripts/export_openapi.py` writes `backend/openapi.json` (never with `/dev`). A test fails if the committed file is stale.
- **D46. Dependencies added (approved): `pyjwt[crypto]`.** It brings in `cryptography`.

### Supabase project
- **D47. The dev project is `nodly-dev`** (ref `hlfxdejxdbukuyekqrjc`, Mumbai `ap-south-1`, free plan). It's used only for Auth for now; the backend database stays local in dev. Production gets its own project, in a region chosen for its users.
- **D48. `scripts/dev_login.py` catches the sign-in on `http://localhost:3000`**, Supabase's default Site URL: clicking the email link is enough. Emailed links work once; we learned that the hard way when the browser and the script raced for the same link.
