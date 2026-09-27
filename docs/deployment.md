# Deploying the public demo

This is a checklist for standing up the read-only(ish) public demo — a separate deployment of
the exact same codebase as the personal one, with `demo_mode=true` and one shared, seeded
account. It is not a guide to running your own personal deployment (that's just Docker Compose
locally, or your own infrastructure of choice — see the README's Quick start).

Creating third-party accounts and typing in real payment/API details isn't something this
project's own tooling does on your behalf — that's you, once, by hand. Everything below is the
config this repo already carries so that manual work is short.

## Why these four services

See [decisions.md](decisions.md) for the full trade-off writeup. Short version: Render's and
Neon's and Upstash's free tiers are the ones that don't expire or need a card on file, as of
this writing (2026). Re-verify before you commit to them — free-tier terms change.

| Piece | Service | Free-tier shape |
|---|---|---|
| Frontend | [Vercel](https://vercel.com) | Static hosting, no cold start |
| Backend | [Render](https://render.com) | Sleeps after 15 min idle, ~1 min cold start |
| Postgres (+ pgvector) | [Neon](https://neon.tech) | Scales to zero, no expiry, 0.5GB |
| Redis | [Upstash](https://upstash.com) | 500K commands/month |

## One-time setup

1. **Neon**: create a project, enable the `vector` extension, copy the connection string.
   Run `alembic upgrade head` against it once (from your machine, with `DATABASE_URL` pointed
   at Neon) to create the schema.
2. **Upstash**: create a Redis database, copy its `rediss://` connection string.
3. **Render**: create a new Blueprint from this repo's [render.yaml](../render.yaml). It
   defines the service and generates `APP_SECRET_KEY` for you; you still need to set
   `DATABASE_URL`, `REDIS_URL`, `RATE_LIMIT_STORAGE_URI` (Upstash), and `CORS_ORIGINS` (the
   Vercel URL from the next step) as its own dashboard secrets — `render.yaml` deliberately
   leaves these `sync: false` rather than storing real values in the repo.
4. **Vercel**: import `frontend/` as the project root. Set `VITE_API_URL` to the Render
   service's URL and `VITE_DEMO_MODE=true` as build-time environment variables.
5. **Seed the demo account once**, from your own machine, with `DATABASE_URL` pointed at Neon:
   ```bash
   cd backend && python ../scripts/seed_demo.py
   ```
6. **Turn on the nightly reset**: add `DEMO_DATABASE_URL` and `DEMO_APP_SECRET_KEY` as GitHub
   Actions secrets (Settings → Secrets and variables → Actions), and add a repository
   *variable* `DEMO_ENABLED=true` (Settings → Secrets and variables → Actions → Variables).
   [.github/workflows/demo-reset.yml](../.github/workflows/demo-reset.yml) no-ops until that
   variable is set, specifically so it doesn't fail loudly every night before the demo exists.

## Verifying it worked

- `GET https://<render-url>/health` → `{"status": "ok", ...}`.
- `POST https://<render-url>/auth/demo-login` → a token pair (this 404s if `DEMO_MODE` isn't
  set on Render, or if step 5 hasn't run yet).
- Open the Vercel URL, click "View the demo" on the login page.

## Cost reality check

Every service above is free-tier-only, and none of them ask for a card to stay on the free
tier — check that's still true before you sign up, since terms change. Don't attach a payment
method for this deployment; if a free tier's limits are ever hit, the honest failure mode is
"the demo is briefly unavailable," not a surprise bill.
