# Nodly mobile

One Expo app, two modes (elder / family), chosen at first launch. See `CLAUDE.md` for the
product and `docs/SETUP.md` for running it on an emulator or phone.

- Expo SDK 57 (React Native 0.86), TypeScript strict, Expo Router (routes in `src/app/`).
- EAS development builds only (Expo Go can't run our native modules). Build profiles in
  `eas.json`: `development`, `galaxy`, `play`, `ios`.
- API types are generated from `backend/openapi.json` into `src/api/schema.d.ts`:
  `npm run gen:api` (never hand-write API types). `npm run check` = typecheck + lint + types
  up to date.
- Design tokens live in `src/theme` (CLAUDE.md §15). `APP_NAME` is in `src/config.ts`.
- `AGENTS.md` / `CLAUDE.md` in this folder are Expo's guidance for this SDK: read the versioned
  docs, use `npx expo install`, never edit `android/` or `ios/` by hand (they're generated).
