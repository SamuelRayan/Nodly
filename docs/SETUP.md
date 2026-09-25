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

The defaults match step 4. Every setting is explained in `backend/.env.example`.

## 6. Migrate

```powershell
& $py -m alembic upgrade head
& $py -m alembic current         # 0002 (head)
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
2. `POST /dev/users` with `{"email": "priya@example.com", "display_name": "Priya", "timezone": "Europe/London"}`
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

## 10. Lint and test

```powershell
& $py -m ruff check .
& $py -m ruff format --check .
& $py -m pytest
```

Tests use `TEST_DATABASE_URL` (`nodly_test`) and **wipe it on every run**: the database name must
end in `_test` or the suite refuses to start. The schema is built with the real migrations.

## Troubleshooting

| Problem | Fix |
|---|---|
| `/readyz` returns 503 | Postgres isn't running: `Get-Service postgresql*`, then `Start-Service postgresql-x64-18` in an admin window. |
| `psql` is not recognised | `$env:Path += ";C:\Program Files\PostgreSQL\18\bin"` |
| `password authentication failed for user "nodly"` | Step 4 wasn't run, or `DATABASE_URL` in `backend/.env` has a different password. |
| Port 8000 is in use | Add `--port 8001` to the uvicorn command. |
| `ENV` field required | `backend/.env` is missing: run step 5. |

## Using conda activate (optional)

If you'd rather type `python` than `& $py`, set up conda for PowerShell once:

```powershell
& "$env:USERPROFILE\miniforge3\Scripts\conda.exe" init powershell
Set-ExecutionPolicy -Scope CurrentUser RemoteSigned    # lets PowerShell run the conda profile script
```

Reopen PowerShell, run `conda activate nodly`, and use `python -m ...` wherever this guide says `& $py -m ...`.
