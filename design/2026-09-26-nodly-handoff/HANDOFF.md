# Nodly – design handoff for Claude Code

Nodly is a daily check-in app for ageing parents, with both sides in one app. The **elder** taps one big "I'm okay" button a day. The **family** (adult children) sees it, shares photos/videos/voice notes ("moments"), and gets alerts. There is no text messaging on purpose. Built for RevenueCat Shipaton 2026 (deadline 30 Sep 2026), launching on Samsung Galaxy Store first, then Google Play, then App Store.

## How to use this folder

- `screens/*.dc.html` is one file per screen (62 screens: 39 core light-mode phone screens at 390×844, plus the extra pages below). **They are visual and copy references, not app code.** They load a runtime (`support.js`) that only exists inside the design canvas, so don't try to open them standalone or port them literally. Read them for exact colours, sizes, spacing, copy and structure, then rebuild each screen natively.
- `canvas.json` gives each screen's ID/title and where it sits on the canvas (elder screens on top row, family screens on the second row).
- **Best results:** export PNGs of the screens from the design canvas (Share > Export) and give Claude Code the images alongside these files. It reads images better than markup.
- Decide the framework before starting (React Native/Expo, Flutter or native Android). Not decided in the design.

Suggested first prompt: *"Read HANDOFF.md fully. Build the elder side first using Expo (or your chosen stack), matching the screens in /screens. Start with E1–E12 (pairing, check-in, moments, Help, missed check-in), with mock data and no backend. Then the family side. Ask me before making any decision not covered in the doc."*

## Design system (as drawn)

**Fonts:** Newsreader (headings, 500–700) and Atkinson Hyperlegible (all body/UI, 400/700). Both are open-licence, so bundle them in the app.

**Colours**

| Token | Hex | Use |
|---|---|---|
| bg | `#FAF6EE` | screen background |
| surface | `#FFFDF9` | cards, inputs |
| border | `#E7DFD2` (`#CFC4B3` for buttons/inputs) | |
| text | `#1E1A15` | primary text, dark buttons |
| muted | `#574E44` | secondary text |
| green | `#2D6A4F` | primary action, "okay" state |
| green-dark | `#1F4D39` | green text on tint |
| green-tint | `#DCEBDF` (`#EAF2EC`, `#EEF4EF`) | "okay" backgrounds |
| amber | `#E8A33D` | "new" badges, late state |
| sand | `#F8E6C4` (text `#5C4A2A`) | moments, voice, recipe audio |
| red | `#B23A2B` (dark `#8A2A1F`) | Help and destructive actions |
| red-tint | `#F6DCD6` (border `#EBC3BA`), page `#FBEDEA` | Help surfaces |
| alert-red | `#A5301F` (panel `#8A2718`, button `#5E1A10`) | full-screen family alerts (F7, F10) |
| star | `#B7791F` | ratings |
| avatar blue | bg `#DDE6F0`, text `#2B3F55` | second family member / strangers |

**Elder-side rules:** body text at least 18px (mostly 20–24), headings 38–50px, buttons 68–92px tall, radius 22–28px, one primary action per screen, back/close as a labelled pill ("Home", "Close", "Cancel"), no swipe-only gestures. **Family side** is denser: text 14–17px, buttons about 52–60px, radius 16–20px. No fake status bar or keyboard is drawn; the real OS ones show. Touch targets are at least 44px. Motion is subtle (pulse on the "I'm okay" halo, waiting dots) and disabled under `prefers-reduced-motion`. Icons are simple 2px-stroke line icons.

## Screen map

**Elder (E)**

| ID | File | What it is | Goes to |
|---|---|---|---|
| E1 | Main | Pairing: 6-digit code (482 913), expires in 9 min, "Waiting for your family…", QR alternative | E2 when family enters the code |
| E2 | ElderPaired | "You're connected with Priya" | E3 |
| E3 | ElderHome | Home, not checked in: big "I'm okay" button; tiles Moments (2 new), Recipes; full-width Help bar | E4, E5, E13, E8 |
| E4 | ElderThanks | Thank you + "checked in at 8:14 AM"; card showing 2 new moments | E5, E7 |
| E5 | ElderMoments | New moments list: photo (Priya) + voice note (Arjun) | E6 |
| E6 | ElderMomentPhoto | Full photo viewer, "Send love", "Next" | E5 |
| E7 | ElderHomeDone | Home, checked in ("Done for today") | same tiles |
| E8 | ElderHelpCountdown | 3-second countdown, "Send now", "Cancel, I'm okay" | E9 or E3 |
| E9 | ElderHelpSent | "Your family has been alerted", per-person delivery status, "Also call 112" | E10 |
| E10 | ElderHelpOnIt | "Priya is on it" (after a family member taps I'm on it), Call Priya, I'm okay now | |
| E11 | ElderNudge | Missed check-in reminder during the buffer: "are you okay?", states when family will be told | E4 |
| E12 | ElderMissedAlerted | "We've let your family know", big I'm okay, I need help | E4, E9 |
| E13 | ElderRecipes | Recipes, "My recipes" tab: "Tell me a recipe" (voice), her recipes | E14, E19 |
| E14 | ElderRecipeListening | Live transcription, timer, Pause, "I'm done" | E15 |
| E15 | ElderRecipeReview | AI-written recipe (ingredients + steps), "Read it to me", "Change it", Share with family / everyone | E13 |
| E19 | ElderRecipesTop | "Top recipes" tab: popular recipes from other grandparents | E20 |
| E20 | ElderRecipeDetail | Recipe with "Hear Kamala tell it" audio, big star rating, "Send Kamala your photo" | E21 |
| E21 | ElderCookedSend | Her cooked photo + pick one of 3 reactions, no text box | E22 |
| E22 | ElderCookedSent | "Sent to Kamala" | |
| E16 | ElderCookedPhoto | Cooked photo from a non-family cook (Meera, "Not family"), Like (toggles Like/Liked), Next, Report | E17 |
| E17 | ElderReportConfirm | Photo blurred, "Report this photo?" | E18 |
| E18 | ElderReportDone | "Done. The photo is gone." | E7 |

**Family (F)** – bottom tabs: Home / Moments / Recipes.

| ID | File | What it is |
|---|---|---|
| F1 | FamilySignIn | Google / email sign-in; "Setting up a parent's phone? Start here" links to elder pairing (E1) |
| F2 | FamilyDashboard | Amma's card: status pill, check-in time, 7-day strip (missed day dashed), Call, Share a moment; "Today's moment" card; "Amma's day" row (locked) |
| F17 | FamilyMoments | Moments tab: carousel of everything shared with Amma, newest first, each with who/when/what Amma did (saw it, sent love, listened) |
| F3 | FamilyPost | Share a moment: Photo / Video / Voice picker, preview, "This counts as today's moment" |
| F4 | FamilyPostUploading | Progress bar, can leave the screen (background upload) |
| F5 | FamilyPostSent | "Sent to Amma" + "Counts for today" |
| F6 | FamilyPostFailed | Offline; photo saved; still counts if sent before midnight |
| F7 | FamilyHelpAlert | Full red screen: "Amma pressed Help": Call Amma, I'm on it |
| F8 | FamilyLocked | Bottom sheet over F2: Share a moment (free) / Day Pass ($2.99) / Nodly Plus ([PRICE]/mo); restore purchases; "Check-ins and Help alerts are never locked" |
| F9 | FamilyDashboardLate | Amber "Late today": timeline (reminded 10:00, reminded 10:30, alert 11:00), Call, Mark okay |
| F10 | FamilyMissedAlert | Red alert: "Amma hasn't checked in": Call, I'm on it, Mark her okay |
| F11 | FamilyRecipes | Recipes tab: newest from Amma (with her voice) + "Popular on Nodly" |
| F12 | FamilyRecipeDetail | Amma's recipe (family view): her voice, rating, strip of photos others sent (each with a report flag), "Cooked it? Send Amma a photo" |
| F13 | FamilyRecipePublic | What anyone sees on Lakshmi's public recipe |
| F14 | FamilyCookedSend | Anyone sends a cooked photo to the author: photo + 1 of 3 reactions, rules shown |
| F15 | FamilyReportSheet | Report sheet: reason picker, what happens next |
| F16 | FamilySenderWarning | What the reported sender sees |

**More screens (lower-fidelity pass, canvas page "More screens")**

| ID | File | What it is |
|---|---|---|
| F18 | FamilyEnterCode | Family types the elder's 6-digit pairing code (or scans QR) |
| F19 | FamilySetupElder | After pairing: what you call her, her name, city/timezone (also sets emergency number), check-in time, invite family |
| F20 | FamilySettings | Check-in due time, reminder interval, alert-after buffer, who gets alerts (toggles), emergency number, "show her city on public recipes" |
| F21 | FamilyAmmasDay | The gated feature: timeline of what she did in Nodly today (check-in, moments seen, recipes, likes). Nodly activity only, no location or other apps |
| E23 | ElderAllMoments | Elder's history of all moments, 2-column grid |

**Dark mode (page "Dark mode"):** `*Dark.dc.html` versions of ElderHome, ElderThanks, ElderMomentPhoto, ElderHelpCountdown, ElderRecipeDetail, FamilyDashboard, FamilyMoments, FamilyRecipes, FamilyPost. Palette mapping: bg `#16130F`, surface `#211D18`, text `#F2ECE2`, muted `#B8AC9C`, borders `#3A342C`/`#4A433A`, dark buttons `#3A332A`, green-tint `#1E3328` (text `#9FD3B4`), sand `#3A2F1E` (text `#E3C99A`), red-tint `#3A1F1B` (text `#F2A596`). Green, red, amber and photos stay the same. Apply the same mapping to every other screen.

**Foldable and split screen (page "Foldable & split screen"):** unfolded (about 780×844) elder home puts the big button on the left and moments, recipes and Help on the right. The unfolded family dashboard uses a nav rail plus two panes. Split screen (about 390×420) has a compact family dashboard and a compact Help alert. **Help and missed-check-in alerts must stay fully usable at half height.**

**Coming next (page "Coming next", one screen each for the video):** NextMusic (elder music player with family-picked playlists), NextVoice (voice assistant: "Call Priya" with a cancel window, suggested phrases), NextLauncher (Nodly as the elder's home screen: clock, I'm okay, big app tiles, Ask Nodly, Help), NextWidgets (elder "I'm okay" and photo widgets; family status, week and today's-moment widgets), NextLiveActivity (family lock-screen live alert for Help with progress).

Prototype links in the files show the intended navigation. Interactive bits worth copying: F17 carousel (prev/next), F15 and E21 reason/reaction radios, E16 Like toggle.

## Rules the screens don't show (build these)

**Check-in and missed check-in**
- Elder taps "I'm okay" once a day. Family sees "Okay today" with the time (shown in the elder's local time; users pick their own timezone, no country defaults).
- If no tap by the due time there is a **buffer**: reminders to the elder, then escalation to a red alert to family (F10, same style as Help). In the design: due 10:00, reminders at 10:00 and 10:30, family alert at 11:00. **Those times are placeholders**; make due time and buffer configurable (the settings screen is not designed yet).
- If the elder taps "I'm okay" after the family was alerted, clear the alert and tell the family.

**Help**
- Help → 3-second cancellable countdown → alert to all family members. First family member to tap "I'm on it" → elder sees "Priya is on it".
- The elder screen says "Also call 112". That is India's number, so **localise it by country**.

**Free-day loop and paywall (RevenueCat)**
- A family member posting a moment (photo, video or voice note via F3) unlocks the app for the family that day.
- If nobody posted, gated features (e.g. "Amma's day") are locked; F8 offers: Share a moment (free), Day Pass (about $3), or Nodly Plus subscription. Include Restore purchases.
- **Never gate:** the "I'm okay" check-in, Help alerts, and missed-check-in alerts. Don't hide the elder's status when she goes quiet either. (This is the recommended design and what F8 states.)
- **Recipe photos do NOT count as a moment.** Store them as a different content type from moments, and have the daily free check count only moments.

**Recipes**
- Elder dictates by voice; AI transcribes and structures ingredients and steps; elder reviews (read-aloud, redo) then chooses to share with family only or with everyone. Keep the original voice recording ("Hear Amma tell it").
- Ratings are 1–5 stars, by family and elders. "Popular/Top" is ranked by rating.
- **Cooked photos:** anyone can send one photo to a recipe's author with one of three preset reactions ("Turned out great", "My family loved it", "Made it my way"). **No free text**, deliberately, so strangers can't message elders. The elder can Like it, skip it or report it. Elders can send cooked photos to other authors the same way.

**Reporting and bans**
- Elder or family can report a photo. Effect: photo is removed from the elder's app immediately, the sender is blocked from contacting that elder, the team reviews it, and serious cases lead to suspension or a permanent account ban. Sender sees the warning in F16. Reasons: Disturbing or violent, Sexual or nude, Scam or spam, Not about cooking, Something else.
- **Recommended, not designed:** run an automatic image check on every stranger photo *before* it reaches the elder, so she never has to see it first (report is the backup, not the main defence); tie accounts to a verified phone number or device so a ban isn't undone by a new account; notify the family when an elder reports something.
- Flags on strangers' photos in F12: only Dan's tile links to the report sheet in the prototype. All tiles should.

**Privacy:** public recipe pages show the author's first name and city (e.g. "Lakshmi · Chennai"). Let the family control what's public.

## Suggested data model

- `family` (id, plan/entitlement state), `user` (id, name, role: elder|family, timezone, country, banned/suspended flags)
- `pairing` (code, expires_at, elder_id, family_id)
- `checkin` (elder_id, local_date, at)
- `alert` (type: help|missed_checkin, elder_id, created_at, ack_by, ack_at)
- `moment` (family_id, sender_id, type: photo|video|voice, media_url, created_at, seen_at, love_at)
- `recipe` (author_id, title, ingredients[], steps[], audio_url, visibility: family|public)
- `rating` (recipe_id, user_id, stars)
- `cooked_photo` (recipe_id, sender_id, media_url, reaction: great|family_loved|my_way, liked_by_author, status: ok|reported|removed)
- `report` (target_id, reporter_id, reason, status, action_taken)

## Placeholder content to replace

All names (Lakshmi/Amma, Priya, Arjun, Kamala, Meera, Tom, Dan, Harjeet, Lourdes, Halina), cities, ratings and counts, all photos (drawn stand-ins), the "Popular on Nodly" list, prices (Day Pass $2.99; Nodly Plus is literally `[PRICE]`), clock times, and dates (around 23–26 Sep 2026).

## Not designed yet (don't invent, ask)

- Family account/profile screen, sign-up by email, invite acceptance flow for a second family member.
- Report sheet for photos other than Dan's (reuse F15 with the right name).
- Dark, foldable and split versions of the remaining screens: follow the patterns above.
- Music, voice, launcher, widgets and live activity are **"Coming next" concepts only**, not for the Shipaton build.
