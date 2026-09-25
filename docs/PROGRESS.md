# Progress

## Deferred until I have a Galaxy device

There's no Android phone for now: testing uses emulators, and these checks wait for a physical
Samsung Galaxy. None of them blocks a phase.

- **Phase 3:** run the app on a physical Samsung phone (the "run it on my Samsung" check), including pairing an elder phone and restarting it.
- **Phase 3:** a push notification arriving on a real device. FCM V1 works on emulators (2026-09-26); real phones, One UI battery rules and Do Not Disturb for `help_alerts` can differ.
- **Phase 3:** pairing by **scanning** the QR code with the camera. Emulators paired by typing the code, which uses the same claim call.
- **Phase 7 and later:** Galaxy Store test purchases, which only work on a physical Galaxy signed into a Samsung account (CLAUDE.md §2).
- **Phase 9 and later:** One UI checks: launcher flow, battery optimisation guidance, Samsung Music (§12), foldable and cover screens (§15).

## Phase 3 — Mobile foundation ✅ (2026-09-26)

**How we work on this PC:**
- Builds happen in the cloud with EAS, never locally.
- Only one heavy thing runs at a time.
- Details are in SETUP.md, "Low-memory workflow".

### Done
- **The app** (`/mobile`): Expo SDK 57, TypeScript strict, Expo Router with typed routes and the React Compiler. Name Nodly, slug and scheme `nodly`, app ID `com.nodlyapp.nodly`. EAS profiles `development`, `galaxy`, `play`, `ios`.
- **Two modes:**
  - The first launch asks in plain words: "Someone set this up for me" (elder) or "I'm setting Nodly up for someone" (family).
  - An elder phone pairs by QR or typed code; case and dashes don't matter.
  - It stays in elder mode across restarts until the family disconnects it or someone types the family PIN.
- **Family sign-in:** Supabase email code (8 digits); the session is kept in SecureStore. Onboarding asks for a name, a country (with flags) and a timezone (with suggestions, never defaulted).
- **Family screens (placeholders until Phase 8):**
  - families: list, create, join by invite code or link
  - a family: clock, elders with phone status, members
  - add an elder
  - pairing: QR, code, countdown, and "connected ✓" as soon as the phone pairs
  - an elder's phone: disconnect, or set up a new phone
  - invites (share, QR, cancel) and the family PIN
- **Elder screens:** pairing (scan or type), home ("Hello, {name}" and the big **I'm okay**, which is a stub until Phase 4), and "This phone" to leave with the family PIN.
- **API layer:**
  - generated types; openapi-fetch; TanStack Query
  - the auth header by mode; problem+json turned into friendly messages
  - an offline banner
  - the server clock (D66)
- **i18n:** English, with typed keys. **Theme:** elder and family scales, light and dark tokens from CLAUDE.md §15.
- **Push:**
  - Expo push tokens for family members and elder phones.
  - Channels `checkin`, `moments`, `help_alerts` (max) and `general`.
  - FCM V1 through Firebase project `nodly-7b90c`. `google-services.json` comes from an EAS secret file; the service-account key is uploaded to EAS and kept out of the repo.
- **Backend for the app:**
  - `POST/DELETE /v1/me/push-tokens` and `POST /v1/device/push-token`
  - the family PIN: `PUT/DELETE /v1/families/{id}/pin`, stored as scrypt, migration `0004`
  - `POST /v1/device/leave`, with wrong PINs throttled
- **EAS:** project `@samuelrayan/nodly`, keystore generated in the cloud, development build `d51f676d` (APK). No native change since, so no other build was needed.
- **Docs:** SETUP 13–19, the Low-memory workflow, the exact FCM steps and a two-device checklist.
- **Checks (2026-09-26):**
  - backend: 297 tests pass; ruff check and format clean
  - mobile: `npm run check` (tsc, lint, API types up to date) passes; expo-doctor 21/21

### Verified on emulators (2026-09-26, Android 16 / API 36, 1.5 GB each)
| Phone | What | Result |
|---|---|---|
| family | Sign in with the emailed code | ✅ families list; push token registered (`204`) |
| family | Create "Rayan family", add Mary Rayan (🇮🇳, Asia/Kolkata) | ✅ pairing code `B740-QWQ7` with QR and a 15-minute countdown |
| family | Restart the app | ✅ still signed in, family mode |
| elder | "Someone set this up for me" → type `b740qwq7` | ✅ paired (`201`), elder home, device push token registered |
| elder | Restart the app | ✅ still the elder home |
| both | Test pushes through Expo's push service | ✅ tickets and receipts `ok`, shown on `general` (family) and `checkin` (elder) |
| both | Channel importances | ✅ `help_alerts` 5 (max), `checkin` 4, `moments` 3, `general` 3 |
| elder | "This phone" with no PIN set | ✅ "Ask your family to disconnect this phone" |
| family | Elder → **Disconnect** | ✅ the elder phone's next call gets `401`, and it lands on Welcome with "Your family disconnected this phone" |
| elder | Pair again with a new code | ✅ elder home |
| family | Set the family PIN | ✅ `204` |
| elder | Wrong PIN, then the right one | ✅ "That PIN isn't right" (`422`), then Welcome with "This phone is no longer in elder mode" (`204`); still Welcome after a restart |

**Done-when:** create a family, add an elder and show a pairing code ✅; a second emulator pairs as that elder ✅; both keep the right mode after restart ✅; tsc and lint pass ✅. The Samsung run is deferred (top of this file). The two emulators ran one after the other rather than side by side, because only 3.3 GB of RAM was free (D68).

### Fixed while testing
- After a restart, family sign-in opened on the verify screen with no email. The screens moved into real route folders (D64).
- The pairing countdown used the phone's clock, which was 28 s off. It now uses the server's clock (D66).
- There was no way for a family to disconnect an elder's phone, and tapping an elder always minted a new code. There's now an elder screen (D67).
- Searching "India" listed British Indian Ocean Territory first. Name matches now rank first.
- supabase-js warned that the `lock` option is deprecated. Removed it.
- Node's DEP0190 warning from `npm run gen:api:check`.

### Decisions
D49–D68 in [DECISIONS.md](DECISIONS.md). The main ones:
- the app ID (D49)
- cloud-only builds (D62)
- the mode and session in SecureStore (D53, D54)
- the family PIN (D56)
- Firebase files kept out of git (D65)
- the server clock (D66)

### Known issues / follow-ups
- **Sign-in needs no redirect URLs:** it's code-only (`detectSessionInUrl: false`, and the email has no link). The Phase 2 note about adding the app's redirect URLs is no longer needed. The Site URL stays `http://localhost:3000` for `dev_login.py`.
- **Invite links are `nodly://invite/<code>`.** They open only where Nodly is installed. Links that work everywhere (https App Links / Universal Links) need a domain (Phase 16); the typed code works meanwhile.
- **Dev builds only:** the dev client's floating "Tools" button sits over the header's right corner.
- **Not checked yet:** dark mode, looked at on a device. The tokens exist; Phase 8 builds the real screens.
- **English only** for now; the i18n setup is ready for more languages.
- **Elder rows** make one `GET /devices` request per elder (D67).
- **The pairing screen** makes a fresh code each time it opens, which cancels the previous one. That's intended; it only matters if two family members show codes for the same elder at once.
- **`adb reverse` rules** sometimes vanish soon after an emulator's first boot. Re-run `npm run reverse` (SETUP troubleshooting).
- **Not built yet:** iOS (Phase 10), the "I'm okay" check-in (Phase 4), the launcher (Phase 9).

### Next
**Phase 4 — Check-ins:**
- the engine: a worker tick every 60 s, the `engine_actions` ledger, tested with frozen time across DST zones
- the elder's **I'm okay** button and the notification action
- the family's status view

## Phase 2 — Auth, families, invites, elder pairing ✅ (2026-09-25)

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
- **Real-user run (2026-09-25, 20:02 IST):** `samuelrayan10@gmail.com` signed in with the emailed code (a real ES256 token). `demo_flow.py` then went through onboarding, a family, an invite with preview, an elder, pairing a fake phone, and `GET /v1/device/me` as that phone. All steps passed.
- **Your Supabase changes:**
  - custom SMTP: codes are sent from your Gmail, and the email limit rose from 2/hour to 30/hour
  - a code-only email template: "Your Nodly sign-in code", **8 digits**
  - a password test user, `test2@nodly.dev`, added in the dashboard

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
- **Email is sent through personal Gmail SMTP.** That's fine for development, but production needs a transactional provider and a sending domain (Phase 16). Sign-in codes are 8 digits, so the app must accept 6–8.
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
