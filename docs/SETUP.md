# Dev setup (Windows 11 + PowerShell)

Every command below is PowerShell (Windows PowerShell 5.1 or PowerShell 7). Run them in order
from a fresh window. `curl` is an alias in PowerShell — use `Invoke-RestMethod` or `curl.exe`.

## 1. Install the tools (once per machine)

```powershell
winget install --id Git.Git -e
winget install --id CondaForge.Miniforge3 -e
winget install --id PostgreSQL.PostgreSQL.18 -e --interactive   # set a password for the "postgres" user when asked
winget install --id Gyan.FFmpeg -e                              # not used until Phase 6 (moments)
```

**Close and reopen PowerShell** so the new PATH entries apply, then check:

```powershell
git --version
ffmpeg -version | Select-Object -First 1
& "C:\Program Files\PostgreSQL\18\bin\psql.exe" --version
Get-Service postgresql*          # Status should be Running
```

If `psql` isn't found in later steps, add it to this window's PATH:

```powershell
$env:Path += ";C:\Program Files\PostgreSQL\18\bin"
```

## 2. Get the code

```powershell
Set-Location $env:USERPROFILE
git clone <repo-url> nodly       # no remote yet: the repo lives at C:\Users\HP\nodly
Set-Location $env:USERPROFILE\nodly\backend
```

## 3. Python environment (conda env `nodly`, Python 3.12)

```powershell
& "$env:USERPROFILE\miniforge3\Scripts\conda.exe" create -n nodly python=3.12 -y
$py = "$env:USERPROFILE\miniforge3\envs\nodly\python.exe"
& $py --version                  # Python 3.12.x
& $py -m pip install -e ".[dev]"
```

`$py` only lives in the current window. **Set it again in every new PowerShell window**:
`$py = "$env:USERPROFILE\miniforge3\envs\nodly\python.exe"`.
(Prefer `conda activate nodly`? See [Using conda activate](#using-conda-activate-optional).)

## 4. Databases

Create a `nodly` role and the two databases. psql asks for the `postgres` password each time.

```powershell
psql -U postgres -h localhost -c "CREATE ROLE nodly LOGIN PASSWORD 'nodly';"
psql -U postgres -h localhost -c "CREATE DATABASE nodly_dev OWNER nodly;"
psql -U postgres -h localhost -c "CREATE DATABASE nodly_test OWNER nodly;"
```

`nodly`/`nodly` is a local-only dev password. If a command says "already exists", that part
is already done.

## 5. Configure

```powershell
Copy-Item .env.example .env
```

The database defaults match step 4. Every setting is explained in `backend/.env.example`.
Then fill in these three:

1. **`CODE_HASH_SECRET`**: a random secret for invite and pairing codes. Generate one and
   paste it in:
   ```powershell
   & $py -c "import secrets; print(secrets.token_urlsafe(48))"
   ```
2. **`SUPABASE_URL`** and **`SUPABASE_PUBLISHABLE_KEY`**: from the Supabase dashboard of the dev
   project (**nodly-dev**, ref `hlfxdejxdbukuyekqrjc`), under *Project Settings → API Keys*. Use the
   `sb_publishable_...` key. It is safe for clients; the API itself only needs the URL.

The project must sign tokens with **asymmetric JWT keys** (*Project Settings → JWT Keys*
shows an ECC/RSA key "in use"). The API only accepts ES256/RS256 tokens verified against
`<SUPABASE_URL>/auth/v1/.well-known/jwks.json`. nodly-dev already uses ES256. On an older
project, click *Migrate JWT secret* and then *Rotate keys*.

Without `SUPABASE_URL` everything else still works, but user endpoints answer
`503 auth_not_configured`.

## 6. Migrate

```powershell
& $py -m alembic upgrade head
& $py -m alembic current         # 0003 (head)
```

## 7. Run the API

```powershell
& $py -m uvicorn nodly.main:create_app --factory --reload --port 8000
```

- Interactive docs: <http://127.0.0.1:8000/docs>
- From another window: `Invoke-RestMethod http://127.0.0.1:8000/readyz` returns `status: ready`.
- Logs are JSON lines. For readable lines, run `$env:LOG_FORMAT = "console"` before starting.

## 8. Run the worker (second PowerShell window)

```powershell
Set-Location $env:USERPROFILE\nodly\backend
$py = "$env:USERPROFILE\miniforge3\envs\nodly\python.exe"
& $py -m nodly.worker
```

Press Ctrl+C once to stop taking new jobs and let running ones finish. Press it again to cancel
them; each cancelled job counts as a failed attempt and is retried later.

## 9. Try the dev routes

With `ENV=dev`, `/docs` has a **dev (ENV=dev only)** section. Run these in order:

1. `POST /dev/families` with `{"name": "The Sharmas"}`
2. `POST /dev/users` with `{"email": "priya@example.com", "display_name": "Priya", "timezone": "Europe/London", "country_code": "GB"}`. These test users have no Supabase account, so they can't sign in (step 10 covers real sign-in).
3. `POST /dev/families/{family_id}/members` with `{"user_id": "...", "role": "organizer"}`
4. `POST /dev/families/{family_id}/elders` with `{"display_name": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN", "is_primary": true}`
5. `GET /dev/families/{family_id}` shows everything together.
6. `POST /dev/jobs` with `{"type": "debug.echo"}` or `{"type": "debug.fail", "max_attempts": 2}`. Watch the worker window, then check `GET /dev/jobs`. A dead job can go back on the queue with `POST /dev/jobs/{id}/requeue`.

The same from PowerShell:

```powershell
$api = "http://127.0.0.1:8000"
$family = Invoke-RestMethod -Method Post "$api/dev/families" -ContentType "application/json" -Body '{"name": "The Sharmas"}'
Invoke-RestMethod -Method Post "$api/dev/families/$($family.id)/elders" -ContentType "application/json" -Body '{"display_name": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN", "is_primary": true}'
Invoke-RestMethod -Method Post "$api/dev/jobs" -ContentType "application/json" -Body '{"type": "debug.echo"}'
Invoke-RestMethod "$api/dev/jobs"
Invoke-RestMethod "$api/v1/meta/timezones/suggest?phone=%2B919876543210"
```

## 10. Sign in with Supabase and walk the real flow

With the API running (step 7), get an access token for yourself:

```powershell
& $py scripts/dev_login.py you@example.com
```

It emails you a sign-in link and waits. **Click the link** on this computer: a small page on
`http://localhost:3000` catches the session. The token is then printed in the terminal and
copied to the clipboard. It's valid for about an hour. Other ways to finish:
`--link "<the link from the email>"` (paste it without clicking), `--code 123456` (only if the Magic
Link email template includes `{{ .Token }}`), or `--password` for a user added in the dashboard.

**From /docs:** click **Authorize**, paste the token under **SupabaseJWT**, then:

1. `PATCH /v1/me` with `{"display_name": "Priya", "timezone": "Asia/Kolkata", "country_code": "IN", "confirm_age_16_plus": true}`
2. `POST /v1/families` with `{"name": "The Sharmas"}` (you become the organizer)
3. `POST /v1/families/{family_id}/invites`. Share the `code` or `link`; another signed-in person joins with `POST /v1/invites/accept`.
4. `POST /v1/families/{family_id}/elders` with `{"display_name": "Asha", "relation_label": "Mom", "timezone": "Asia/Kolkata", "country_code": "IN"}`
5. `POST /v1/elders/{elder_id}/pairing-codes`, then `POST /v1/pairing/claim` with `{"code": "...", "platform": "android"}` (this one needs no sign-in, like the elder's phone). It returns a `device_token`.
6. **Authorize** again and paste the device token under **DeviceToken**. `GET /v1/device/me` now answers as the elder's phone.

**Or all of it in one go:**

```powershell
& $py scripts/demo_flow.py --token "<access token>" --timezone Asia/Kolkata --country IN
```

## 11. Lint and test

```powershell
& $py -m ruff check .
& $py -m ruff format --check .
& $py -m pytest
```

Tests use `TEST_DATABASE_URL` (`nodly_test`) and **wipe it on every run**: the database name must
end in `_test` or the suite refuses to start. The schema is built with the real migrations.
Tests never call the real Supabase. A local fake signs tokens with its own key and serves the JWKS.

## 12. Export the API schema for the mobile app

```powershell
& $py scripts/export_openapi.py          # writes backend/openapi.json
& $py scripts/export_openapi.py --check  # fails if it's out of date (the test suite checks too)
```

Commit `backend/openapi.json` with any API change. The mobile app generates its types from it
with openapi-typescript.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/readyz` returns 503 | Postgres isn't running: `Get-Service postgresql*`, then `Start-Service postgresql-x64-18` in an admin window. |
| `psql` is not recognised | `$env:Path += ";C:\Program Files\PostgreSQL\18\bin"` |
| `password authentication failed for user "nodly"` | Step 4 wasn't run, or `DATABASE_URL` in `backend/.env` has a different password. |
| Port 8000 is in use | Add `--port 8001` to the uvicorn command. |
| `ENV` field required | `backend/.env` is missing: run step 5. |
| `code_hash_secret` field required | Add `CODE_HASH_SECRET` to `backend/.env` (step 5). |
| `email rate limit exceeded` from dev_login | Supabase's built-in email sends only a few emails per hour (and only to your project team's addresses). Wait, or add a user with a password in the dashboard (*Authentication → Users → Add user*, auto-confirm) and use `--password`. |
| `Email link is invalid or has expired` | Sign-in links work once. If you already clicked it (or used `--link`), request a new one. |
| `503 auth_unavailable` | The API can't reach `<SUPABASE_URL>/auth/v1/.well-known/jwks.json`: check the URL and your internet connection. |

## Using conda activate (optional)

If you'd rather type `python` than `& $py`, set up conda for PowerShell once:

```powershell
& "$env:USERPROFILE\miniforge3\Scripts\conda.exe" init powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned    # lets PowerShell run the conda profile script
```

Reopen PowerShell, run `conda activate nodly`, and use `python -m ...` wherever this guide says `& $py -m ...`.
