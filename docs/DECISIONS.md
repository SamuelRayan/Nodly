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

## Phase 3 — Mobile foundation (2026-09-25)

### App identity and builds
- **D49. The app ID is `com.nodlyapp.nodly` on both Android and iOS.**
  *`app.nodly` would have implied owning `nodly.app`, which is registered, as are `nodly.com` and `getnodly.com`, by owners we don't know. If someone else published under that namespace first, our upload would be blocked. `com.nodlyapp.nodly` is unused on Google Play and matches the unregistered `nodlyapp.com`. The ID is permanent after the first store upload.*
- **D50. Expo SDK 57** (React Native 0.86, React 19.2, TypeScript 6), trimmed from the default template: no web, no demo screens.
  - **Routes:** they live in `src/app` with Expo Router, and the React Compiler is on.
  - **Screen orientation:** not locked, for foldables and split screen (§15). Android 16 ignores orientation locks on large screens anyway.
  - **`android/` and `ios/`:** generated by `npx expo prebuild` and git-ignored.
- **D51. EAS profiles:** `development` (a development build, internal APK), plus `galaxy`, `play` and `ios`, each setting `EXPO_PUBLIC_STORE`.
  - **Galaxy uses an APK for now.** Whether Galaxy Store takes AABs gets verified before the first upload (Phase 16).
  - **Store keys come later:** RevenueCat keys and the CI check that keys aren't mixed between profiles arrive with Phase 7.
- **D52. API types are generated from `backend/openapi.json` by a pinned `openapi-typescript@7.13.0`, run through `npx`.**
  *It declares TypeScript 5 as a peer and the app uses 6. The generator runs isolated; the `.d.ts` it writes works with both.*
  - `npm run gen:api:check` fails if the types are stale.
  - The client is **openapi-fetch**; `unwrap()` turns problem+json into `ApiError`.

### Modes, sessions and storage
- **D53. The mode (`family` / `elder`) and the elder's device token live in SecureStore.** The root layout picks the screens with `Stack.Protected` guards: `welcome`, `signin/`, `onboarding`, `family-error`, `(family)/`, `pair/`, `home/` (the elder home). The splash screen stays up until that's known.
  - An elder phone only leaves elder mode when the API says `device_revoked`, which sends it to Welcome with a notice, or with the family PIN.
  - Before pairing, or before signing in, "Back" returns to the choice.
- **D54. The Supabase session is stored in SecureStore, split into 1,800-character chunks.** Supabase's own example uses AES + AsyncStorage, which needs three more libraries; chunking avoids the ~2 KB platform limit Expo warns about with none.
  - This follows Supabase's React Native setup: `react-native-url-polyfill`, and auto-refresh only in the foreground. There's no `lock` option (their example passes `processLock`): supabase-js 2.117 deprecates it and warns at startup.
  - SecureStore items are readable after the first unlock since boot, so later background work (an "I'm okay" from a notification) can use the device token.
- **D55. Auth header by mode:** the device token in elder mode, and the Supabase JWT (from `getSession()`, which refreshes itself) in family mode.
  - `device_revoked` and `invalid_token` are handled once, app-wide, from the TanStack Query caches.
  - Queries retry only when there's no answer, on 5xx, or once on `token_expired`.

### Family PIN, push, i18n
- **D56. The family PIN is 4–8 digits, set by the organizer and stored as scrypt** (Python stdlib, migration `0004`). `POST /v1/device/leave` checks it, with wrong PINs limited per phone (5 per 15 minutes by default) and per IP. Without a PIN, the family disconnects the phone from their app.
- **D57. Push tokens are upserted by `(provider, token)`**, so a phone's token follows whoever uses it now (sign-out and sign-in, re-pairing). Registration never blocks the app. Without an EAS project id or Firebase config, it logs and skips.
- **D58. Android channels are created at startup and before asking for permission** (Android 13+ requires that order):
  - `checkin` (high)
  - `moments` (default)
  - `help_alerts` (max, bypasses Do Not Disturb, visible on the lock screen, long vibration)
  - `general` (default)

  The app can't change a channel's importance after creating it, so these levels are deliberate.
- **D59. Every string goes through `t()`, and keys are typed from `en.json`**, so a missing key fails `tsc`. The elder's language comes from their profile (`elders.language`) and falls back to the phone's language, then English.
- **D60. Devices reach the local API through `adb reverse`** (`npm run reverse`): `EXPO_PUBLIC_API_URL=http://localhost:8000` then works on every emulator and USB phone at once. Wi-Fi and tunnel setups are documented as alternatives.
- **D62. Native builds happen in the cloud (EAS), never locally**, because this PC has 16 GB RAM and a local Gradle build plus an emulator plus Metro ran it out of memory.
  - **Cloud builds only when native dependencies or `app.config.ts` change**; everything else is a Metro reload. Claude says before each cloud build, and why.
  - **Budget:** the free plan has 15 Android builds a month (not carried over), a low-priority queue (about 9 minutes on average, up to ~45 at busy times) and a 45-minute build limit.
  - **On the PC:** Metro plus one emulator at 1.5 GB with quick boot on. A second emulator only for batched two-device tests, shut down right after.
  - **No `CLAUDE_CODE_DISABLE_BG_SHELL_PRESSURE_REAP`:** a stopped task beats a swapping PC.
  - **Expo project:** `@samuelrayan/nodly` (id `a00f75c5-…`, in `app.config.ts`). EAS holds the Android signing key it generated.
- **D63. Physical Samsung checks are deferred** until there's a Galaxy device (the list is in PROGRESS.md). Emulators cover everything else.
- **D61. Dependencies added (approved):**
  - **New libraries:** `openapi-fetch`, `@react-native-community/netinfo`, `react-native-qrcode-svg` + `react-native-svg`, `expo-device`.
  - **Covered by the stack or Supabase's documented React Native setup:** `@supabase/supabase-js`, `react-native-url-polyfill`, `react-i18next`.
  - **Tooling:** `react-dom` stays pinned at 19.2.3 like the template, because npm 11 otherwise pulls a mismatched optional peer.

### Found while testing on emulators
- **D64. Sign-in, elder pairing and the elder home are real route folders (`signin/`, `pair/`, `home/`), not route groups.**
  *Groups like `(signin)` add nothing to the URL, so their screens share the root's URL space. After a restart the family sign-in opened on its verify screen, with no email. Each folder now has an `index` and its own Stack. The `(family)` group stays a group, anchored on `index` so a deep link (an invite) still has the family home underneath.*
- **D65. Firebase files stay out of git; the repo will be public.**
  - `google-services.json` is git-ignored. Local runs point at it through `GOOGLE_SERVICES_JSON` in `mobile/.env`, and cloud builds get it from an EAS secret *file* variable of the same name (development and production environments). `app.config.ts` only sets `android.googleServicesFile` when the variable exists.
  - The FCM V1 service-account key lives outside the repo and is uploaded to EAS credentials; the app never sees it. `.gitignore` also blocks `*firebase-adminsdk*.json` and `*service-account*.json`.
- **D66. Comparisons with server timestamps use the server's clock.** The API client estimates it from each response's `Date` header (`serverNow()`).
  *The emulator's clock was 28 s behind, so a 15-minute pairing code showed "15:22 left". A phone running fast could also miss a pairing, because "paired after this code" compared server and phone clocks. Phones' clocks are often off; the server is the one clock that matters.*
- **D67. Families manage an elder's phone from an elder screen:** the connected phone(s), **Disconnect** (with a confirmation), and **Set up a (new) phone**. Elder rows say whether a phone is connected.
  *Before, tapping an elder always minted a new pairing code, and nothing in the app could disconnect a phone, although the elder's leave screen and the PIN screen both said the family could. Status comes from one `GET /devices` per elder row. That's fine for a few elders; Phase 4's status data can replace it.*
- **D68. Two-device tests can run one emulator at a time.** Pairing goes through the server, so the family emulator can be off while the elder emulator pairs.
  *Each emulator process takes about 3 GB of RAM, even at a 1.5 GB guest. With 3.3 GB free, a second one would have pushed the PC into swap.*

## Shipaton sprint (2026-09-26 → 2026-10-01)

- **D69. The Shipaton target is the Next Gen award.**
  - What judges get: a demo video under 2 minutes and this repo, public under **MIT**.
  - Purchases run through RevenueCat's **Test Store**; there's no store release before the deadline (30 Sep, 11:45 PM PDT = 1 Oct, 12:15 PM IST).
  *Every other category needs a live store listing. An app still in review at the deadline doesn't qualify, and RevenueCat advises submitting a week ahead. Next Gen is judged on the video and the repo.*
  - **Pulled forward, with the tests CLAUDE.md requires:** slices of Phases 4–8, namely check-ins, Help, moments (photo and voice first), Plus with the Test Store, and the design's screens.
  - **Cut until after Shipaton:**
    - recipes, cooked photos and reporting
    - AI, music, launcher, widgets
    - live presence, SMS/voice escalation
    - foldable layouts, iOS, Google sign-in
  - The Test Store key never ships in a store build (CLAUDE.md §10).
- **D70. The Claude Design handoff of 2026-09-26 (`design/2026-09-26-nodly-handoff/`) is the visual reference.**
  - **Fonts:** Newsreader for headings (static 500, 600 and 700; expo-font 57.0.4's plugin can't set a variable font's axes) and Atkinson Hyperlegible for everything else (400/700). Both are under the SIL Open Font License, embedded with the expo-font config plugin.
  - **Palette:** the design's colours replace the starting tokens in CLAUDE.md §15. Checked against its contrast rules:
    - body text 7.5:1 or better on every background, in light and dark
    - labels on the green, red and alert buttons 5.4:1 or better
  - **Icons:** drawn from the design's logo by `mobile/scripts/make-icons.py`.
- **D71. Where the design and CLAUDE.md differ, for Shipaton:**
  - **Pairing:** the direction stays as built, with the family showing the code and the elder typing or scanning it. The design has the elder's phone show a 6-digit code instead. The screens are restyled now, and the direction switches after Shipaton.
  - **Plus rules:** CLAUDE.md §10's money rules stand. A moment on day D gives Plus through D+1 on the family clock, and a Day Pass lasts 24 hours from purchase. The design's copy ("until midnight") is changed to match.
  - **Help countdown:** 5 seconds (§8; the design shows 3). It's a config value.
  - **Elder body text:** at least 20 pt (§15; the design allows 18).
  - **Sign-in:** "Continue with Google" is dropped, email code only. §5 would require Sign in with Apple alongside it.
  - **Check-in settings:** they follow §7's engine (reminder time, due-by time, grace period).
  - **"Amma's day" consent:** it's gated behind the elder's consent (§13), asked in plain words right after pairing. The design has no consent step.
- **D72. Packages added for the second development build (approved):**
  - **Mobile:** `react-native-purchases` and `react-native-purchases-ui` 10.10.2 (Test Store needs 9.9.0+ on Android), `expo-image-picker`, `expo-audio` (+ its required peer `expo-asset`), `expo-video`, `expo-file-system`, `expo-haptics`.
  - Background audio and video playback are off, so there's no foreground service to declare.
  - **Backend:** `pillow` and `imagehash`, for the moments photo checks.
- **D73. Moment files live in a local media store for the sprint, behind a small storage module (`nodly/media.py`).** The API serves them through HMAC-signed links that expire after 10 minutes. The signature is keyed from `CODE_HASH_SECRET` with its own domain prefix, so there's no new secret.
  *Supabase Storage needs the project's secret key, which the Supabase connector deliberately doesn't expose. It would also make the recorded demo depend on internet uploads, and add a secret just before the repo goes public. A Supabase Storage store (private bucket, its own signed URLs) replaces `media.py` behind the same functions after Shipaton.*
  - Uploads are a plain PUT of the file to the API. Photos are small, and the app's persistent queue retries a whole upload. Resumable (TUS) uploads come with video and the Supabase store.
  - `backend/var/` (the dev media folder) is git-ignored: it holds family photos.
- **D74. Notification buttons: a background task handles them where Android lets it** (`Notifications.registerTaskAsync`, `expo-task-manager`). The elder's "I'm okay" checks in and the family's "I'm on it" acknowledges Help, then a quiet confirmation replaces the notification. While the app is open, the normal response listener handles the same buttons. See D75 for when buttons can appear at all.
- **D75. Help alerts and reminders stay ordinary notifications; tapping one opens straight to a one-tap screen.**
  - Tested on emulators (2026-09-27): the Expo Push Service sends title/body pushes as FCM notification messages. While the app isn't in the foreground, Android draws those itself, without our categories, so there are no buttons.
  - Data-only pushes would be presented by the app with buttons, but they rely on JS running in the background, which Android doesn't guarantee (Doze). A Help alert must never silently fail to appear.
  - Sending straight through FCM (natively presented data messages) needs a Firebase service-account key on the server and native FCM tokens.
  - So, for Shipaton:
    - tapping a Help notification opens the full-screen alert with its big "I'm on it"
    - tapping a reminder opens the home with its big "I'm okay"
    - buttons appear, and work, whenever the app shows the notification itself (app in the foreground)
  - **After Shipaton:** send through FCM directly with data messages presented natively, and test on a physical Samsung (One UI).
  - Also: a force-stopped Android app receives no FCM messages until it's opened again (Android's "stopped" state). Swiping it away from recents is fine.- **D76. Voice notes are AAC in an MP4 (`.m4a`) file, and the worker measures them with ffprobe.**
  - That's what expo-audio records on both Android and iOS, so the API accepts only `audio/mp4` (and its aliases `audio/m4a`, `audio/x-m4a`). The worker rejects anything that isn't an MP4 container with an audio stream, no video and a duration (`not_audio`). Another format would be stored under the wrong extension and might not play on the elder's phone.
  - Limits (config): posted up to 5 minutes (`too_long` beyond), and it counts for the day from 10 s (§10; `too_short` below, still posted). A 20 MB upload cap.
  - ffprobe runs in a worker thread through `subprocess`, so it works under any event loop (Windows included). `FFPROBE_PATH` sets the binary.
  - The app records mono 64 kbps (about 2.4 MB for 5 minutes), tap to start and tap to stop (never hold-to-talk), and stops itself just under 5 minutes, so a finished recording is never over the limit. Its "counts for today" hints are guidance only; the server decides.
  - Only photos are checked for near-duplicates (§10 names photos). Re-sending the same recording would still count; accepted for the sprint.
- **D77. Nodly Plus billing (S4): one ledger, one judge, RevenueCat as the only witness.**
  - `access_grants` is the ledger: [starts_at, ends_at) per family, from moment credits, Day Passes, subscription periods or goodwill. It is never edited; a refund revokes. `evaluate_access` is the only function that answers "has Plus"; the app only displays its answer.
  - **Moment credit:** granted in the same transaction as the moment's verdict: from the start of day D to the end of D+1 on the family clock (DST-aware, via `local_instant`). One per family and day (a partial unique index). Moments that qualified before the ledger existed were backfilled by the migration.
  - **Day Pass:** 24 h from the purchase time RevenueCat confirms. It is recorded only from RevenueCat: the webhook (`NON_RENEWING_PURCHASE`) or `POST /access/refresh`, which calls REST v1 `GET /subscribers/{app_user_id}` with the server's secret key. The app calls refresh after buying and polls `/access`; it never unlocks anything itself. The Test Store has no public webhook target in local dev, so refresh is the demo path; the webhook is ready for deployment.
  - `day_pass` must **not** be attached to the `plus` entitlement in RevenueCat: a non-subscription product on an entitlement unlocks it for life. Subscriptions (`plus_monthly`, `plus_annual`) are attached; the server mirrors each paid period as a grant.
  - **Idempotency:** purchases are unique by (store, transaction id) and, as a backstop, by (store, app user, product, purchase second). Webhook events are unique by event id. A refund that arrives before its purchase records the purchase as refunded, so the late purchase grants nothing.
  - **Who:** RevenueCat's App User ID is our `users.id` (from `/v1/me`), not the Supabase auth id: the server looks up that same id with RevenueCat, and webhooks map straight to a user.
  - **Which family:** the app sets the `family_id` customer attribute before buying. A webhook uses it if the buyer is a member, otherwise their only family; otherwise the purchase waits and the buyer's next refresh claims it. The first family to get a purchase keeps it.
  - **Offer rules (§10):** a Day Pass is offered only without Plus and without a family member's moment on its way today.
  - **Sandbox:** Test Store and store-sandbox purchases count only with `BILLING_ACCEPT_SANDBOX` (off in prod, and prod refuses to turn it on).
  - **The sprint's Plus feature:** check-in history beyond 7 days (up to 30), gated on the server (`403 plus_required`). The 7-day strip stays free.
  - **Deferred until after Shipaton:** the overlap detector, `billing_incidents`, store refunds initiated by us, the family billing timeline beyond `/access`, and `REFUND_REVERSED`.
  - **App side:** the SDK is configured only in family mode, with the Test Store key only in development builds (`__DEV__`). An ESLint rule forbids any purchase import in elder screens, and the billing functions throw in elder mode. The F8 sheet puts "Share a moment" first; after a purchase it shows "Confirming…" and calls `/access/refresh` every 2 s (up to 30 s) until the server says Plus is on.
