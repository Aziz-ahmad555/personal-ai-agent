# Personal AI Agent

A personal, single-user agent that researches, verifies, and prepares — a human always approves before anything executes. See [CLAUDE.md](CLAUDE.md) for the full philosophy, build order, and standards this project is held to.

**Phase 1: Foundation** (auth, DB, design-system shell), **Phase 2: Personal Profile Engine** (structured profile, evidence-backed skill history, preferences, pgvector/Voyage embeddings groundwork), **Phase 3: Research Engine** (cited, confidence-scored research queries, full UI), **Phase 4: Semantic Search** ("Ask your agent"), and **Phase 5: Gmail integration — read-only stage** (see below) are done. **Phase 6: Career Intelligence** is in progress — sub-steps 1 (job discovery), 2 (employer verification + fraud/scam detection), 3 (weighted match scoring, with a `/career` page), 4 (application tracker, with an `/applications` board), and 5 (resume tailoring with a reviewable diff) are done (see below); resume tailoring, cover-letter generation, and the ATS checker are not built yet. No email classification/drafting/sending or LinkedIn/GitHub/Fiverr/Indeed integrations exist yet either — those are Phase 7+.

### Phase 6, sub-step 5: Career Intelligence — resume tailoring (a diff you review, never a silent rewrite)
"Tailor your resume" on a job proposes rewordings of your existing summary and role descriptions so they speak to that posting, shown as before/after diffs you **accept or reject one change at a time** — nothing takes effect until you accept it, and pending/rejected changes leave your original wording untouched. It only rephrases what your profile already says. The base resume is assembled from the profile itself (headline, summary, roles, education, and only skills with recorded evidence), so there's no second copy of the truth to drift; a skill asserted without evidence is never written in.
One LLM call proposes the rewordings, each naming the posting requirement it speaks to with that requirement's verbatim quote (reusing the match's quote-checked requirements when there is one). Then **plain code** verifies every proposal (`app/career/resume_verify.py`) and discards any that add a number not in the source, mention a posting or profile skill the item isn't entitled to (for a role, the skill's evidence must point at that role), introduce a proper-looking name found nowhere in the profile, or balloon in length. Discards are recorded with their reasons and shown ("3 suggestions were discarded"), not hidden. Reordering skills (the posting's first) is plain code — a permutation of evidence-backed skills, so it can't add a claim. Required/preferred skills with no evidence are listed as gaps, never inserted.
Changes are reviewed against a snapshot of the base taken at generation, so what you reviewed is what gets exported; a later profile edit marks the draft stale, and regenerating is a confirmed action. Export is Markdown (copy or download) with only accepted changes applied; the profile holds no contact details, so none are invented. Found while running it on a real profile: a plural of a word already in your text ("Law" → "Laws") was being mistaken for an invented name, and Python turned up in the profile with no evidence recorded, so it (correctly) can't be claimed. Green risk; generation, each decision, export, and delete are audit-logged. Not built: cover letters, the ATS checker, PDF export (that comes with reporting).

### Phase 6, sub-step 4: Career Intelligence — application tracker
The user's own record of applying to a job and where it stands (`/career/applications`, `/applications` board). Pure bookkeeping: **nothing is submitted or sent, and every status is entered by the user, never inferred** (inferring it from email waits for Gmail classification, and would arrive as a suggestion to confirm). One application per job posting, so the posting's match, fraud, and employer evidence stay attached. Statuses run `saved → applied → screening → interviewing → offer → accepted`, closing as `rejected` / `withdrawn` / `no_response`.
The transition rules are plain code (`app/career/application_rules.py`) enforced server-side and returned to the UI as `allowed_transitions` / `reopen_targets`, so the frontend never re-implements them: an application must be marked applied before it progresses, may skip forward through active stages, and a closed one must be explicitly reopened; `accepted` is final. The timeline is append-only (status changes, notes, interviews) and dated by when things *happened*, not when they were logged — logging an application after the fact pulls the automatic "saved" event back to the same date, a user-dated status earlier than a previous one is rejected, and future dates are refused.
Moving to `applied` freezes a **snapshot** of the posting's match score (with its low-confidence flag and assessed weight), fraud risk, and employer verification as they were at that moment, recording absence as absent — "applied at 72%, low confidence" stays true after the live values are recomputed. A follow-up reminder (text + date) is shown in-app only, with overdue / due-today computed in code and surfaced on the dashboard; a closed application never nags. Green risk; creation, status changes, reopening, note/follow-up edits (field names only, never the notes themselves), and deletion are all audit-logged.
Also fixed while building it: the API client now refreshes the 30-minute access token on a 401 (using the 14-day refresh token; concurrent requests share one refresh) and only signs the user out if that fails — previously an expired token left every page erroring with no way out.

### Phase 6, sub-step 3: Career Intelligence — weighted match scoring
`POST /career/jobs/{id}/match` (background task; the `/career` page polls) answers "how well does this job fit me?" as a percentage where every point traces to evidence. An LLM reads the posting into structured requirements (required/preferred skills, minimum years, education, industry), each with a **verbatim quote** that plain code re-checks against the posting text — a requirement whose quote can't be found is dropped, never scored (the same guardrail as Phase 3's citations). Everything after that is deterministic code (`app/career/matching.py`), no LLM: required skills 35, years of experience 20, preferred skills 10, work mode/location 10, salary 10, industry 10, education 5. Skills match exactly or by alias; an embedding-similar skill counts for labeled half credit (`FUZZY_SIMILARITY_THRESHOLD` is an uncalibrated starting default, worth tuning against real postings). Only skills with recorded evidence count.
A component the posting or profile can't speak to (salary not published, no work history on file, ...) is **not assessed**: left out of the denominator and listed under "what this doesn't know" — never scored 0 or guessed. `assessed_weight` records how many of the 100 points were measurable; under 55 the match is flagged `low_confidence`, and the UI shows a prominent "Low confidence — most components unknown" warning ahead of the number (relabeled "of what could be measured"). With nothing measurable there's no score at all ("Can't score"), not 0%. Free-text deal-breakers are checked against the posting and reported only with a verified quote; if that check fails it's shown as "not checked", never as clear. Each match stores a hash of the profile it was computed from, so a later profile edit marks it stale. Employer-verification and fraud results are shown right next to the score — a high-fraud posting is called out so a good fit on paper can't reassure. Green risk, audit-logged (`career.job.matched`).
The `/career` page also covers adding postings (paste or URL), the employer/fraud check, and job-board feed management. Not built yet in Phase 6: cover letters and the ATS checker.

### Phase 6, sub-step 2: Career Intelligence — employer verification + fraud/scam detection

`POST /career/jobs/{id}/verify` (background task, same pattern as feed polling) runs two independent, always-both-run steps. **Employer verification** reuses Phase 3's full research pipeline rather than a parallel mechanism — a targeted query asking whether the claimed employer is real — cached per employer (`EmployerVerification`, keyed by domain or lowercased name) for 30 days, so many postings from the same company share one research run. The verdict (`verified` / `unconfirmed` / `suspicious` — deliberately not `ResearchClaim`'s own status vocabulary, since it answers a different question) is derived by plain code: each claim's supporting citations are re-classified with `classify_domain(..., employer_domains={company_domain})` (the shared pipeline can't do this at collect time, since it doesn't yet know which domain is "confirmed" — that judgment belongs here, without mutating the stored, context-free source row) and re-scored with Phase 3's own `score_claim`, never a second LLM call re-deciding the answer.

**Fraud/scam detection** (`app/career/fraud.py`) is fully deterministic, plain-code pattern matching over the posting's stored fields — no LLM, per CLAUDE.md's "no LLM for ... policy enforcement" rule: upfront-payment language, requests for sensitive info before an interview, a suspicious/unconfirmed employer, a mismatched posting domain, a personal email standing in for a corporate contact, urgency/pressure language, and an inverted or implausibly wide salary range each carry a weight; the summed score maps to `low`/`medium`/`high`. Every signal that actually fired is stored (`JobFraudAssessment.signals`), so a `high` verdict is always traceable to specific reasons, never an opaque score. Both steps log to the audit trail (`career.employer.verified`, `career.job.fraud_assessed`), and `GET /career/jobs`/`GET /career/jobs/{id}` return the results nested once computed (`null` until then).

### Phase 6, sub-step 1: Career Intelligence — job discovery

Two discovery paths, both backend-only so far (no frontend page yet — use `/docs`): **manual capture** (`POST /career/jobs/from-url` fetches a URL through the same `app.research.fetch`/`verify_source`/`classify_domain` pipeline Phase 3 built, so a captured posting's page becomes a real `ResearchSource` row rather than a parallel one; `POST /career/jobs/paste` takes raw text directly), and **board polling** (`POST /career/jobs/feeds` subscribes to a company's postings on Greenhouse, Lever, or Ashby, or a USAJobs keyword search — all public, documented, unauthenticated job-board APIs meant for third-party consumption, polled with plain `httpx`, never scraped). LinkedIn and Indeed are deliberately absent: both require an official partner/publisher API agreement, which is Phase 7, not this one.

Every posting's structured fields (title, company, location, remote type, salary) are extracted by an LLM constrained to a required-only JSON schema (`app/career/extraction.py`) — an unstated field comes back absent, never guessed. Dedup is two-layered like Phase 3's: exact match on normalized URL / board external id, plus a `description_hash` check across channels so the same posting re-published on a different board doesn't double-count.

New shared infrastructure landed alongside it: `app/audit/` is the first real implementation of CLAUDE.md's Green/Yellow/Red risk model — `AuditLog` rows record every risky action's what/why/evidence/risk level/decision/result; green actions log themselves automatically, yellow/red actions go through `request_approval` → `decide_approval` (`POST /audit/logs/{id}/decide`), and a red-risk approval is refused unless `second_check_passed` is explicitly true. Job discovery itself is entirely green risk (nothing leaves the system — only public data the user pointed at or subscribed to is read), so this phase is also the first real exercise of the audit trail without yet exercising the approval gate itself.

### Phase 5: Gmail (read-only)

OAuth2 web flow, hand-rolled over `httpx` rather than `google-api-python-client`/`google-auth-oauthlib` (both sync-only — this codebase never blocks inside async request handlers). The CSRF `state` param is a short-lived signed JWT carrying the user id (reusing `app/auth/security.py`'s token machinery), since the OAuth callback is hit directly by the browser with no Bearer header available. Requests exactly `gmail.readonly` — nothing else — and the granted scope Google actually returns is checked against that, never assumed. Tokens are Fernet-encrypted at rest (`TOKEN_ENCRYPTION_KEY`) — the one thing this app stores that's a live credential to something real.

A sync is a `GmailSyncRun` with the same `pending → running → completed/failed` lifecycle as `ResearchQuery`, polled the same way from `/gmail`. First sync is a **backfill** bounded to `GMAIL_SYNC_WINDOW_DAYS` (default 180) — deliberately not the whole mailbox, since nothing has judged relevance yet at this stage (data-minimization). Later syncs are **incremental**, via the Gmail History API from a stored cursor; a stale cursor (Gmail only retains ~1 week of history) falls back to a fresh backfill automatically. Stores metadata + plain-text body only — no raw MIME, no attachments. Message content is **not** wired into Phase 4's embeddings/search — classifying what's actually relevant is explicitly the next stage, not this one.

Real-world lesson from live testing: Gmail's per-user quota rate-limited a 668-message first backfill hard enough that ~40% of fetches (and the trailing bookkeeping call) came back `403`. Fixed with exponential-backoff retry in `app/gmail/client.py` (only for rate-limit-flavored responses — a genuine permission/not-found error still fails immediately) plus making the history-cursor update non-fatal, so a rate-limited tail call degrades to "next sync re-backfills" instead of discarding an otherwise-successful run.

Disconnecting always asks — keep the already-synced mail, or delete it — never a silent default either way. Requires `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` (OAuth consent screen kept in "Testing" status — no Google review needed for personal use, but refresh tokens then expire every 7 days; reconnect from `/gmail` when that happens) and `TOKEN_ENCRYPTION_KEY` in `.env`.

### Phase 4: Semantic Search

Cross-corpus retrieval, not an LLM-synthesized answer — a deliberate choice to keep Phase 3's evidence discipline (every result is a real row, never a generated summary). A query is embedded once (Voyage, `input_type="query"` — distinct from the `"document"` type used when indexing content, since Voyage's retrieval models are trained asymmetrically), then ranked by pgvector cosine distance against both `ProfileEmbedding` and `ResearchEmbedding` in one blended list (same embedding model/dimension for both, so the distances are directly comparable). Results are deduped to one per real row (a long research source with several embedded chunks surfaces once) and resolved back to actual fields — a skill hit shows the real skill name and level, not a raw text blob. No relevance score is shown: it isn't the same kind of rigor as Phase 3's confidence score, and showing a number next to both would imply otherwise.

Searchable: profile bio, work experience, education, skills (with evidence), preferences, and research claims/sources. `GET /search?q=...`, user-scoped. Surfaces in two places: a dedicated `/search` page, and the Cmd/Ctrl+K command palette (type a query, select "Search for '...'" to deep-link with the query prefilled and auto-run). Research results deep-link into `/research` with the exact query selected and the specific claim/source scrolled-to and highlighted.

### Phase 3: Research Engine

A research query runs as a LangGraph pipeline: **search** (Tavily) → **collect** (fetch + trafilatura extraction + robots.txt respect + rule-based source-tier classification) → **dedupe** (exact hash + Voyage-embedding semantic similarity) → **extract** (LLM pulls structured claims from tier-labeled excerpts, each claim requiring a verbatim citation that plain code re-verifies against the actually-stored source text — a claim whose quote can't be found is forced to `unverified`/0% confidence, never asserted) → **report** (LLM drafts a claim-linked summary; any citation marker it invents is stripped before storage). Confidence scores are a deterministic formula (source tier + independent corroboration + recency + citation verification), not model self-assessment. See [CLAUDE.md](CLAUDE.md) for the full source-tier hierarchy and design rationale.

The LLM step is behind a provider interface (`app/research/llm.py`, `LLMProvider`) — Gemini Flash by default, Anthropic available — swappable via `LLM_PROVIDER` in `.env` without touching pipeline code. Runs as a FastAPI `BackgroundTask` (no Celery/APScheduler yet): `POST /research/queries` returns immediately with status `pending`; the `/research` page polls `GET /research/queries/{id}` for `running` → `completed`/`failed` and shows sources, claims, citations, and the report as they land — including partial progress on a failed run, never hidden.

Requires `TAVILY_API_KEY` and (`GEMINI_API_KEY` or `ANTHROPIC_API_KEY`, matching `LLM_PROVIDER`) in `.env` to actually run; without them the query fails cleanly with a clear `error` field rather than hanging or fabricating a result.

## Stack

- **Backend**: FastAPI (async), Pydantic v2, SQLAlchemy 2.0 (async) + Alembic, PostgreSQL + pgvector, Redis, structlog, JWT auth via OAuth2 password flow, Voyage AI for embeddings, LangGraph for the Research Engine pipeline, Tavily for search, Gemini/Anthropic for claim extraction and report drafting, Gmail API (read-only) via a hand-rolled async OAuth2 client.
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

**Note:** Postgres is mapped to host port **5433**, not the default 5432. If you have a native/standalone Postgres already running on this machine, it silently wins the 5432 binding on Windows (IPv4 vs IPv6 binding precedence) and `localhost:5432` connections will hit *that* server instead of the container — auth then fails with no trace in the container's logs. Using 5433 avoids the collision entirely. If 5433 is also taken on your machine, change `POSTGRES_PORT` in `.env` and `DATABASE_URL`'s port to match.

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

Settings always load `.env` from the repo root regardless of your working directory, so run these commands from wherever's convenient — there's no ambiguity about which `.env` gets read.

- API: http://localhost:8000
- Interactive docs: http://localhost:8000/docs
- Health check (verifies live DB + Redis connectivity, not a guess): http://localhost:8000/health

**Embeddings (optional for profile CRUD, required for Search):** the Profile Engine embeds bio/work-experience/education/skill-evidence/preferences text via Voyage AI. Set `VOYAGE_API_KEY` in `.env` (get one at https://dash.voyageai.com) to enable it — without it, profile CRUD still works fully, embeddings are just skipped with a logged warning rather than faked. `/search`, however, has nothing to search without a Voyage key — it fails the request clearly (503) rather than silently returning zero results.

**Research Engine (requires keys to run):** unlike embeddings, `TAVILY_API_KEY` (https://tavily.com) is required — there's no meaningful research without search. Also set `LLM_PROVIDER` (`gemini` by default, or `anthropic`) and the matching `GEMINI_API_KEY` (https://aistudio.google.com/apikey) or `ANTHROPIC_API_KEY` (https://console.anthropic.com). Missing keys fail the query cleanly with an `error` field rather than hanging.

**Career Intelligence — job discovery (Greenhouse/Lever/Ashby need no key; USAJobs does):** Greenhouse, Lever, and Ashby feeds work with no configuration — their job-board APIs are public. USAJobs additionally requires a free registered key from https://developer.usajobs.gov, set as `USAJOBS_API_KEY`, plus your own contact email as `USAJOBS_USER_AGENT_EMAIL` (required by their terms). Manual capture (`from-url`/`paste`) reuses the Research Engine's fetch pipeline and LLM provider, so it needs the same keys as Phase 3 above.

**Gmail (requires keys to connect):** create an OAuth 2.0 Client ID at https://console.cloud.google.com/apis/credentials, add `http://localhost:8000/gmail/oauth/callback` under Authorized redirect URIs, add your own Google account as a test user on the OAuth consent screen (keep it in "Testing" status), and set `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET` plus a generated `TOKEN_ENCRYPTION_KEY` in `.env` — see `.env.example` for the exact command. Testing-status refresh tokens expire every 7 days; reconnect from `/gmail` when the status shows "Needs reconnect".

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

## Verifying end-to-end

1. `docker compose up -d`, confirm both services healthy.
2. Backend running, `GET /health` returns `"status": "ok"` for both `database` and `redis`.
3. Register the first user via `/docs`.
4. Frontend running, log in with that user at http://localhost:5173/login.
5. Dashboard loads your profile (fetched live from the backend), shows the command palette on Cmd/Ctrl+K, and the theme toggle switches light/dark without a flash.
6. Go to **Profile**: fill in the overview form, add a work experience, add a skill and give it an evidence-backed assessment, set preferences. Everything persists to Postgres; a second assessment on the same skill adds to its history instead of overwriting the first.
7. Go to **Research**: submit a question, watch it move from `pending`/`running` to `completed` (polls automatically), and see the report, claims (with confidence + rationale), citations (with verified/unverified marks), and sources.
8. Go to **Search** (or press Cmd/Ctrl+K and type a query, then select "Search for..."): a real profile field or research claim/source should come back, resolved to its actual title — not a floating text blob. Clicking a research result should land on `/research` with that exact query selected and the claim/source scrolled to and briefly highlighted.
9. Go to **Gmail**: click "Connect Gmail (read-only)", complete Google's consent screen, and confirm you land back on `/gmail` with your real email address shown and status "Connected". Click "Sync now" and watch it move from `Queued`/`Syncing` to `Done`, with a real, growing message count — then confirm real subjects/senders/snippets show up in "Recent mail". The "Disconnect" button should show a dialog asking whether to keep or delete the synced mail, never disconnecting silently.
10. Career job discovery has no frontend page yet — verify via `/docs`: `POST /career/jobs/from-url` with a real job posting URL and confirm the extracted title/company/location come back (absent fields come back `null`, never guessed); `POST /career/jobs/feeds` with `{"board": "greenhouse", "company_slug": "airbnb"}` (or any company known to be on Greenhouse), then `POST /career/jobs/feeds/{id}/poll` and confirm `GET /career/jobs` shows real postings shortly after. `GET /audit/logs` should show a `career.job.captured_from_url` / `career.feed.polled` row for each action, all `risk_level: "green"` and `status: "completed"`.
11. Employer verification + fraud detection, also `/docs`-only for now: `POST /career/jobs/{id}/verify` on a captured posting, then `GET /career/jobs/{id}` shortly after and confirm `employer_verification` (status/confidence/rationale) and `fraud_assessment` (risk_level/risk_score/signals) are populated — `null` beforehand, real values after. `GET /audit/logs` should show `career.employer.verified` and `career.job.fraud_assessed` rows.
