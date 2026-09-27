# Nodly — build prompts

Use these in order. `CLAUDE.md` must sit in the repo root: it holds every rule, so these prompts stay short.

## How to run each phase

1. In Claude Code, type `/clear` so each phase starts with a clean context.
2. Paste the phase prompt.
3. Read the plan it gives you. Push back if anything looks off, then approve.
4. When it says done, run the **"Done when"** checks yourself. Don't trust "tests pass" without seeing them pass.
5. Commit, then use the **Phase review prompt** (bottom of this file) before moving on.

Claude Design prompts (D1, D2) can run in parallel any time after Phase 3. Their output is needed for Phase 8.

---

## Phase 0 — Manual setup (you, not Claude Code)

**Install on Windows:**
- Git
- Node.js LTS
- Miniforge (conda)
- PostgreSQL
- Android Studio (for the emulator)
- Claude Code
- ffmpeg (Phase 1's SETUP.md will give you the exact command)

**Create accounts now:**
- GitHub (private repo `nodly`)
- Expo (for EAS builds)
- Supabase: create a project called `nodly-dev`
- RevenueCat: create a project and add a **Test Store** app
- Samsung: a Galaxy Store **Seller Portal** account. Apply for **commercial seller** status early, because selling needs it.
- Hardware: a **physical Samsung Galaxy phone**. Galaxy Store test purchases don't work on emulators.

**Create accounts later, when the phase needs them:**
- Apple Developer ($99/yr) — Phase 10
- Google Play Console ($25) — Phase 16
- Anthropic API key — Phase 12
- Twilio — Phase 15

**Then:** make an empty folder `nodly`, put `CLAUDE.md` in it, open PowerShell there, and run `claude`.

---

## Phase 1 — Foundation

```
Read CLAUDE.md fully. We're doing Phase 1 — Foundation. Give me a plan first and wait for my OK.

Scope:
1. Monorepo per CLAUDE.md §3, a proper .gitignore (Python, Node, Expo, Android/iOS build output, .env files), git init.
2. backend/: FastAPI app factory, pydantic-settings config from backend/.env, structured JSON logging with request IDs, consistent error format (problem+json), GET /healthz and GET /readyz (DB ping).
3. Async SQLAlchemy + Alembic (async). First migration with the identity tables only: families, users, family_members, elders, elder_devices, invites, push_tokens, audit_log. Use sensible constraints and indexes. Timezone columns are required with no default. Elder check-in settings get the defaults from §7.
4. DB-backed job queue: jobs table (type, payload, run_at, attempts, status, last_error, idempotency key), enqueue helper, and an async worker loop runnable with `python -m nodly.worker`. Include retries with backoff and a dead-letter state.
5. Services:
   - timezone validation (IANA via zoneinfo), a list of all zones with current UTC offset + readable label, and suggestions from a device timezone or a phone number's country (phonenumbers)
   - ISO-3166 country validation + an emoji flag helper
   - E.164 phone normalisation
6. Dev-only admin router (mounted only when ENV=dev) to create families, users and elders for testing.
7. Tests (pytest + pytest-asyncio, TEST_DATABASE_URL, schema created/dropped per session): health endpoints, key constraints, timezone validation + suggestions (+91, +44, +1, +61), flags, job queue (retry, dead-letter, idempotency key).
8. Tooling: pyproject.toml with [dev] extras, ruff config, backend/.env.example (every variable commented).
9. Docs: docs/SETUP.md with exact PowerShell steps (conda env "nodly" with Python 3.12, PostgreSQL + nodly_dev/nodly_test databases, ffmpeg via winget, migrations, run API, run worker, run tests), docs/PROGRESS.md, docs/DECISIONS.md. mobile/: README placeholder only.

Don't build: auth, pairing, or any feature logic.
Done when: SETUP.md works from a fresh PowerShell, ruff + pytest pass, the API and worker both run, and admin routes work from /docs.
Finish with: what you built, the commands to verify it, and anything I must do by hand.
```

---

## Phase 2 — Auth, families, invites, elder pairing (API)

```
Read CLAUDE.md fully. We're doing Phase 2 — Auth, families, invites, elder pairing (backend only). Plan first, wait for my OK.

Scope:
1. Supabase JWT verification as a FastAPI dependency (JWKS fetch + cache, issuer/audience/expiry checks). GET /me upserts the user on first call and requires display name, country and timezone to finish onboarding.
2. Families:
   - create (caller becomes organizer), rename, list mine, transfer organizer
   - member invites: link + QR payload + short code, single use, 48h expiry
   - accept an invite; remove a member; leave
3. Elders:
   - create a profile: display name, relation label, full name, country, language, REQUIRED timezone, check-in settings
   - update; pause; set primary elder (this defines the family clock)
4. Pairing:
   - create a pairing code (15 min, single use, QR payload)
   - an unauthenticated device claims it and receives a device token (256-bit random, returned once, stored hashed)
   - device-token auth dependency; list/revoke devices; token rotation endpoint
   - brute-force protection on claims
5. Authorization matrix: members only see their families; elder devices only their own elder/family; organizer-only actions enforced. Write table-driven tests for every endpoint × role, including cross-family access attempts.
6. OpenAPI: clean tags and schemas. Add a script that exports openapi.json for the mobile type generator.
7. audit_log entries for membership, pairing and device changes.

Done when: all auth/authz tests pass, and I can run the full flow from /docs with a real Supabase test user: create family → invite member → create elder → pair a fake device → call a device-authenticated endpoint.
```

---

## Phase 3 — Mobile foundation

```
Read CLAUDE.md fully. We're doing Phase 3 — Mobile foundation. Plan first, wait for my OK.

Scope:
1. Create the Expo app in /mobile: latest stable SDK, TypeScript strict, Expo Router, EAS config with a development profile (Android first) plus per-store build profiles `galaxy`, `play`, `ios` as in CLAUDE.md §19 (Galaxy Store first). Name "Nodly", slug "nodly", scheme "nodly". PROPOSE the android.package and ios.bundleIdentifier values but do not set them until I confirm.
2. First launch mode choice, in plain words:
   - "I'm setting Nodly up for someone" → Family mode
   - "Someone set this up for me" → Elder mode
   Elder mode goes to pairing (scan QR or type code). Once paired, the device stays in elder mode; switching away requires re-pairing from family mode or a family PIN.
3. Family auth: Supabase email OTP, session in SecureStore, onboarding for display name, country (searchable picker with flags) and timezone (picker with suggestions — never silently default).
4. API layer: generated TypeScript types from backend openapi.json (openapi-typescript), a typed fetch client, TanStack Query, auth header injection (Supabase JWT or elder device token), consistent error handling, an offline banner.
5. i18n: i18next + expo-localization, every string through t(), English strings file, and an elder language setting.
6. Theme: tokens from CLAUDE.md §15 in mobile/src/theme with elder and family scales, light and dark. Placeholder screens use tokens, but don't spend effort on styling.
7. Push: register Expo push tokens for users and elder devices. Create the Android notification channels now: checkin, moments, help_alerts (max importance), general.
8. Placeholder screens:
   - family: sign-in, onboarding, create family, add elder, pairing QR/code display, members + invites, dashboard stub
   - elder: pairing, home stub with a big "I'm okay" button (not wired yet)
9. docs/SETUP.md: Android emulator, a physical phone, EAS dev build, and reaching the local backend from a device (LAN IP or tunnel).

Done when: on Android I can create a family, add an elder, and show a pairing code; a second emulator/phone pairs as that elder; both keep the right mode after restart; tsc and lint pass. Also run it once on my physical Samsung phone.
```

---

## Phase 4 — Check-ins

```
Read CLAUDE.md fully, especially §7. We're doing Phase 4 — Check-ins. Plan first, wait for my OK.

Backend:
1. Tables checkins + engine_actions (new migration).
2. Endpoints:
   - elder: POST check-in (source: home | widget | notification), POST activity ping (throttled server-side)
   - family: GET today's status per elder, POST resolve, PATCH check-in settings
3. Engine: a worker job ticking every 60s implementing §7 exactly, with engine_actions idempotency and the family clock + DST rules from §5.
4. Push service: Expo push API with batching, receipt checking, invalid-token cleanup, per-channel payloads. The elder reminder includes an "I'm okay" action.
5. Tests: time-travel tests for every §7 branch in America/New_York, Europe/London, Asia/Kolkata and Australia/Sydney, including DST change days; double-tick idempotency; activity_counts_as_ok on/off; tap after escalation → "all good".

Mobile:
6. Elder: the giant "I'm okay" button → instant confirmation (haptic + sound + "Thank you, see you tomorrow"), then a "today's new moments" placeholder.
7. Elder: the notification action checks in WITHOUT opening the app where the platform allows. Verify this on a real Android device. If it isn't reliable, make the action open straight to a one-tap confirm screen, and tell me which path you chose and why.
8. Elder: send activity pings on foreground and key screens.
9. Family: elder status card (✅ time / 🟡 active / not yet / missed) with times in the elder's zone + the viewer's zone, a resolve button, and a check-in settings screen.

Done when: I can simulate a whole day by moving the elder's check-in times close to now, and see reminder → nudge → family alert → tap → "all good" on two devices; all tests pass.
```

---

## Phase 5 — Help & escalation ladder

```
Read CLAUDE.md fully, especially §8. We're doing Phase 5 — Help & escalation ladder. SMS and voice calls are stubbed behind a provider interface (real ones in Phase 15). Plan first, wait for my OK.

Backend:
1. Tables help_requests + help_events.
2. Endpoints:
   - elder: create (urgent | call_me), cancel ("I'm okay now")
   - family: acknowledge ("I'm on it"), resolve with note, list/timeline
   - test alert
3. Ladder as scheduled jobs with every timing in config: T+0 push to all, repeat every 60s to non-acknowledged members (max 15 min), T+2 min SMS step, T+5 min voice step (the provider interface logs "would send" for now). First ack stops the repeats and notifies the others. Live status for the elder device.
4. Emergency numbers: a data file mapping country → local emergency number(s), with its source cited in the file header, plus an endpoint returning the elder's number.
5. Rules: real alerts are never rate-limited or paywalled; test alerts are rate-limited and clearly labelled everywhere.
6. Tests: full ladder timeline with frozen time, ack races (two members ack at once), cancel during the countdown vs after sending, test mode isolation.

Mobile:
7. Elder Help flow: tile → 5s countdown with a huge Cancel → auto-send → live status screen (who's on it), big "Call {family}" buttons, big "Call {emergency number}". Offline fallback after 10s: "No internet — call {primary} now" (tel:) while retrying in the background. One-shot location (permission requested during setup, explained simply) and battery level.
8. Family: urgent notification on the help_alerts channel with "I'm on it" / "Call" actions; an in-app alert screen (elder, time, map link, battery, last check-in, who's handling it); resolve with note; a history timeline.
9. Android: onboarding step to let help alerts bypass Do Not Disturb (notification policy access), with plain explanations and a "send test alert" button.
10. iOS prep: mark help notifications time-sensitive, and document in docs/DECISIONS.md how we'll request the Critical Alerts entitlement later.

Done when: on two Android devices, pressing Help rings the family phone even in Do Not Disturb (after granting access), "I'm on it" updates the elder's screen within seconds, and all ladder tests pass.
```

---

## Phase 6 — Moments

```
Read CLAUDE.md fully, especially §9 and the qualifying rules in §10. We're doing Phase 6 — Moments. Plan first, wait for my OK.

Backend:
1. Tables moments, moment_views, moment_reactions. A private Supabase Storage bucket.
2. Pipeline:
   - POST intent → server timestamp + resumable upload target
   - client uploads
   - POST complete → a worker job verifies (object exists, MIME, size, ffprobe duration, perceptual-hash near-duplicate check against the family's last 90 days of photos, thumbnail/poster via ffmpeg) → published | rejected with a human-readable reason
   Every step idempotent.
3. Qualification: compute `qualifies` + `qualifying_local_date` (family clock, from the intent timestamp, verified within 24h) exactly per §10. This phase only records it; Phase 7 turns it into access.
4. Endpoints:
   - family feed and elder feed (paginated)
   - "new" counts per viewer; mark viewed
   - heart toggle (behind the feature flag)
   - delete own moment
   - short-lived signed view URLs
5. Tests: happy paths per kind, duration thresholds (4.9s vs 5.0s video, 9.9s vs 10s voice), near-duplicate rejection for qualification (still posted), late completion (23h vs 25h), double "complete", elder posts never qualify.

Mobile:
6. Family: post a photo/video/voice recording (camera, gallery, recorder), client-side compression, and a persistent upload queue that survives app restarts and offline periods with automatic retries.
   - Visible states: Queued → Uploading → Checking → Posted
   - "Counts for today ✓" chip
   - Clear, friendly rejection reasons
   - A "Today's moment" indicator with time left on the family clock
7. Family feed (grid + viewer) with hearts.
8. Elder viewer: one item at a time, huge Next/Previous buttons (no swipe-only), big video play/unmute, giant voice-note play. After an "I'm okay" tap, go straight to today's new moments. Elder big camera button to post.

Done when: I can post all three kinds from family mode on a flaky network (toggle airplane mode mid-upload) and they all finish; the elder sees them after checking in; the tests pass.
```

---

## Phase 7 — Nodly Plus & billing

```
Read CLAUDE.md fully, especially §10. This is the money phase: correctness over speed. Plan first, wait for my OK. Include in your plan the exact RevenueCat products, entitlement and webhook events you'll handle, with links to the RevenueCat docs you checked.

Backend:
1. Tables purchases (unique RevenueCat event id + transaction id), access_grants (ledger), billing_incidents.
2. ONE access evaluation function used everywhere (family API, elder API, feature gates). GET /access returns: has_plus, sources, current window end, and today's moment status on the family clock.
3. Moment credits: when a moment becomes qualifying, create a grant covering day D + D+1 (family clock). Idempotent per family + day.
4. RevenueCat webhook endpoint (verify the authorization header secret):
   - Day Pass grant ONLY on NON_RENEWING_PURCHASE for the day_pass product: 24h from the purchase time
   - subscription grants mirrored from purchase/renewal/expiration/cancellation events
   - refunds (CANCELLATION with a refund reason) revoke the matching grant
   - all idempotent
5. POST /access/refresh: if the webhook hasn't arrived, verify the purchase via the RevenueCat REST API and apply the same idempotent grant.
6. GET /access/day-pass-eligibility: blocks when the family already has Plus or has a pending upload that would qualify today (with the reason).
7. Overlap detector job (§10): open billing_incidents, auto-compensate with goodwill grants, and refund via RevenueCat where the store allows it (confirm the endpoint in the docs first; if unsure, leave the refund as a manual step and tell me). Log everything.
8. GET billing timeline for the family (grants, purchases, incidents in plain language) and POST "report a problem" (store + email me).
9. Feature gates for the Plus features listed in §10, enforced server-side.
10. Tests — table-driven and exhaustive:
    - access at day boundaries in 4 timezones incl. DST days
    - moment + Day Pass overlap
    - duplicate and out-of-order webhooks
    - refund after use
    - subscription lapse
    - webhook late → refresh path
    - an elder device can never trigger a purchase

Mobile:
11. RevenueCat SDK with the Test Store key (dev only), app user id = Supabase user id, and our family id sent as a subscriber attribute.
    Galaxy Store build profile: react-native-purchases ≥ 10.3.0 + react-native-purchases-store-galaxy, `store: "GALAXY"`, the Galaxy public key, GALAXY_BILLING_MODE.TEST for test builds (production mode only for beta/production). Confirm in the RevenueCat docs how Galaxy purchases appear in webhooks (store field, event types) and handle them with the same grant rules. Check what refund options exist for Galaxy Store and apply the CLAUDE.md §10 fallback if developer refunds aren't possible.
12. Locked-feature sheet (family only): "Share a moment — free" (primary, opens the camera) · "Day Pass" · "Nodly Plus", plus restore purchases and manage subscription. After a purchase: show "Confirming…", poll /access, never unlock client-side.
13. Elder: locked Plus features show the kind message from §10 and trigger the rate-limited family nudge. No purchase UI can ever render in elder mode — add a test/assertion for this.
14. Family: "Plus & billing" screen with the timeline and "Report a problem".

Done when: with the Test Store I can buy a Day Pass and a subscription and see /access flip only after the webhook/refresh; posting a qualifying moment grants the day; the overlap scenario creates an incident + goodwill grant; all billing tests pass. Then repeat the Day Pass + subscription purchase on my physical Samsung phone with a Galaxy Store test build (GALAXY_BILLING_MODE.TEST), once Seller Portal products exist.
```

---

## D1 — Claude Design: Elder mode (paste into Claude Design)

Attach `CLAUDE.md` (or paste §1, §7–§9, §11–§15). If you have a colour reference image, attach it too.

```
Design the ELDER MODE of a mobile app called Nodly — "A daily nod that says I'm okay." Users are older adults (70–90) worldwide, often with weaker eyesight, less steady hands, and little tech confidence. The attached brief has the full product rules; follow its design system section exactly (palette tokens, contrast, sizes).

Principles: calm, warm, dignified, never childish. Warm paper background, no pure white or pure black. Body text ≥ 20pt, titles 28–34pt, primary buttons ≥ 64pt tall and full width, max 6 tiles per screen, every icon has a text label, no swipe-only or long-press-only actions, generous spacing, obvious "back". Show both light and warm-dark versions.

Screens (phone frames, include every state):
1. Pairing: scan QR / type code; the presence-consent question in plain words.
2. Home (Android launcher version + iOS app version): giant "I'm okay" (states: not yet / done ✅ with time), tiles for Moments (new count badge), Music, Recipes, Help, Phone, Camera, favourite apps row, "All apps".
3. After "I'm okay": thank-you moment → "3 new from your family" → moments viewer.
4. Moments viewer: photo, video (big play/unmute), voice recording (giant play), huge Next/Previous, heart button, big camera button to post.
5. Help: countdown with huge Cancel → sent status ("Priya is on it") → call buttons, local emergency number, "I'm okay now"; offline variant.
6. Music: now playing with big artwork and controls, "Play my music", locked state ("Music is resting today…"), notification-access setup explained simply.
7. Recipes: browse (Top rated / New / By country / My family), recipe detail (big text, read-aloud button, byline with country flag and "with help from…"), approve-a-helper's-recipe screen (big Yes/No).
8. Voice recipe assistant: record, "listening", read-back confirmation one ingredient/step per card with ✔ Correct / ✏ Fix.
9. Settings: text size, language, dark mode, "let my family see when I'm on Nodly".
10. Widgets: "I'm okay" (small + medium, both states) and family photo frame.

Also deliver: a component sheet (buttons, tiles, cards, badges, dialogs) and the final token list with contrast ratios.

Samsung Galaxy optimisation (the app launches on the Galaxy Store first): also show the Home, Moments viewer, Help and Music screens on a Galaxy Z Fold inner screen, the Z Fold cover screen, a Z Flip, and in split-screen. Elder minimum sizes still apply everywhere.
```

## D2 — Claude Design: Family mode (paste into Claude Design)

```
Using the same design system as the elder mode we just designed, design the FAMILY MODE of Nodly for adult children and relatives (standard text sizes, same warm palette, calm tone; the Help red is reserved for real Help alerts).

Screens (include empty, loading, error states):
1. Sign-in (email code), onboarding (name, country with flag, timezone picker with suggestions — never an assumed default).
2. Create family, add elder (with timezone + country pickers), show pairing QR/code, members & invites.
3. Dashboard: elder cards — check-in status (✅ time / 🟡 active / not yet / missed), live activity ("On Nodly now · listening to music"), last seen, times shown as "7:12 AM Mom's time · 9:42 PM yours", Plus status, "Today's moment" progress with time left on the family clock.
4. Post a moment: camera / gallery / voice recorder; upload states Queued → Uploading → Checking → Posted; "Counts for today ✓" chip; friendly rejection reasons.
5. Family feed (grid + viewer) with hearts. No text messaging anywhere.
6. Locked-feature sheet: "Share a moment — free" (primary) · Day Pass · Nodly Plus; "Confirming…" state; Plus & billing screen with a plain-language timeline and "Report a problem".
7. Help alert: urgent full-screen alert (elder, time, map, battery, last check-in) with "I'm on it" / "Call"; "Priya is handling it" state; resolve with note; history timeline.
8. Missed check-in alert + resolve ("I've talked to her").
9. Recipes: help write a recipe for an elder (helper name + optional flag, byline preview), "waiting for Mom's approval" state.
10. Settings: check-in times, notification test, Do-Not-Disturb override setup, music app preference for the elder, launcher favourites, family PIN.
11. Widgets: elder status (✅ / not yet / HELP active), small + medium.

Deliver a component sheet and confirm the tokens are shared with elder mode.

Samsung Galaxy optimisation: also show the Dashboard, Post a moment, Help alert and feed screens on a Galaxy Z Fold inner screen (use the extra width, e.g. list + detail side by side), the cover screen, and in split-screen.
```

When you're happy with both, use **Hand off to Claude Code**, save the bundles into `/design/<date>-elder` and `/design/<date>-family`, then run Phase 8.

---

## Phase 8 — Implement the Claude Design screens

```
Read CLAUDE.md fully, especially §15. We're doing Phase 8 — implementing the Claude Design handoff bundles in /design into React Native. Plan first, wait for my OK. The plan should include a screen-by-screen mapping from the bundle files to our routes.

Rules:
1. The bundles are HTML/CSS reference. Rebuild them natively; never use WebViews.
2. Update mobile/src/theme from the bundle's final tokens. Keep the contrast rules and report any token that breaks them.
3. Build a shared component library first (buttons, tiles, cards, badges, sheets, dialogs, pickers, upload-state chips) with accessibility labels, roles, hit slop, and font-scaling support. Elder components enforce the minimum sizes.
4. Then implement the screens mode by mode, wiring them to the existing hooks and APIs. Don't change backend behaviour. If a design needs data we don't have, list it rather than inventing it.
5. Verify on an Android phone at the largest system font size and in dark mode, and list anything that clips or overflows.
6. Galaxy optimisation (CLAUDE.md §15 / §19): implement the foldable and split-screen layouts from the designs, and make sure screen state survives fold/unfold and resizing. Test on Android Studio's foldable emulator and on my Samsung phone in split-screen and pop-up view.

Done when: every screen from D1/D2 exists and is wired, tsc + lint pass, and you've given me a checklist of screens with any deviations from the design and why.
```

---

## Phase 9 — Android home launcher + Android widgets

```
Read CLAUDE.md fully, especially §14. We're doing Phase 9 — Android launcher mode and Android widgets. Plan first, wait for my OK.

Launcher (local Expo module "nodly-launcher", Kotlin, Expo Modules API):
1. An activity-alias with the HOME category, enabled only in elder mode and disabled when leaving it. Open the system "default home app" screen with simple guidance.
2. List launchable apps (label, package, icon cached as PNG) using <queries> for launcher activities — no QUERY_ALL_PACKAGES. Launch an app by package.
3. Elder home as launcher: tiles + up to 6 favourite apps chosen by the family (synced from the backend) + an "All apps" list with big rows.
4. Leaving launcher mode: family PIN (set in family mode, stored hashed) or a deliberate long-press + confirm. Never trap the elder.
5. A "Keep Nodly awake" guidance screen with per-brand battery-optimisation steps (Xiaomi, Samsung, Oppo, Vivo, OnePlus…) and a "Nodly is working ✓" self-test. Don't use restricted permissions that Play policy disallows for our use case — check the policy and tell me what you chose. Samsung One UI first (Galaxy-first): its default-home-app flow and its battery settings (e.g. the "never sleeping apps" list) get tested on my Samsung phone before other brands.

Widgets (react-native-android-widget):
6. Elder "I'm okay" widget: tap → check-in via the API with the device token → widget updates to ✅. Handle offline (queue and retry, show "saving…").
7. Elder photo-frame widget (latest moment thumbnail, cached locally).
8. Family elder-status widget (✅ time / not yet / HELP active).
9. Refresh on relevant pushes, on app changes, and periodically as backup.

Done when: on a physical Android phone Nodly works as the home app, the widgets check in and update correctly, and it survives a reboot + a day of normal use; you've documented the results of testing on any brand-specific phone I have.
```

---

## Phase 10 — iOS builds + iOS widgets

*Ships after the Galaxy Store launch (release order in CLAUDE.md §19). You can build it whenever you're ready; nothing in it changes.*

```
Read CLAUDE.md fully. We're doing Phase 10 — iOS. I now have an Apple Developer account. Plan first, wait for my OK.

1. Walk me step by step through what I must do in the Apple Developer portal / App Store Connect, and what EAS does for me: bundle id, APNs key for push, device registration for internal builds, TestFlight. Give me the exact EAS commands for PowerShell.
2. iOS notifications: the time-sensitive capability; help alerts marked time-sensitive; a written guide in docs/ on applying for the Critical Alerts entitlement, with the code path behind a flag ready for when it's approved.
3. iOS elder experience: no launcher. Onboarding that helps the family add the Nodly widget + Lock Screen widget and turn on notifications.
4. expo-widgets: elder "I'm okay" widget (interactive, iOS 17+), photo frame, family elder-status widget.
   - FIRST check the expo-widgets docs on how interactive actions execute. If a network call can't run from the widget, record the tap in shared storage and sync it on the next app/background run.
   - If that isn't reliable enough for a safety check-in, make the widget button deep-link into a one-tap check-in screen instead. Tell me which you chose and why.
5. Sign-in and all existing flows verified on an iPhone via a development build.

Done when: an iPhone dev build runs both modes, pushes arrive (help alerts as time-sensitive), and the widgets show correct state; docs updated.
```

---

## Phase 11 — Music hub

```
Read CLAUDE.md fully, especially §12. We're doing Phase 11 — Music (a Plus feature). Plan first, wait for my OK.

Android (local Expo module "nodly-media", Kotlin):
1. A NotificationListenerService declaration + a plain-language onboarding to grant notification access (the family helps during setup).
2. Active media sessions via MediaSessionManager: pick the preferred app's session, or the most recently active. Stream metadata (title, artist, artwork) and playback state to JS. Transport controls: play/pause/next/previous.
3. "Play my music": resume the preferred app via a media-button intent without opening its UI. Report per-app success, since behaviour varies.
4. List installed media apps (media-browser services + music-category apps) so the family can choose the preferred one. Try MediaBrowser browsing where the app allows it; degrade gracefully.
5. Test with Samsung Music first (Galaxy-first), then Spotify, YouTube Music, and one more app. Record what works in docs/DECISIONS.md.

iOS (local Swift module, after Phase 10):
6. Apple Music via MusicKit: authorisation, recently played + library playlists, play/pause/skip, now playing. Explain to me what must be enabled on the App ID.
7. Other iOS music apps: a kind "Open {app}" fallback.

Shared:
8. Elder music screen per the designs, Plus gating with the kind locked state, and emitting a "listening" activity event for Phase 14.

Done when: on my Android phone I can start, pause and skip Spotify from inside Nodly without Spotify's UI opening, and see the artwork; iOS is either done or clearly deferred with notes.
```

---

## Phase 12 — Recipes (Nodly Kitchen)

```
Read CLAUDE.md fully, especially §11. We're doing Phase 12 — Recipes, without the voice assistant (that's Phase 13). I'm adding ANTHROPIC_API_KEY to backend/.env. Plan first, wait for my OK.

Backend:
1. Tables: recipes, recipe_ingredients, recipe_steps, recipe_photos, recipe_translations, recipe_ratings, reports, blocks.
2. Compose:
   - an elder creates by typing
   - a helper (family member) creates on the elder's behalf, with helper_name (free text) + optional helper country
   - byline style (full / first + last initial / first only)
   - elder approval is REQUIRED before public (state machine: draft → pending_elder_approval → published / unpublished / removed)
3. Ratings: 1–5, one per account, and the author's family's ratings excluded from the public score (shown as "Loved by family"). A Bayesian ranking job with the prior in config.
4. Feeds: Top rated, New, By country, My family (paginated), with block filtering.
5. Moderation: an AI pre-check of text + photos with the Anthropic API before publishing (auto-hold if flagged, with the reason stored); report + block endpoints; a small protected admin review page served by FastAPI (admin role).
6. Translation on demand via the Anthropic API, cached per language, keeping the original.
7. Units: store quantity + unit; a conversion helper for the metric/imperial display toggle (never convert things like "a pinch").
8. A public read-only web page per public recipe (/r/{slug}, server-rendered, Open Graph tags, byline + flag only, no family data) with an "Open in Nodly" link.
9. Tests: approval gating, family-rating exclusion, ranking maths, byline formatting incl. helper + flags, moderation holds, block filtering, unit conversion.

Mobile:
10. Elder: browse tabs, recipe detail with large text + read-aloud (text-to-speech), approve/decline a helper's recipe, simple typing composer with huge inputs.
11. Family: the helper composer with byline preview, "waiting for approval" state, ratings, report/block.

Done when: a helper-written recipe needs the elder's approval, then appears in Top rated with the right byline and flags; ratings from the elder's own family don't move the public score; flagged content is held; tests pass.
```

---

## Phase 13 — AI voice recipe assistant

```
Read CLAUDE.md fully. We're doing Phase 13 — the AI voice recipe assistant (Plus). Accuracy is the whole point, so we measure it. Plan first, wait for my OK.

1. Speech-to-text behind a provider interface. Implement TWO options:
   (a) a multilingual cloud STT API (propose 1–2 candidates with pricing + language coverage, then ask me)
   (b) on-device platform speech recognition as a fallback (check a maintained Expo-compatible library's health before adding it)
2. An evaluation harness in backend/eval/: I'll record 10+ test clips (older voices, accents, at least 3 languages, kitchen noise). It reports word error rate per provider/language and ingredient-quantity accuracy. Pick the default from the data and write the results to docs/DECISIONS.md.
3. Structuring: Claude turns the transcript into our recipe schema via strict JSON, with per-field confidence and needs_check flags on quantities, units, times and temperatures. RULE: never invent anything — unmentioned fields stay empty. Keep the original language; translation is separate.
4. Mobile elder flow: one big "Start talking" button (tap to start, tap to stop — no hold), live "listening" feedback, then a read-back confirmation with one ingredient/step per card, ✔ Correct / ✏ Fix (re-record just that item or type it), and optional text-to-speech read-back. "Ask my family to finish" hands the draft to the helper flow.
5. Privacy: audio + transcripts kept 30 days for corrections, then deleted by a job; say so in the UI.
6. Metrics: log how often users correct each field type so we can improve prompts.
7. Optional sub-step (ask me first): an iOS App Shortcut / Android shortcut "New recipe in Nodly" that opens the recorder.

Done when: the eval report exists, the chosen provider meets the targets we agree on, and I can dictate a full recipe on my phone and publish it after confirmation.
```

---

## Phase 14 — Presence & live activity

```
Read CLAUDE.md fully, especially §13. We're doing Phase 14 — Presence (viewing is Plus). Plan first, wait for my OK.

1. The elder device sends presence/activity updates to the backend (throttled): on Nodly / viewing moments / listening to music (+ track title only if the elder allowed it) / writing a recipe / checked in; plus offline → last seen.
2. The backend is the ONLY publisher: it stores the latest state per elder (no history beyond 24h) and broadcasts to a private Supabase Realtime channel per family. Only family members with Plus can subscribe (authorise it properly — show me the channel authorisation setup).
3. Elder consent enforced server-side (no consent = nothing is stored or broadcast). The elder settings toggle takes effect immediately.
4. Family UI: live line on the elder card ("On Nodly now · Listening to music"), last seen, and a locked state for non-Plus.
5. Tests: consent off, Plus off, stale presence expiry, a non-member trying to subscribe.

Done when: on two devices I see the elder's activity change within a few seconds, and turning consent off stops it immediately.
```

---

## Phase 15 — SMS/voice escalation + alert reliability

```
Read CLAUDE.md fully, especially §8. We're doing Phase 15 — the real SMS + voice steps of the Help ladder via Twilio, plus reliability checks. I'm adding Twilio credentials to backend/.env. Plan first, wait for my OK.

1. The Twilio provider implementing our interface: SMS at T+2 min, a voice call at T+5 min (TwiML message: "{elder} pressed Help in Nodly. Press 1 if you're handling it" → pressing 1 acknowledges the request via a webhook, with signature validation).
2. Phone numbers: verify family members' numbers (OTP) before use. Backup contacts (people without the app): name + phone, and they must opt in by replying YES to a confirmation SMS.
3. Country realities: summarise which countries need sender registration (e.g. US A2P, India DLT) and what that means for us. Start with the countries I pick; everything else falls back to push only, clearly shown in the UI.
4. Cost controls: only real alerts use SMS/voice; test alerts may send one test SMS per month per family.
5. Reliability: a per-device test-alert report (delivered / acknowledged) in family settings, Expo push receipt monitoring with alerts to me on failures, and a DND-override check on Android.
6. Tests for the full ladder with the Twilio provider mocked, including webhook acknowledgements.

Done when: a real Help test (my phone as the family, notifications silenced) ends with an SMS and then a call I can acknowledge by pressing 1.
```

---

## Phase 16 — Launch hardening

```
Read CLAUDE.md fully. We're doing Phase 16 — launch hardening. Plan first, wait for my OK. Split the work into small steps and pause after each.

1. Account deletion in-app: family member; elder profile by the organizer; family dissolution. Purge jobs cover storage objects too. Data export (JSON + media links).
2. Draft a privacy policy + terms (clearly marked as drafts for legal review): not an emergency service, data we collect, retention, Day Pass and subscription terms per store policies.
3. Security pass:
   - authz tests for every endpoint
   - signed URL lifetimes; token hashing/rotation; webhook authentication (RevenueCat, Twilio)
   - rate limits; secrets audit; dependency audit
4. Monitoring: Sentry for mobile + backend, structured logs, health alerts, DB backups.
5. Deploy: propose a host for the API + worker (Render / Railway / Fly) with costs and ask me. Set up a Supabase production project, migrations in CI, and environment separation.
6. Production builds: EAS production profiles, RevenueCat production API keys (remove the Test Store key and add a CI check that fails if it's present), store products (plus_monthly, plus_annual, day_pass) — tell me exactly what to create in Samsung Seller Portal (first — Galaxy Store release), Play Console, and App Store Connect. The Galaxy Store build uses production Galaxy billing mode and the Galaxy RevenueCat key.
7. Store listings: a checklist for screenshots, Google data safety, Apple privacy labels, content rating, UGC compliance notes (report/block/contact), and US availability for Shipaton.
8. Galaxy Store release (first): a Seller Portal listing checklist (polished metadata, assets, US availability, the "Samsung Galaxy phones only for now" note), Samsung IAP products live, a production purchase test, and a written "How Nodly is optimised for Galaxy" description for the Shipaton submission (foldables, split-screen/pop-up view, Samsung Music, One UI launcher + battery handling).

Done when: a production build installs from the Galaxy Store (first), TestFlight / a Play internal test track, a real purchase unlocks Plus via production RevenueCat, and the launch checklist in docs/ is all ticked or explicitly deferred.
```

---

## Extra prompts you'll reuse

**Phase review (after every phase):**
```
Review the phase we just finished against CLAUDE.md and that phase's "Done when". List: anything missing, any rule from CLAUDE.md that's violated, untested edge cases, and risky shortcuts. Don't fix anything yet — give me the list ranked by severity.
```

**Bug fix:**
```
Bug: <what happened> / Expected: <what should happen> / Steps: <how to reproduce> / Logs: <paste>.
Reproduce it first (write a failing test if possible), find the root cause, fix it, and show me the test passing. Don't touch unrelated code.
```

**Resume after a break:**
```
Read CLAUDE.md and docs/PROGRESS.md. Tell me where we are, what's half-done, and what you'd do next. Don't change anything yet.
```
