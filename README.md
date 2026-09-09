# Personal AI Agent

A personal, single-user agent that researches, verifies, and prepares — a human always approves before anything executes. See [CLAUDE.md](CLAUDE.md) for the full philosophy, build order, and standards this project is held to.

This is **Phase 1: Foundation** — repo structure, auth, DB, and a real design-system frontend shell. No AI features live here yet; everything below is deterministic infrastructure.

## Stack

- **Backend**: FastAPI (async), Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL + pgvector, Redis, structlog, JWT auth via OAuth2 password flow.
- **Frontend**: React + TypeScript + Vite, Tailwind CSS v4, Radix primitives (shadcn-style components), TanStack Query, Zustand, Framer Motion, a Cmd/Ctrl+K command palette.
- **Infra**: Docker Compose for local Postgres + Redis.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) running (for Postgres + Redis)
- Python 3.11+
- Node 20+

## 1. Start infrastructure

```bash
docker compose up -d
```

Verify both containers are healthy:

```bash
docker compose ps
```

## 2. Backend

```bash
cd backend
python -m venv .venv
./.venv/Scripts/activate        # Windows
pip install -e ".[dev]"
cp ../.env.example ../.env      # then fill in real secrets
alembic upgrade head
uvicorn app.main:app --reload
```

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Health check (verifies live DB + Redis connectivity, not a guess): http://localhost:8000/health

Run tests:

```bash
pytest
```

Lint / type-check:

```bash
ruff check .
mypy app
```

## 3. Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

- App: http://localhost:5173
- First run has no users yet — the app will redirect you to `/login`, but there's no account. Register the first (and only) user via the API docs at http://localhost:8000/docs → `POST /auth/register`. Registration is bootstrap-only: it works once, then locks — this is a single-user personal agent, not a signup flow.

Run unit tests:

```bash
npm run test
```

Run end-to-end tests (first time only, installs browsers):

```bash
npx playwright install
npm run e2e
```

## Verifying Phase 1 end-to-end

1. `docker compose up -d`, confirm both services healthy.
2. Backend running, `GET /health` returns `"status": "ok"` for both `database` and `redis`.
3. Register the first user via `/docs`.
4. Frontend running, log in with that user at http://localhost:5173/login.
5. Dashboard loads your profile (fetched live from the backend), shows the command palette on Cmd/Ctrl+K, and the theme toggle switches light/dark without a flash.
