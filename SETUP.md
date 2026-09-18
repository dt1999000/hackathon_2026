# Running and using this app

Bid-matching dashboard: describe your company to Aria, then score German construction tenders against that profile. Matches show as **Gute Treffer** / **Warnungen** / **Schlechte Treffer**.

## What you need

### Install

| Tool | Why |
| --- | --- |
| [Git](https://git-scm.com/) | Clone the repo |
| [Docker Desktop](https://www.docker.com/products/docker-desktop/) | PostgreSQL |
| [uv](https://docs.astral.sh/uv/) | Python 3.14 and backend dependencies |
| [Bun](https://bun.sh/) | Frontend |
| [Ollama](https://ollama.com/) | Local embeddings (`bge-m3`). **Analyze** needs this unless you switch embeddings to Google |

### Copy from a teammate (not in git)

- `.env` at the repo root (gitignored)
- `mock_data/` at the repo root (gitignored — tender JSON that **Load data** imports)

### API keys

- **Anthropic** (`ANTHROPIC_API_KEY`) — onboarding chat, Aria (Claude), and bid-fit LLM. Claude calls fail without it.
- **Optional:** `GOOGLE_API_KEY` only if you pick Google/Gemini in Aria.

Mailpit, Traefik, a Google key, and Firecrawl are **not** required for the demo.

**Hardware:** a few GB of RAM for `bge-m3`. 

## 1. Clone and copy secrets

```bash
git clone git@github.com:dt1999000/hackathon_2026.git
cd hackathon_2026
git checkout main
```

Copy these from a machine that already works:

- `.env` → repo root
- `mock_data/` → repo root (keep the folder structure)

If you create `.env` yourself, use this shape. Generate your own `SECRET_KEY` and `POSTGRES_PASSWORD`. Do not commit `.env`.

```env
DOMAIN=localhost
FASTAPI_ENV=development
PROJECT_NAME=Hackathon 2026
SECRET_KEY=<random long string, not changethis>
FIRST_SUPERUSER=admin@example.com
FIRST_SUPERUSER_PASSWORD=<at least 8 characters>
FRONTEND_HOST=http://localhost:5173
POSTGRES_PASSWORD=<same password as in DATABASE_URL>
DATABASE_URL=postgresql://postgres:<POSTGRES_PASSWORD>@localhost:5432/app
SMTP_HOST=
EMAILS_FROM_EMAIL=info@example.com
SENTRY_DSN=
LLM_LOCAL_BASE_URL=http://127.0.0.1:11434
LLM_LOCAL_MODEL=qwen3:4b
LLM_EMBEDDING_MODEL=bge-m3
ANTHROPIC_API_KEY=<your key>
FIRECRAWL_API_KEY=
```

`frontend/.env` is already in the repo:

```env
VITE_API_URL=http://localhost:8000
```

Docker Compose interpolates the whole `compose.yml`, so `.env` must exist even if you only start Postgres.

## 2. Start Ollama models

```bash
ollama serve          # if it is not already running
ollama pull bge-m3    # required for Analyze
ollama pull qwen3:4b  # only if you want Aria → Local (Ollama)
```

Confirm Ollama is up at [http://127.0.0.1:11434](http://127.0.0.1:11434).

## 3. Start Postgres

From the **repo root**, with Docker Desktop running:

```bash
docker compose up -d db
```

Postgres is published on `localhost:5432`.

## 4. Backend

```bash
cd backend
uv sync
uv run bash scripts/prestart.sh    # migrations + creates FIRST_SUPERUSER
uv run fastapi dev --host 127.0.0.1 --port 8000
```

Python **3.14** is required; `uv sync` can install it.

Checks:

- API docs: [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs)
- Health: [http://127.0.0.1:8000/api/v1/utils/health-check/](http://127.0.0.1:8000/api/v1/utils/health-check/)

## 5. Frontend

New terminal, from the **repo root**:

```bash
bun install
bun run dev
```

Open [http://localhost:5173](http://localhost:5173).

## How to use it

1. **Log in** with `FIRST_SUPERUSER` / `FIRST_SUPERUSER_PASSWORD` from `.env`, or sign up a new user.
2. **Dashboard** (`/`) — you should see the profile card (name, hardliners, capabilities). That is what matching uses.
3. **Load data** — imports tenders from `mock_data/`. A 404 means `mock_data/` is missing.
4. **Analyze** — scores every loaded bid against the profile. Needs Ollama `bge-m3` plus Claude (or another configured LLM). Can take a couple of minutes.
5. Read **Gute Treffer / Warnungen / Schlechte Treffer**.

**Update profile** on the card goes back to onboarding and overwrites the saved profile when you finish again.
