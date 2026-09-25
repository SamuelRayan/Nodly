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
