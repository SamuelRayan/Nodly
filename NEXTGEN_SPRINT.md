# Nodly — Next Gen sprint (Sat 26 Sep → submit Wed 30 Sep)

**Hard deadline:** Wed 30 Sep, 11:45 PM PDT = **Thu 1 Oct, 12:15 PM IST**.
**Our target:** submitted by **Wed 30 Sep, 10:00 PM IST**. Thursday morning is emergency buffer only.

**What Next Gen needs:**
- a demo video under 2 minutes
- a public GitHub repo under the MIT licence
- purchases shown working through RevenueCat's Test Store

**This file doesn't replace anything.** CLAUDE.md, PROMPTS.md and decisions D69–D72 still rule. This is just the order of work until submission. After Shipaton, continue with the normal phases in PROMPTS.md.

---

## How to use this file

- **One prompt per Claude Code session.** Type `/clear` between prompts.
- **Start every session with Prompt S0** (the memory-safe start), then paste the task prompt.
- **Before any session:** close Edge and anything heavy. One emulator at a time; a second only for two-device checks.
- **When a prompt's "Done when" is met:** commit, then move on. Don't polish anything that isn't in the video.

### Cut lines

If you fall behind, cut in this order. Never cut the last three.

1. Video moments (keep photos)
2. Voice-note moments
3. The subscription option (keep the Day Pass)
4. The billing timeline screen (keep the unlock working)
5. ~~Help~~ · ~~check-in~~ · ~~one working Test Store purchase~~ ← never cut these

---

## Schedule

| When (IST) | Prompt | Your manual jobs |
|---|---|---|
| **Sat evening** | S0 → S1 (finish Help checks) | RevenueCat project + Test Store key (see below) |
| **Sat night / Sun morning** | S0 → S2 (photo moments) | — |
| **Sun afternoon** | S0 → S3 (voice notes; video only if ahead) | GitHub repo (private for now) |
| **Sun evening → night** | S0 → S4 (billing core) | — |
| **Mon morning** | S0 → S5 (billing checks + screens) | Devpost: register, pick Next Gen, verify your VIT email |
| **Mon afternoon** | S0 → S6 (design polish on demo screens) | Export the "Coming next" screens from Claude Design as images |
| **Mon night** | S0 → S7 (demo data + full run-through) | — |
| **Tue morning** | S0 → S8 (repo release: MIT, README, secrets audit) | Confirm the copyright name |
| **Tue afternoon/evening** | S0 → S9 (video script + recording kit) | Record + edit the video (under 2 min) |
| **Wed** | S0 → S10 (final checks) | Upload the video, make the repo public, **submit on Devpost by 10 PM** |
| Thu before 12:15 PM | Buffer only | — |

---

## S0 — Memory-safe start (paste at the start of EVERY session)

```
Read CLAUDE.md, docs/PROGRESS.md, docs/DECISIONS.md (especially D69–D72) and NEXTGEN_SPRINT.md. We're in the Next Gen sprint; the deadline is Thu 1 Oct 12:15 PM IST and our target is Wed 10 PM IST.

Before starting anything:
1. I've closed Edge and heavy apps. Check free RAM and tell me the number.
2. Start only what this session's task needs, in this order: API, worker, Metro, then ONE emulator (1.5 GB, cold boot). Start a second emulator only for two-device checks, and shut it down straight after.
3. No local Gradle builds. Cloud-build only if native deps or config changed; run prebuild locally first to catch config errors, and tell me before spending a build.
4. Tell me in 3 lines what's done and what this session will do. Then wait for the task prompt.
```

---

## S1 — Finish Help checks (Sat evening)

```
Task: finish the Help verification left open yesterday. No new features.

1. Resolve the leftover open Help alert from yesterday so the family dashboard is clean.
2. Verify on two emulators, and fix anything broken:
   a. The elder's screen updates to "Samuel is on it" after the family taps "I'm on it".
   b. The elder cancels with "I'm okay now" and the family gets notified.
   c. The "I'm okay" action on the elder's reminder notification, and the "I'm on it" action on the family's Help notification, both work WITHOUT opening the app. If one isn't reliable on Android, make it open straight to a one-tap screen and record the decision in DECISIONS.md.
   d. A scheduled reminder actually arrives on the elder emulator. Move remind_at close to now to test.
3. Add a small dev-only helper (script or admin route) that sets an elder's remind_at / due_by to "now + N minutes". It's for recording the video later.
4. Update docs/PROGRESS.md.

Done when: all four checks pass on emulators, tests + tsc + lint pass, and the dashboard shows no leftover alerts.
```

---

## S2 — Photo moments (Sat night / Sun morning)

```
Task: photo moments from CLAUDE.md §9, with the qualifying rules from §10 recorded (not yet turned into access; that's S4). PHOTOS ONLY in this session. Plan first, keep the plan short, wait for my OK.

Backend:
- Tables moments, moment_views, moment_reactions. A private Supabase Storage bucket.
- Pipeline: intent (server timestamp) → upload → complete → worker verifies (object exists, MIME, size, perceptual-hash near-duplicate check against the family's last 90 days of photos) → published | rejected with a friendly reason.
- Record qualifies + qualifying_local_date on the family clock. Elder posts never qualify.
- Endpoints: feeds, "new" counts, mark viewed, heart toggle (feature flag on), delete own, short-lived signed URLs.
- Tests: happy path, near-duplicate → posted but not qualifying, double "complete", late verification (23h vs 25h), elder post never qualifies.

Mobile, using the handoff designs:
- Family "Share a moment": pick or take a photo → client-side compression → persistent upload queue (survives app restart and offline) → states Queued → Uploading → Checking → Posted → "Counts for today ✓" chip.
- Family feed grid + viewer with hearts.
- Elder: after "I'm okay", go straight to today's new moments. One photo at a time, huge Next/Previous buttons, a heart, and a big camera button to post.

Done when: on two emulators, a family photo posted with airplane mode toggled mid-upload still finishes and shows "Counts for today ✓", and the elder sees it right after checking in; tests + tsc + lint pass.
```

---

## S3 — Voice notes (Sun afternoon) — cuttable

```
Task: add voice-note moments to the existing moments pipeline, reusing everything from S2. Only if S2 is fully done. Video moments ONLY if this finishes with time to spare — ask me first.

- Family records a voice note (tap to start, tap to stop — no hold). Same upload queue and states as photos.
- Worker: ffprobe duration; qualifies at ≥ 10 s (test 9.9 s vs 10.0 s); max 5 min.
- Elder viewer: a giant play/pause for voice notes, with the sender's name and time.
- Tests for the duration thresholds, and a corrupt file → rejected with a friendly reason.

Done when: a 12 s voice note posts, counts for today and plays on the elder emulator; a 5 s one posts but doesn't count; tests pass.
```

---

## S4 — Billing core with RevenueCat Test Store (Sun evening → night)

**Before this session:** have the RevenueCat Test Store key ready (see Manual jobs).

```
Task: Nodly Plus billing per CLAUDE.md §10, using RevenueCat's Test Store. This is the money logic: correctness over speed. Plan first, including the exact RevenueCat products, entitlement, offering, and which events/API you'll use, with links to the RevenueCat docs you checked. Wait for my OK.

Sprint scope:
1. purchases table (idempotent by event id + transaction id), access_grants ledger, ONE access evaluation function, GET /access (has_plus, sources, window end, today's-moment status on the family clock).
2. Moment credits: a qualifying moment on family-clock day D → a grant for D + D+1. Idempotent per family + day.
3. Day Pass (consumable, day_pass): grant 24 h, ONLY after the purchase is confirmed server-side. First check in the docs whether Test Store purchases send webhooks. If they do, use the webhook (verify the auth header). If not, or if it's late, POST /access/refresh verifies via the RevenueCat REST API. Same idempotent grant either way.
4. Subscription (plus_monthly): mirror the active entitlement into a grant.
5. GET /access/day-pass-eligibility: blocks if the family already has Plus, or has a pending upload that would qualify today.
6. Refund handling: revoke the matching grant.
7. The sprint's Plus feature, gated server-side: "30-day check-in history". The 7-day strip stays free. Keep the other Plus features from §10 in the gate list for later.
8. Mobile (family only): RevenueCat SDK with the Test Store key (from env config, never committed), app user id = Supabase user id, family id as a subscriber attribute. Locked-feature sheet: "Share a moment — free" (primary) · "Day Pass" · "Nodly Plus", plus restore purchases. After a purchase: "Confirming…" → poll /access, never unlock client-side.
9. Elder mode: no purchase UI can ever render. Add a test/assertion.
10. Deferred to after Shipaton, noted in PROGRESS.md: the overlap-detector job, billing_incidents, and store refunds.

Tests (table-driven): day boundaries in 4 timezones incl. a DST day; moment + Day Pass on the same day; duplicate + out-of-order events; the refresh path; refund; an elder device can't purchase.

Done when: on the family emulator, a Test Store Day Pass purchase flips /access to Plus only after server confirmation; posting a qualifying photo grants the day for free; the 30-day history unlocks and locks correctly; tests + tsc + lint pass.
```

---

## S5 — Billing checks + screens (Mon morning)

```
Task: finish and verify the billing experience. No new billing logic unless a bug needs it.

1. Walk through these on the family emulator and fix anything broken:
   - Plus locked → sheet → "Share a moment — free" → post → unlocked.
   - Next family-clock day with no moment → locked → Day Pass (Test Store) → "Confirming…" → unlocked.
   - Restore purchases.
2. "Plus & billing" screen: a plain-language timeline (why they have or don't have Plus, what was bought, when) + "Report a problem" (stores the report and logs it).
3. Dashboard: the "Today's moment" indicator with time left on the family clock, plus the Plus status.
4. Make sure nothing about payments ever appears in elder mode.

Done when: all three walkthroughs pass twice in a row from a fresh app launch.
```

---

## S6 — Design polish on the demo screens (Mon afternoon)

```
Task: bring every screen that appears in the video up to the Claude Design handoff in /design — nothing else. Screens:
- Elder: pairing, home (both states), thank-you → new moments, moments viewer, Help countdown → sent → "Samuel is on it"
- Family: sign-in, dashboard (elder card + 7-day strip + today's moment + Plus status), share a moment with upload states, feed, Help alert, locked-feature sheet, Plus & billing

Rules:
- Use the theme tokens and shared components. Native React Native only, no WebViews.
- Keep elder minimum sizes and contrast.
- Check at the largest system font size.
- List any screen where you deviated from the design, and why.

Don't touch backend behaviour. Done when: every listed screen closely matches the handoff with no clipping at large font; tsc + lint pass.
```

---

## S7 — Demo data + full run-through (Mon night)

```
Task: make the demo reliable to record.

1. A dev-only demo seed script:
   - family "Rayan family" with elder "Mom" (her own timezone) and family member "Samuel"
   - 6 past days of check-ins so the 7-day strip looks real (one missed day that was resolved)
   - 4–5 past photo moments (from a folder of my own or royalty-free photos that I'll point you to)
   - no open alerts
2. A reset script that returns everything to that clean seeded state in one command.
3. Using the S1 helper: set up a "reminder in 2 minutes" state for recording.
4. Run the full video flow end to end on two emulators, twice, and list anything slow, glitchy or confusing:
   pair → reminder → "I'm okay" → new photos → family posts a photo ("Counts for today ✓") → Plus locked → Day Pass → unlocked → Help → family alert → "I'm on it" → elder sees "Samuel is on it" → resolve.
5. Fix the glitches. Anything you can't fix tonight goes into PROGRESS.md.

Done when: the full flow runs cleanly twice from a fresh reset.
```

---

## S8 — Repo release (Tue morning)

```
Task: get the repo ready to go public. Don't make it public yet; I'll do that on Wednesday.

1. LICENSE: MIT, "Copyright (c) 2026 <NAME I CONFIRM>".
2. Secrets audit: scan the FULL git history for .env files, keys, tokens, google-services.json, service accounts and passwords. If anything was ever committed, tell me first; I'll rotate those keys, then we clean the history. Make sure .gitignore covers all of them and every .env.example is complete with placeholders.
3. README.md:
   - what Nodly is (one line + the problem)
   - a 60-second overview (the check-in loop, the Help ladder, moments, "share a moment a day and Plus stays free")
   - screenshots (I'll drop PNGs into docs/screenshots/)
   - an architecture diagram (Mermaid)
   - tech stack
   - how RevenueCat is used (Test Store, Day Pass consumable, subscription, server-side access ledger)
   - how to run it (short, pointing to docs/SETUP.md)
   - "What's working / Coming next" (be honest)
   - Shipaton Next Gen note
   - licence
4. Make sure CLAUDE.md, PROMPTS.md and docs/ are included — they show the plan.

Done when: the secrets scan is clean (or you've told me what to rotate), the README renders well, and tests + tsc + lint pass.
```

---

## S9 — Video script + recording kit (Tue afternoon)

```
Task: help me make a demo video UNDER 2 MINUTES (aim for 1:50).

1. Write docs/VIDEO_SCRIPT.md as a shot list with timestamps and voice-over lines:
   - 0:00–0:12 the problem (elders living alone, families far away)
   - 0:12–1:25 the live demo flow from S7 (elder + family side by side)
   - 1:25–1:40 "Coming next": music, recipes with the voice assistant, launcher, widgets, live activity — clearly labelled as designs, not built
   - 1:40–1:50 the RevenueCat model + close
   Keep the voice-over plain and warm, with no hype.
2. Give me exact recording steps on Windows:
   - showing two emulators side by side
   - OBS scene setup, or the emulator's own screen recording + a simple free editor
   - 1080p export settings
3. Run the reset script and set the "reminder in 2 minutes" state right before I record.

Done when: VIDEO_SCRIPT.md exists and the demo state is ready.
```

---

## S10 — Final checks (Wed)

```
Task: final pre-submission checks. No new features.

1. Run the full backend tests, tsc and lint. Fix anything red.
2. Confirm the README, LICENSE and docs are all in the repo, and that no secrets are tracked (re-run the scan).
3. Walk through docs/SETUP.md as a checklist to confirm a fresh clone would work (don't start emulators; just check the steps and commands are correct).
4. Update PROGRESS.md: what's done, what's deferred (including the physical-Samsung items and the billing overlap detector), and the post-Shipaton plan (the PROMPTS.md phases).
5. Write me a 150-word project description and a one-line tagline for the Devpost submission.

Done when: everything above is green and the text is ready.
```

---

## Manual jobs (only you can do these)

**Sat evening — RevenueCat Test Store**
1. Go to app.revenuecat.com and create a project called **Nodly**.
2. Find the Test Store app/API key in the project. If you can't find it, ask Claude Code in S4 to walk you through it from the RevenueCat docs.
3. Keep the key handy for S4. It goes in the mobile env config, never in git.

**Sun — GitHub**
- Create a **private** repo `nodly`, push the project, and keep it private until Wednesday.

**Mon — Devpost**
1. Register for Shipaton 2026 on Devpost.
2. Check the Next Gen rules and verify eligibility with your **VIT email**.
3. Note exactly which fields the submission form needs (video link, repo link, description, etc.).

**Mon — "Coming next" images**
- In Claude Design, export clean images of the music, recipes + voice assistant, launcher, widgets and live-activity screens for the video.

**Tue — Copyright name**
- Tell Claude Code your legal name for the MIT line (e.g. "Samuel Rayan").

**Tue — Record the video**
- Follow docs/VIDEO_SCRIPT.md. Record in 1080p and keep it under 2:00.

**Wed — Submit (by 10 PM IST)**
1. Upload the video to YouTube (public or unlisted, whichever the form accepts).
2. Make the GitHub repo **public**.
3. Fill in the Devpost form (description from S10, video link, repo link) → **Submit**.
4. Open the submission page in a private window and check that every link works.
