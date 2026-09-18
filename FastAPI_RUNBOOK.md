# Hackathon 2026 — Run & Setup Guide

Project: Full Stack FastAPI Template (FastAPI + React/Vite + PostgreSQL)
Stack: n8n Cloud, Google AI Studio (Gemini), FastAPI full-stack app

---

## One-time setup checklist (do these once)

These fixes were needed on this Windows machine due to port conflicts. Once
done, you shouldn't need to repeat them.

1. **Postgres host port**: If port `5432` fails to bind on Windows
   (`bind: An attempt was made to access a socket in a way forbidden by its
   access permissions`), it's a Windows port issue, not Docker. Fix: in
   `compose.override.yml`, map the `db` service to a different **host** port
   while keeping the **container** port at `5432` (Postgres always listens on
   5432 internally, no matter what):
   ```yaml
   db:
     ports:
       - "5000:5432"   # HOST:CONTAINER — only change the left number
   ```
   Then update `.env` to match:
   ```
   DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@localhost:5000/app
   ```
   And in `compose.yml`, the backend's internal `DATABASE_URL` should still
   point at `db:5432` (internal Docker network traffic always uses the real
   container port, never the host-mapped one):
   ```yaml
   DATABASE_URL: postgresql://postgres:${POSTGRES_PASSWORD:?Variable not set}@db:5432/app
   ```

2. **Vite dev server port**: Windows had excluded port ranges
   (`netsh interface ipv4 show excludedportrange protocol=tcp` showed
   `5105–6642` blocked in chunks), which made Vite hunt through 30+ ports
   before landing on a free one. Fixed by pinning Vite to a safe fixed port
   in `frontend/vite.config.ts`:
   ```ts
   export default defineConfig({
     server: {
       port: 4000,
       strictPort: true,
     },
     // ...rest of config
   })
   ```
   And matching it in `.env`:
   ```
   FRONTEND_HOST=http://localhost:4000
   ```
   (`FRONTEND_HOST` is what the backend's CORS check compares the browser's
   origin against — it must exactly match Vite's port or login requests will
   succeed on the backend but get blocked by CORS in the browser, showing as
   "Network error.")

3. If you ever change `POSTGRES_PASSWORD` (or `POSTGRES_DB`/`POSTGRES_USER`)
   in `.env` **after** the database has already been initialized once, it
   won't take effect — Postgres only sets these on first init of a fresh data
   volume. Fix: `docker compose down -v` (wipes the `db` volume) before
   restarting.

---

## Option A — Full Docker Compose (simplest, slower iteration)

```bash
# 1. Prepare the database (migrations + seed superuser)
docker compose run --rm backend bash scripts/prestart.sh

# 2. Start everything (db, backend, frontend, adminer, traefik, mailpit)
docker compose watch
```

Open:
| Service | URL |
|---|---|
| App (frontend + API) | http://localhost:8000 |
| Swagger API docs | http://localhost:8000/docs |
| Adminer (DB admin) | http://localhost:8080 |
| Traefik dashboard | http://localhost:8090 |
| Mailpit (captured emails) | http://localhost:8025 |

Login with `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` from `.env`.

⚠️ Stop any locally running `uv run fastapi dev` first — both use port 8000.

---

## Option B — Local dev servers (faster iteration, hot reload)

```bash
# 1. Start only the supporting services
docker compose up -d db mailpit

# 2. Backend: install deps, migrate, seed, run
cd backend
uv sync
uv run alembic upgrade head          # NOT `uv run bash scripts/prestart.sh` —
uv run python app/initial_data.py    # bash subprocesses don't reliably see the venv on Windows
uv run fastapi dev                   # leave running in this terminal

# 3. Frontend: in a NEW terminal, from the project root
bun install
bun run dev                          # leave running in this terminal
```

Open:
| Service | URL |
|---|---|
| Frontend (hot reload) | http://localhost:4000 |
| Backend API | http://localhost:8000 |
| Swagger API docs | http://localhost:8000/docs |
| Mailpit | http://localhost:8025 |

Login with `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` from `.env`.

---

## Quick troubleshooting reference

| Symptom | Likely cause | Fix |
|---|---|---|
| `bind: ... forbidden by its access permissions` on a Docker port | Windows port exclusion or another service already on that port | Remap the **host** side of the port only; keep container-side port unchanged |
| `alembic: command not found` after `uv run bash scripts/...` | `bash` subprocess doesn't inherit `uv`'s venv PATH on Windows | Run `uv run alembic ...` and `uv run python ...` directly instead of via a bash script |
| `psycopg... connection timeout` | Nothing listening on that host port — `db` container not running, or `.env` port doesn't match compose port mapping | `docker compose ps` / `docker compose logs db`; align `.env`'s `DATABASE_URL` port with the compose host-port mapping |
| `psycopg... server closed the connection unexpectedly` | Container-side port number was changed (should always stay the app's real listening port, e.g. `5432` for Postgres) | In `HOST:CONTAINER` mappings, only ever change the `HOST` (left) number |
| `FATAL: password authentication failed for user "postgres"` | The `db` volume was already initialized with a different password | `docker compose down -v` to wipe the volume, then restart so Postgres re-inits with the current `.env` password |
| Vite prints many `Port XXXX is in use, trying another one...` lines even though nothing is running there | Windows excluded port range (check with `netsh interface ipv4 show excludedportrange protocol=tcp`) | Pin Vite to a fixed port outside the excluded ranges in `vite.config.ts` (`server.port`, `strictPort: true`), and match it with `FRONTEND_HOST` in `.env` |
| Login POSTs return `200` in backend logs but frontend shows "Network error" | CORS mismatch — `FRONTEND_HOST` doesn't match the actual frontend origin | Set `FRONTEND_HOST` in `.env` to the exact URL (including port) the frontend is served from, then restart the backend |

---

## Environment variables that matter for local dev

From `.env` (root):
- `DATABASE_URL` — must match the **host**-mapped Postgres port when running locally
- `FRONTEND_HOST` — must exactly match the Vite dev server's URL (CORS origin check)
- `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` — login credentials for the seeded admin account
- `POSTGRES_PASSWORD` — changing this after first DB init requires `docker compose down -v`
- `GEMINI_API_KEY` / `GEMINI_IMAGE_MODEL` — Google AI Studio integration, already wired into the backend
