# Nodly — project brief for Claude Code

**Nodly — "A daily nod that says I'm okay."**
The home app for older adults, and the family app for the people who love them.
Keep the display name in ONE constant per side (`APP_NAME`).

---

## 1. Product in one screen

ONE app, TWO modes (chosen at first launch):

- **Elder mode** (older adult): a calm home screen with a giant **"I'm okay"** button, family photos/videos/voice recordings, music, recipes, and a **Help** button. On Android it can be set as the phone's **home app (launcher)**. On iOS it's a normal app plus widgets.
- **Family mode** (adult children, relatives): see check-ins and live activity, get alerts, share **moments** (photos, videos, voice recordings — **no text messages**), help elders publish recipes, manage the family, pay.

**Core loop:** elder picks up phone → Nodly home → taps "I'm okay" → is rewarded with today's new family moments. Family sees ✅. Posting one moment a day keeps **Nodly Plus** free for the family.

### Non-negotiable principles
1. **Safety is never paywalled:** check-in, reminders, Help, alerts, the family moments feed.
2. **Elders never see a paywall** or any purchase UI.
3. **Not an emergency service.** Say so plainly; always show the local emergency number on Help screens.
4. **Dignity & consent:** elders consent to presence sharing and must approve any recipe before it goes public.
5. **International by default:** no country defaults, user-picked IANA timezones, i18n from day 1, country flags, metric/imperial.
6. **Money must be exact:** the server is the only judge of access; every grant/charge is idempotent, auditable and tested.
7. **No text messaging** between users. Moments + (optional) heart reactions only.

---

## 2. Platform realities (design around these, don't fight them)

- **Android:** launcher mode, universal music control through MediaSession (needs notification access), interactive widgets, notification channels.
- **iOS:** no custom launcher; cannot control other apps' playback; **Apple Music only via MusicKit**; interactive widgets via `expo-widgets` (iOS 17+).
- **Spotify:** its developer program caps new apps at 5 allow-listed users and only grants wider access to registered businesses with 250k+ MAU. → **No Spotify SDK / Web API.** On Android, Spotify is controlled through the universal media controller like any other music app.
- **Payments:** only **user-initiated** in-app purchases through RevenueCat. **No automatic penalty charges.** App Store refunds are decided by Apple; Google Play purchases can be refunded via RevenueCat.
- **Siri / Google Assistant** cannot be used as our dictation engine → voice capture happens in-app. Siri Shortcuts / Android App Actions may later *launch* flows only.
- **Public recipes are user-generated content** → must have filtering, reporting, blocking and a published contact (App Store guideline 1.2).
- App Store requires **in-app account deletion**.
- **Dev machine is Windows** → Android first. iOS builds go through EAS cloud and need an Apple Developer account (Phase 10+).
- **Distribution is Galaxy Store first** (then Google Play, then the App Store) — see §19. The Galaxy Store only exists on Samsung Galaxy phones, so until the Google Play release both elders and family members need Samsung phones. Galaxy Store test purchases only work on a **physical** Galaxy device signed in to a Samsung account — not on emulators.

---

## 3. Repo layout

```
/backend            FastAPI service, worker, migrations, tests
/mobile             Expo app (both modes)
/mobile/modules     Local Expo native modules (Kotlin/Swift): launcher, media, etc.
/docs               SETUP.md, PROGRESS.md, DECISIONS.md, API notes
/design             Claude Design handoff bundles (reference only)
```

---

## 4. Stack (locked — ask before adding anything else)

**Backend:** Python 3.12, FastAPI, SQLAlchemy 2.x async + asyncpg, Alembic (async), Pydantic v2 + pydantic-settings, httpx, `phonenumbers`, Pillow + `imagehash`, ffmpeg/ffprobe (system binaries), pytest + pytest-asyncio + time-machine, ruff.
Background work: a **DB-backed job queue** (jobs table + async worker loop, `python -m nodly.worker`). No Redis/Celery for now.

**Supabase:** Auth (family members), Storage (private buckets, resumable uploads), Realtime (presence). Postgres for the backend is local in dev/tests and Supabase-hosted in staging/prod.

**Mobile:** Expo (latest stable SDK), TypeScript strict, Expo Router, TanStack Query, Zustand (small client state), i18next + expo-localization, expo-secure-store, expo-notifications, expo-camera / expo-image-picker, the current recommended Expo audio/video packages, react-native-purchases (≥ 10.3.0) + react-native-purchases-ui + react-native-purchases-store-galaxy (Galaxy Store builds), `expo-widgets` (iOS), `react-native-android-widget` (Android), Expo Modules API for native code. **EAS development builds** only (Expo Go can't run our native modules or real purchases).

**AI (Phase 12+):** Anthropic API (recipe structuring, translation, moderation incl. images). Speech-to-text behind a provider interface.

**Escalation fallback (Phase 15):** Twilio SMS + voice.

API types: generate TypeScript types from the backend OpenAPI schema (openapi-typescript) — never hand-write API types in the app.

---

## 5. Identity, families, time

- **Family member accounts:** Supabase Auth, email OTP to start. Account holders must be **16+**. (If Google sign-in is added later, Sign in with Apple must be added too.)
- **Elders have no login.** A family member creates the elder profile → shows a pairing QR/code → the elder's phone claims it → receives a long-lived **device token** (random 256-bit, stored in SecureStore, **hashed** server-side, revocable).
- **Family roles:** `organizer` (created it, manages billing; transferable), `member`, plus 1+ **elders**.
- **Invites:** link / QR / short code, single use, 48h expiry (pairing codes: 15 min).
- **Timezones:** every user and elder has a **required, user-picked IANA timezone**. We only *suggest* (device timezone, phone-number country). Never default to any country.
- **Family clock:** the primary elder's timezone. "Today" for check-ins and billing is always the family-clock day.
- **Countries:** ISO-3166 alpha-2 codes; flags rendered as emoji from the code.
- **DST:** all local-time maths via `zoneinfo`. A local time that doesn't exist (spring-forward) moves to the next valid minute; an ambiguous one (fall-back) uses the first occurrence (`fold=0`). Local days can be 23 or 25 hours — always key on local dates, never on rolling 24h windows (except where a rule explicitly says "24 hours").
- **Display rule:** show times in the elder's local time with a zone label, plus the viewer's own time when different ("7:12 AM Mom's time · 9:42 PM yours").

---

## 6. Domain model (summary — each phase adds its own tables via new migrations)

- Identity: `families`, `users`, `family_members`, `elders`, `elder_devices`, `invites`, `push_tokens`, `audit_log`
- Check-ins: `checkins` (unique elder_id + local_date), `engine_actions` (idempotency ledger, unique elder_id + local_date + action)
- Help: `help_requests`, `help_events`
- Moments: `moments`, `moment_views`, `moment_reactions`
- Billing: `purchases` (unique RevenueCat event id), `access_grants` (the ledger), `billing_incidents`
- Recipes: `recipes`, `recipe_ingredients`, `recipe_steps`, `recipe_photos`, `recipe_translations`, `recipe_ratings`, `recipe_voice_drafts`
- Safety/UGC: `reports`, `blocks`
- Elder settings: launcher favourites, preferred music app, presence consent (columns or small tables)
- `jobs` (queue)

All timestamps UTC. Soft-delete where users can delete content; hard-delete on account deletion.

---

## 7. Check-in rules

Per elder: `remind_at` (default 09:00 local), `due_by` (default 12:00), `grace_minutes` (default 60), `activity_counts_as_ok` (default true). Family can edit.

Signals:
- **TAP** — the home "I'm okay" button, the widget button, or the notification action → **Checked in ✅**
- **ACTIVITY** — using Nodly (launcher use, viewing moments, music, recipes) → **Active 🟡**

Engine:
1. At `remind_at`: no TAP yet → push a reminder to the elder's device with an **"I'm okay"** action button.
2. At `due_by`: TAP → nothing. ACTIVITY and `activity_counts_as_ok` → no alert (family sees "Active, didn't tap"). Otherwise → second reminder to the elder + normal push to family: "{name} hasn't checked in yet."
3. At `due_by + grace`: still nothing → **missed check-in alert** to all family members (high priority, but NOT the Help ladder). Any member can resolve: "I've talked to her."
4. A TAP at any time → auto-resolve + "All good — {name} checked in" to anyone who was alerted.
5. After tapping, the elder immediately sees today's **new moments** (the reward loop).

Implementation: one worker tick every 60s queries for due work; every action goes through `engine_actions`, so re-running a tick is always safe. Pure decision logic is a function that's unit-tested with frozen time across DST zones.

---

## 8. Help (emergency) rules

**Elder side**
- Help tile → full-screen **5-second countdown** with a huge **Cancel** → then sends **automatically**, so an elder who can't tap again still gets help. Same screen offers a non-urgent **"Please call me"**.
- Payload: server time, elder local time, one-shot location (if permission was granted during setup), battery %, last check-in, network type.
- After sending: live status ("Sent to Priya, Arjun… ✓ Priya is calling you"), big **Call {family}** buttons, and a big **Call {local emergency number}** button (by elder's country; keep a sourced data file).
- No internet within 10s → "No internet — call {primary contact} now" (tel:) while retrying in the background.
- "I'm okay now" cancels an open request and notifies the family.

**Family side — escalation ladder (all timings in config)**
- **T+0:** urgent push to every family member (Android `help_alerts` channel: max importance, alarm-style sound, can bypass Do Not Disturb if the user granted it; iOS: time-sensitive now, Critical Alerts once Apple approves the entitlement). Actions: **"I'm on it"**, **"Call {name}"**.
- **Every 60s:** repeat to members who haven't acknowledged, until someone does (max 15 min).
- **T+2 min, no ack:** SMS to all members + backup contacts (Phase 15).
- **T+5 min, no ack:** automated voice call to the organizer and primary contacts (Phase 15).
- The first "I'm on it" stops the repeats; others get "{responder} is handling it"; the elder's screen updates live.
- Resolve with an optional note. Full timeline kept in `help_events`.
- **Test mode:** family can send a clearly labelled test alert to check every device (recommend monthly). Only test alerts are rate-limited.

---

## 9. Moments rules

- Kinds: **photo**, **video**, **voice recording**. No captions, no text.
- Family-only and private. Viewing uses short-lived signed URLs.
- Anyone in the family can post, including elders (a big camera button).
- Optional **heart** reaction (feature flag `REACTIONS_ENABLED`, default on).
- Limits (config): video free ≤ 60s, Plus ≤ 3 min; voice ≤ 5 min.
- **Pipeline:** create an *intent* (server timestamp) → resumable upload to private storage (client-side compression, persistent offline queue, automatic retries) → *complete* → a worker verifies (object exists, MIME, size, duration via ffprobe, photo perceptual-hash dedupe, thumbnail/poster via ffmpeg) → `published` or `rejected` with a human-readable reason.
- UI states, always visible: **Queued → Uploading → Checking → Posted**, plus a **"Counts for today ✓"** chip when it qualifies (§10).
- Elder viewer: one item at a time, huge next/previous buttons (no swipe-only navigation), videos with big play/unmute, voice notes with a giant play button. "New" counts per viewer via `moment_views`.

---

## 10. Nodly Plus & billing rules (the part that must be perfect)

**Free, always:** check-ins and reminders, Help and escalation, elder home/launcher, family moments (view, post, hearts), recipes (browse, rate, publish manually or with a helper), basic widgets, up to 6 family members.

**Plus (family-wide):** music hub, AI voice recipe assistant, live activity status, check-in history beyond 7 days, longer videos, family members beyond 6. Values in config.

**A family has Plus at time _t_ if any non-revoked `access_grant` covers _t_.** Sources:

1. **Moment credit (free):** a *qualifying* moment posted by a **non-elder** family member on family-clock day **D** grants Plus from the start of D until the end of **D+1** (family clock). One a day is enough; extra moments don't stack.
   - Qualifying: a photo that isn't a near-duplicate of the family's last 90 days of photos; a video ≥ 5s; a voice recording ≥ 10s (all config).
   - Counting time is the **server timestamp of the upload intent**. It qualifies if verification completes within 24h of the intent. The client never decides.
2. **Day Pass:** consumable, ~$2.99 (price set in the stores). Grants **24 hours** from the purchase time confirmed by the RevenueCat webhook. Only offered to family members. **Not offered** if the family already has Plus or has a pending upload that would qualify today.
3. **Subscription:** Nodly Plus monthly / annual (suggested $6.99 / $49.99, configured in the stores) — the "never think about it" option. RevenueCat entitlement id: `plus`.
4. **Goodwill:** automatic compensation grants (see errors below) or manual support grants.

**Flow when locked:** tapping a Plus feature in family mode opens a sheet: **"Share a moment — free"** (primary) · **"Day Pass"** · **"Nodly Plus"**. In elder mode: a kind message ("Music is resting today — your family can turn it back on 🙂") + a rate-limited push to the family (max 1 per feature per day). Never shaming copy. Headline: *"Share one moment a day and Plus stays free."*

**Correctness rules**
- Grant a Day Pass **only** from the RevenueCat `NON_RENEWING_PURCHASE` webhook (idempotent by event id + transaction id). After a purchase the app polls `/access`; if the webhook is late, the backend verifies via the RevenueCat REST API.
- Handle refunds (`CANCELLATION` with a refund reason) by revoking the matching grant.
- **Overlap detector job:** if a Day Pass was bought for a window that a qualifying moment already covered (e.g. an upload finished late), open a `billing_incident` and auto-compensate: a goodwill grant, plus a refund where the store allows developers to refund (Google Play via RevenueCat). For Apple, show the user how to request a refund from Apple.
- Every family sees a **billing timeline** ("why do I have / not have Plus, what was charged, when") and a **Report a problem** button.
- We cannot make purchases "non-refundable" — store policies apply. Terms say Day Passes are used immediately.
- RevenueCat **Test Store** key in dev only; never ship it.
- **Galaxy Store builds:** configure RevenueCat with `store: "GALAXY"` and the Galaxy (`galx_…`) public key. Use `GALAXY_BILLING_MODE.TEST` for test builds only and production mode only for beta/production distribution. Product ids and the `plus` entitlement are identical across stores. The backend treats the store as a field on each purchase and applies the same grant rules. For Galaxy Store refunds, check what Samsung/RevenueCat allow developers to do before promising anything; if developer refunds aren't possible, compensate with a goodwill grant and show the user how to ask Samsung.

---

## 11. Recipes rules ("Nodly Kitchen")

- **The author is always an elder.** Byline: author name in the chosen style (full name / first name + last initial / first name only) + **country flag**. If someone helped: "· with help from {helper_name} {flag}". The helper name is free text (any person); the flag is optional.
- Composition: elder by voice (AI assistant, Plus) or typing; or a **helper** composes on the elder's behalf → the elder must **approve in elder mode** ("Publish your recipe?" big Yes/No) before it can be public.
- Visibility: `family` or `public`. Public recipes appear in Nodly Kitchen for all users + get a shareable read-only web page.
- Structure: title, the elder's story/note, photos, ingredients (quantity, unit, item, note), steps (text + optional photo), servings, total time, tags, original language.
- **Ratings:** 1–5 stars, one per account, signed-in users only. Ratings from the author's **own family don't count** toward the public score (shown separately as "Loved by family"). Ranking = Bayesian average (prior weight and global mean in config).
- Tabs: **Top rated**, **New**, **By country** (flag filter), **My family**.
- Units: store quantity + unit; display toggle metric/imperial where convertible.
- Translation on demand (cached), with "Show original".
- **Moderation:** AI pre-check (text + images) → auto-hold if flagged; report + block; a small protected admin review queue; published support email; takedown.

---

## 12. Music rules (Plus)

- **Android:** local native module (Kotlin): NotificationListenerService + MediaSessionManager → now playing (title/artist/artwork), play/pause/next/previous for **any** music app (Spotify, Samsung Music, YouTube Music, Apple Music for Android…). "Play my music" resumes the elder's preferred app via a media-button intent **without opening it**. The family picks the preferred app from installed media apps. Library browsing via MediaBrowser only where the app allows it — degrade gracefully. **Galaxy-first:** Samsung Music is the first app we test and optimise for.
- **iOS:** Apple Music via MusicKit (Swift module; needs the user's Apple Music subscription for catalog). Other iOS music apps: open the app (platform limitation — say so kindly).
- Elder UI: giant controls, big artwork, no small targets.

---

## 13. Presence rules (viewing is Plus)

- The elder must **opt in** (asked during pairing in elder-friendly words, changeable in elder settings; default off).
- States: on Nodly, viewing moments, listening to music (track title only if the elder allows "share what I'm listening to"), writing a recipe, checked in; plus "last seen".
- Supabase Realtime Presence channel per family (authorised). The server keeps only the **latest** state per elder — no activity history beyond 24h.

---

## 14. Widgets & launcher

- **Elder widgets:** "I'm okay" (interactive button + today's status), family **photo frame** (latest moment). **Family widgets:** elder status (✅ time / not yet / HELP active).
- Android: `react-native-android-widget`. iOS: `expo-widgets` (interactive on iOS 17+; widget code runs in an isolated runtime — keep it pure).
- Data: the app writes a small snapshot to shared storage/app group on every relevant change and on data pushes; periodic refresh as backup.
- **Android launcher:** an activity-alias with the HOME category, **enabled only in elder mode**. Home = big tiles: I'm okay · Moments (new count) · Music · Recipes · Help · Phone · Camera · up to 6 favourite apps chosen by the family · "All apps" list (via `<queries>` for launcher activities — no QUERY_ALL_PACKAGES). Leaving launcher mode needs a family PIN or a deliberate long-press + confirm — never trap the elder.
- **iOS:** no launcher → widgets + Lock Screen widget + daily notification with the action button.

---

## 15. Design system (Claude Design → React Native)

- UI is designed in **Claude Design**; handoff bundles go in `/design/<yyyy-mm-dd>-<name>/` and are HTML/CSS **reference**. Translate to React Native with our tokens in `mobile/src/theme`. **Never** render designs in a WebView.
- **Elder mode:** body ≥ 20pt, titles 28–34pt, primary buttons ≥ 64pt tall and full-width, max 6 tiles per screen, icons always with text labels, no swipe-only or long-press-only actions, haptic + sound on key actions, respect system font scale, contrast ≥ 7:1 for body text (≥ 4.5:1 for large bold labels), **no pure white and no pure black**, warm dark mode.
- **Family mode:** same palette family at standard sizes. Calm by default; the Help colour is reserved for real Help.
- **Galaxy optimisation (both modes):** responsive layouts for foldables (Galaxy Z Fold inner + cover screens, Z Flip) that keep state across fold/unfold, plus split-screen/multi-window and pop-up view support. Elder minimum sizes still apply on every screen size.
- Starting tokens (Claude Design may refine them; keep the contrast rules):

| Token | Light | Dark |
|---|---|---|
| background | `#F6F1E7` | `#1C1A17` |
| surface | `#FFFBF4` | `#262320` |
| text | `#2A2520` | `#F1EADF` |
| textMuted | `#52483F` | `#CFC5B7` |
| ok (button bg, white/dark text) | `#245A41` | `#8FD1AE` |
| help (button bg, labels ≥ 24pt bold) | `#B3261E` | `#F2B8B5` |
| accent (icons/large text only) | `#A0501C` | `#E7A47A` |
| border | `#D9CFC0` | `#3A352F` |

---

## 16. Dev environment

- **Windows 11 + PowerShell.** Always give PowerShell commands. `curl` is aliased — use `curl.exe` or `Invoke-RestMethod`.
- conda env `nodly` (Python 3.12). ffmpeg via `winget`. Local PostgreSQL for `nodly_dev` / `nodly_test`.
- Android emulator + a physical Android phone. EAS dev builds.
- A **physical Samsung Galaxy phone** is required for Galaxy Store purchase testing and One UI checks (launcher, battery settings, Samsung Music).
- iOS: EAS cloud builds + Apple Developer account (from Phase 10).
- Secrets only in `.env` files (git-ignored). Keep `.env.example` complete and commented.

---

## 17. Working agreements

- **Plan first** for anything multi-file; wait for my OK.
- Small steps. After each: `ruff check` + `pytest` (backend) / `tsc --noEmit` + lint (mobile). Report results honestly, including failures. Never call a phase done with failing tests.
- Tests are mandatory for: the check-in engine, the help ladder, access evaluation/billing, the moments pipeline, pairing/auth, and ranking.
- Don't guess third-party APIs (RevenueCat, Expo, Supabase, Android MediaSession, MusicKit, Twilio, Anthropic): check the official docs and link them in comments for anything non-obvious.
- Don't build future phases unless asked. Ask before adding dependencies, changing migrated schema, or touching auth/payments beyond the phase scope.
- Commit at the end of each step. Never commit secrets.
- End of every phase: update `docs/PROGRESS.md` (done / decisions / known issues / next) and `docs/DECISIONS.md`.

---

## 18. Phases

Release order: **Galaxy Store → Google Play → App Store** (§19). Phase order below is unchanged.

- [ ] 1. Foundation (backend skeleton, identity schema, jobs, timezone/country services, docs)
- [ ] 2. Auth, families, invites, elder pairing (API)
- [ ] 3. Mobile foundation (Expo, two modes, auth, pairing, i18n, theme, push, EAS Android)
- [ ] 4. Check-ins (engine + elder button + notification action + family status)
- [ ] 5. Help & escalation ladder (push; SMS/voice stubbed)
- [ ] 6. Moments (upload pipeline, verification, feeds, hearts)
- [ ] 7. Nodly Plus & billing (RevenueCat, ledger, moment credits, Day Pass, subscription, incidents)
- [ ] 8. Implement Claude Design screens (both modes)
- [ ] 9. Android home launcher + Android widgets
- [ ] 10. iOS builds + iOS widgets (ships after the Galaxy Store launch)
- [ ] 11. Music hub (Android universal controller; iOS Apple Music)
- [ ] 12. Recipes (compose, helper + approval, public feed, ratings, moderation, translation, web page)
- [ ] 13. AI voice recipe assistant
- [ ] 14. Presence & live activity
- [ ] 15. SMS/voice escalation + alert reliability
- [ ] 16. Launch hardening (deletion, privacy, monitoring, deploy, store builds — Galaxy Store release first)

---

## 19. Store strategy — Galaxy Store first

- **Release order:** 1) **Samsung Galaxy Store** (Shipaton + "Best App for Galaxy"), 2) **Google Play** (reaches every Android phone), 3) **Apple App Store**. All features stay in scope; only the release order changes.
- **Until the Google Play release, Nodly is Samsung-only.** Say so in the store listing and in family onboarding ("everyone in the family needs a Samsung Galaxy phone for now").
- **One codebase, per-store builds:** EAS build profiles `galaxy`, `play`, `ios`. The store is chosen at build time (RevenueCat store + API key, store-specific links like "manage subscription"). Never mix keys between profiles; add a CI check for it.
- **RevenueCat:** add a Galaxy Store app to the same RevenueCat project (package name = applicationId) using the service account ID + private key generated in Samsung Seller Portal. Create the same products in Seller Portal (`plus_monthly`, `plus_annual`, `day_pass`) mapped to the same `plus` entitlement and offerings.
- **Samsung Seller Portal:** register early and get commercial seller approval before selling anything. Samsung In-App Purchase handles payment.
- **Galaxy optimisation** (20% of the "Best App for Galaxy" score): foldable support (Z Fold inner + cover screens, Z Flip; no lost state on fold/unfold), split-screen/multi-window and pop-up view, Samsung Music as the first-class music app, One UI-tested launcher flow and battery guidance, and a polished Galaxy Store listing. Galaxy Store exclusivity can earn bonus consideration.
- **Shipaton requirements:** first public release inside the Shipaton window; the RevenueCat SDK powers at least one purchase; available to download in the United States; a live Galaxy Store listing URL; and a written description of how the app was optimised for Galaxy (foldables, Samsung features, device optimisation).
