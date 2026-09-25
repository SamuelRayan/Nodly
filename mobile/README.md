# Nodly mobile

Placeholder — the Expo app arrives in **Phase 3** (see `CLAUDE.md` §4 and §18).

Planned shape:

- Expo (latest stable SDK), TypeScript strict, Expo Router, EAS development builds only.
- One app, two modes (elder / family), chosen at first launch.
- `mobile/modules/` — local Expo native modules (Kotlin/Swift): launcher, media, etc.
- `mobile/src/theme` — design tokens (CLAUDE.md §15).
- API types generated from the backend OpenAPI schema with `openapi-typescript` — never hand-written.
- `APP_NAME` lives in one constant on this side too.
