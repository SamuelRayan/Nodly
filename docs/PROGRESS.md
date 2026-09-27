# Progress

## Deferred until I have a Galaxy device

There's no Android phone for now: testing uses emulators, and these checks wait for a physical
Samsung Galaxy. None of them blocks a phase.

- **Phase 3:** run the app on a physical Samsung phone (the "run it on my Samsung" check), including pairing an elder phone and restarting it.
- **Phase 3:** a push notification arriving on a real device. FCM V1 works on emulators (2026-09-26); real phones, One UI battery rules and Do Not Disturb for `help_alerts` can differ.
- **Phase 3:** pairing by **scanning** the QR code with the camera. Emulators paired by typing the code, which uses the same claim call.
- **Phase 7 and later:** Galaxy Store test purchases, which only work on a physical Galaxy signed into a Samsung account (CLAUDE.md §2).
- **Phase 9 and later:** One UI checks: launcher flow, battery optimisation guidance, Samsung Music (§12), foldable and cover screens (§15).

## Shipaton sprint (in progress; plan and scope in DECISIONS D69–D72)

Target: the Next Gen award. The deadline is 30 Sep, 11:45 PM PDT (1 Oct, 12:15 PM IST).

### Day 1 (2026-09-26): check-ins and Help, backend and app
- **Development build 2** (`08f48d7f`) adds RevenueCat, image picker, audio, video, file system and haptics, plus the embedded fonts and new icons. The first attempt (`7d34e42b`) failed in prebuild: expo-font 57.0.4's plugin can't read a variable font's family-level path. A local prebuild now validates native config before any cloud build.
- **Check-ins (Phase 4 slice):**
  - the engine as pure functions, tested across DST and odd offsets
  - a 60-second periodic tick in the worker, with the `engine_actions` ledger
  - reminders, a family notice at the due time, and the missed check-in alert
  - "All good" after a late tap; Mark okay; "I'm on it"
  - the family status with the week strip; "starts tomorrow" for phones set up after the due time
- **Help (Phase 5 slice):**
  - requests with optional location, battery and network
  - repeats every minute until "I'm on it" (at most 15 minutes); SMS and voice logged as skipped until Phase 15
  - cancel and resolve; the whole timeline is kept
  - test alerts: labelled, 3 a day, never repeating, never blocking real Help
- **App:**
  - the design system from the handoff (tokens, fonts, icons)
  - elder screens E2, E3, E4, E7, E8, E9, E10 and the past-due and alerted states (E11, E12)
  - family dashboard (F2, F9, F10), full-screen Help alert (F7), Help banners
  - notification buttons ("I'm okay", "I'm on it")
- **Tests:** 367 backend tests pass; tsc and lint are clean.

**Verified on emulators (one at a time, D68):**
- Family:
  - dashboard with a missed check-in → "I'm on it" ("Samuel is on it") → Mark okay ("Samuel marked them okay at 1:33 PM · 1 minute ago")
  - test Help alert: F7 screen, push "Test: Mom pressed Help" received, "Alert delivered", "I'm on it", Resolved
- Elder:
  - paired → "You're connected with Samuel" → home (no false nudge on setup day) → "I'm okay" → thank-you → "Done for today"
  - Help countdown → "Your family has been alerted", "Samuel · Alert delivered", "Also call 112"

**Not verified yet:**
- the elder seeing "Samuel is on it" (E10), and "I'm okay now"
- the notification buttons
- a real reminder arriving on the elder's phone at the reminder time

### Day 2 (2026-09-27): S1, Help checks finished ✅
Verified on two emulators, with build 3 (task manager, image manipulator, battery):
- **(a)** The family taps "I'm on it" (from the dashboard's red banner → alert screen). The elder's screen switches to "Samuel is on it" within seconds.
- **(b)** The elder taps "I'm okay now": `POST /v1/device/help/cancel` returns 200, and the family phone gets "Mom is okay now". Tapping that notification opens the alert screen.
- **(c)** Notification buttons: when the app shows the notification itself (app open), "I'm okay" checks in (`POST /v1/device/checkin` 200). Otherwise Android shows Expo's pushes without buttons, so taps open straight to the one-tap screen: the reminder opens the home with "I'm okay", and the Help alert opens the alert with "I'm on it". Decision recorded as D75.
- **(d)** A scheduled reminder, set with `python scripts/demo_state.py schedule --elder "Mary Rayan" --remind-in 1`, arrived on the elder emulator on time.

Fixed along the way:
- A reset day never got its reminder push: notify jobs were deduplicated by elder/day/action. They're now keyed by the engine-action row, with a regression test.
- The UI-dump test helper could read a stale screen. Not app code.

Also added: `scripts/demo_state.py` (dev only). It moves check-in times to now + N minutes (resetting today) and closes leftover alerts. The leftover Help alert from day 1 is closed.

### Day 2 (2026-09-27): S2, photo moments ✅
- **Backend:**
  - pipeline: intent (server time) → PUT file → complete → the worker checks it (file present, real JPEG/PNG/WebP, size limit, thumbnail, perceptual hash) → published | rejected with a reason
  - qualifying per §10: not an elder's post, checked within 24 h, not a near-duplicate of the family's last 90 days; the day comes from the family clock
  - feeds with "new" counts, views, hearts, delete your own, signed links that expire (local media store, D73)
  - new moments push to the family and the elders' phones
  - 399 backend tests pass
- **App:**
  - a persistent upload queue: survives restarts and offline, retries with backoff
  - photos resized (longest side 1600 px) and saved as JPEG before upload
  - Share screen (F3–F6) with Waiting / Sending / Checking / Posted and "Counts for today"
  - "Today's moment" on the dashboard; a moments grid and viewer with hearts
  - elder viewer (E6): one at a time, big Next/Previous, Send love, a camera to share back; the Moments tile shows "N new"; the thank-you screen offers new moments right after "I'm okay"
- **Verified on two emulators:**
  - The family shared a photo while the API was down: "Couldn't send yet. You're offline." Then the app was killed; the queue file kept the item.
  - The API came back and the app relaunched: the queue finished on its own ("posted", qualifies).
  - The dashboard said "Shared at 12:18 PM · counts for today".
  - The elder got "Samuel sent a photo" and the home showed "Moments · 1 new". After "I'm okay", the thank-you screen offered it; the viewer showed it, marked it seen, and Send love worked.
- **Known gaps:**
  - If the API can't be reached **when the family app starts**, it waits on a spinner. It needs `/v1/me`, which isn't cached. An open app is fine offline.
  - Airplane mode can't be tested on emulators: `adb reverse` doesn't use the network.
  - Voice notes and video are next (S3).

### Day 2 (2026-09-27): S3, voice notes ✅
- **Backend:**
  - moments accept `kind: voice` (MP4/AAC `.m4a`, D76)
  - the worker measures each file with ffprobe: not playable → `not_audio`, over 5 minutes → `too_long`, under 10 s → posted but `too_short`
  - the upload limit depends on the kind; `.m4a` is served as `audio/mp4`; the push says "Samuel sent a voice note"
  - tests use real 12 s and 5 s files made with ffmpeg, plus random bytes, a cut-off file and a video; the pure boundary is 9,900 / 9,999 / 10,000 ms
  - 408 backend tests pass
  - `.env.example` now lists the moments settings (it was missing them since S2)
- **App:**
  - Share has Photo | Voice; tap to start, tap to stop (no hold)
  - while recording: timer, live waveform, "from 10 seconds it counts for today"; it stops by itself just under 5 minutes
  - a preview player and "Record again" before sending; the same queue and states as photos
  - voice tiles (length, ✓ when it counts) in the family grid; the sand voice card with a big play/pause (design E5) in the family and elder viewers
- **Verified on two emulators** (the emulators have no microphone input, so recordings are silent; lengths and playback are real):
  - a 12.5 s note posted with "Counts for today" (`duration_ms` 12523) and the dashboard said "Shared at 12:45 PM · counts for today"
  - a 5 s note posted with "Posted. Voice notes count for today from 10 seconds." (`too_short`)
  - the elder phone showed "Moments, 1 new", played the 12 s note from its signed link (pause icon, the waveform filling, 0:04 of 0:12, "From Samuel"), and Send love worked
- **Fixed along the way:**
  - The family moments grid crashed with "Maximum update depth exceeded". Its zustand selector built a new array on every call, which zustand v5 treats as a change every time. This bug dated from S2; the grid wasn't opened then.
  - The "Counts for today" pill on Share is centred.
- **Not done:** video moments. They're first in the cut order, and S4 (billing) matters more for Next Gen.

### Day 2 (2026-09-27): S4, billing core (backend ✅, app ✅, live purchase waiting for keys)
- **Backend** (D77):
  - the `access_grants` ledger and one `evaluate_access`
  - moment credits for D and D+1 on the family clock, granted with the moment's verdict; today's credits backfilled
  - Day Passes and subscription periods only from RevenueCat: the webhook (Authorization header, optional HMAC, each event once) or `POST /access/refresh` (REST v1, secret key)
  - refunds revoke, even when they arrive before the purchase
  - `GET /access` (Plus, why, until when, today's moment, the Day Pass offer) and day-pass eligibility
  - the Plus-gated 30-day check-in history (7 days free)
  - 20 billing tests (Kolkata, New York and Berlin DST days, Santiago's skipped midnight, Chatham); 433 backend tests pass
- **App:**
  - RevenueCat in family mode only (Test Store key in dev builds only); elder screens can't import purchase code (ESLint rule)
  - "See 30 days" on each elder's week strip opens the history
  - without Plus: the 7 free days, and the F8 sheet opens (Share a moment — free, Day Pass, Nodly Plus, Restore)
  - after a purchase: "Confirming…" until the server says Plus is on
- **Checked on the family emulator:**
  - with today's moment credit: "Plus is on · Free today and tomorrow: a moment was shared" and all 30 days
  - with the grant revoked for a minute (dev DB, then restored): the 7 free days, and the sheet opened
- **Fixed:** the history screen looped. The sheet's access query refetched on mount, and the page showed its spinner while fetching, which unmounted the sheet, and so on. The page now waits only for an answer newer than when it opened.
- **Waiting on you:** the RevenueCat project, products and keys. Then: a Test Store Day Pass on the emulator → "Confirming…" → unlocked by the server.

### Found today
- **Hermes on Android has no `Intl.RelativeTimeFormat` (nor `PluralRules`).** "12 minutes ago" is now built from plain strings.
- **An emulator restored from a quick-boot snapshot lost its display:** every app went black and ours reported an ANR ("no focused window"). A cold boot (`-no-snapshot-load`) fixed it. Use cold boots for now.
- **Claude Code stops background tasks when memory runs critically low.** It stopped Metro, the API, the worker and the elder emulator mid-test (Edge was open, about 1.7 GB). Close the browser before emulator sessions.
- **`uiautomator dump` waits until the screen is idle.** While a voice note plays, the UI updates every 250 ms, so the dump only returns after playback ends and shows the finished state. Use screenshots to check anything that moves.
- **The Phase 2 demo elder** (a fake paired phone) is part of the engine too. It got a real missed check-in alert on the family emulator. Only the dev database and your own device are involved.

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
