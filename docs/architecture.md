# Architecture

This is the detail behind the README's diagrams: the real components, how a request actually
flows through them, and the design of each subsystem. Where a decision needs justifying rather
than just describing, that's in [decisions.md](decisions.md) instead — this file describes what
exists, not why it was chosen.

## Repo layout

```
backend/
  app/
    auth/         JWT + OAuth2 password flow, account deletion (red-risk)
    profile/      Profile Engine — bio, experience, education, skills, preferences, embeddings
    research/     Research Engine — the LangGraph pipeline, LLM provider abstraction, cost guard
    search/       Semantic Search — cross-corpus pgvector retrieval
    career/       Career Intelligence — discovery, verification, fraud, matching, applications,
                  resume, cover letters, ATS, interview practice
    gmail/        Gmail integration (read-only)
    github/       GitHub integration (read-only)
    calendar/     Calendar integration (read-only)
    reporting/    Weekly digest + PDF export
    audit/        Green/Yellow/Red risk model, approval flow, second-check registry
    integrations/ The cross-integration "what's connected" overview
    core/         Rate limiting, health checks, the background scheduler
    db/           SQLAlchemy Base, async session factory
  alembic/        Migrations — a fresh clone builds the schema from nothing (verified)
  tests/          785 tests; tests/conftest.py is the shared test infrastructure
frontend/
  src/
    features/     One folder per domain (profile, research, career, gmail, github, calendar,
                   reporting, landing, ...), each owning its own API hooks and components
    components/   Shared UI (shadcn-style, Radix primitives) and layout (AppShell, ReauthBanner)
    stores/       Zustand — currently just auth
evals/            The eval harness — a separate tool that imports from backend/, never the
                  reverse; its own dedicated Postgres database, never the real one (see below)
docs/             This folder
.github/workflows/  CI (every push) and evals (manual dispatch)
```

## Request flow, end to end

Take a research query as the representative example — it touches most of the same machinery
every other feature does:

1. **Frontend** (`POST /research/queries` via the TanStack Query mutation in
   `features/research/hooks.ts`) sends the query text with a Bearer JWT.
2. **`app/auth/deps.get_current_user`** decodes the JWT and loads the user — every authenticated
   route depends on this the same way.
3. **`app/research/router.py`** creates a `ResearchQuery` row (`status="pending"`), binds a
   fresh `task_id` via `structlog.contextvars` (so every log line from here on, however deep,
   carries it), and hands off to a FastAPI `BackgroundTasks` callback — the endpoint returns
   immediately, before the actual work runs.
4. The background task opens its own DB session (`db_base.async_session_factory` — background
   work runs outside FastAPI's request-scoped dependency injection, so it can't reuse the
   request's session) and calls `run_research_query`, which builds and runs the LangGraph graph
   described in the README: **search → collect → dedupe → extract → report**.
5. Each LLM-calling step goes through `get_llm_provider()`, which — regardless of which real
   provider (Groq/Gemini/Anthropic) is configured — always returns a `SpendGuardedProvider`
   wrapping it. That checks the task's own running token total and today's persisted spend
   ledger *before* the call, and writes a ledger row *after* one succeeds.
6. Every claim `extract` produces is independently checked against the real, stored source text
   (`verify_citation_excerpt`) before it's persisted — a citation that can't be found is forced
   to `unverified`/0% confidence, never asserted anyway.
7. The frontend polls `GET /research/queries/{id}` (React Query's own polling) until status
   leaves `pending`/`running`, then renders sources, claims, citations, and the report as they
   land — including whatever succeeded before a failure, never hidden.

Every other background-task feature (career matching, resume tailoring, cover-letter drafting,
GitHub/Gmail/Calendar sync) follows this same shape: request creates a row and returns
immediately → a background task does the real work with its own session and its own
`task_id` → the frontend polls.

## Auth

JWT via `pyjwt`, OAuth2 password flow (`/auth/login` with a username/password form, not a
third-party identity provider — this is a single-user app).
Access tokens are short-lived (30 min default); refresh tokens are longer-lived (14 days) and
**not yet rotated on use** — a known, documented gap, see the README's Limitations section and
`app/auth/router.py`'s `refresh` docstring. Registration is bootstrap-only: it works exactly
once, then `any_users_exist()` locks it — there is no multi-tenant signup flow to secure.

Login/register are rate-limited (`slowapi`, 5/minute per IP) — the one place an unauthenticated
caller can make the server do repeated work against a guessable identity.

**Full-account deletion** (`app/auth/account_deletion.py`) lives here too, as the account's own
lifecycle action: a genuine Red-risk, two-step flow (request → decide) that gathers a live
evidence snapshot (row counts across every table with a direct `users.id` foreign key, plus
connection statuses), re-verifies that exact snapshot hasn't drifted at decision time (the
independent second check), then revokes every connected integration at its provider and deletes
the user row — which cascades every owned table (every foreign key to `users.id` is
`ondelete="CASCADE"`, verified against a genuinely empty database, not just assumed).

## Profile Engine

Structured profile: bio/headline/summary, work experience, education, skills, and preferences.
Skills are versioned, not overwritten — `SkillVersion` rows accumulate over time, each with its
own recorded evidence text, so "how proficient was I at X six months ago" is an answerable
question, not lost history. Every text field that matters for retrieval is embedded via Voyage
AI (`input_type="document"`) into `ProfileEmbedding`, keyed polymorphically (`owner_type` +
`owner_id`) so a hit resolves back to the real row, never a floating text blob.

## Research Engine

The pipeline itself is the README's second diagram. A few details worth knowing:

- **Source-tier classification** (official > government > docs > reputable secondary >
  forum-anecdotal > unknown) happens inside `collect`, per-source, the moment it's fetched — a
  synchronous judgment made once, not re-derived later.
- **Deduplication** is two-layered: exact hash on normalized content, then Voyage-embedding
  semantic similarity, so a syndicated copy of the same press release on two domains collapses
  to one source rather than double-counting corroboration.
- **Confidence scoring** is a deterministic formula (source tier + independent corroboration +
  recency + citation verification) — never the model grading its own output.
- **The LLM step is behind `app.research.llm.LLMProvider`**, a Protocol implemented by
  `GeminiLLMProvider`, `AnthropicLLMProvider`, and `GroqLLMProvider` — swappable via
  `LLM_PROVIDER` in `.env` with zero pipeline-code changes. Every provider goes through the same
  retry/backoff shape (bounded exponential backoff, transient-vs-permanent classified per
  provider's own error shape) and the same `SpendGuardedProvider` wrapping described above.
- **`wrap_untrusted`** labels every span of externally-sourced text (a job posting, a fetched
  page, claims ultimately sourced from the web) before it enters a prompt — explicitly
  defense-in-depth, never the actual defense (see Safety by design in the README).

## Semantic Search

One embedded query (`input_type="query"` — Voyage's retrieval models are trained asymmetrically
from the document side, so this distinction is load-bearing, not cosmetic) ranked by pgvector
cosine distance against `ProfileEmbedding` and `ResearchEmbedding` in one blended list, since
both use the same embedding model/dimension and are directly comparable. Results are deduped to
one per real row and resolved back to actual fields. No relevance score is shown — it isn't the
same kind of rigor as the Research Engine's own confidence score, and showing a number next to
both would imply otherwise.

## Career Intelligence

The largest subsystem, built in sub-steps that each stayed real and tested before the next
began:

- **Discovery**: manual capture (a pasted URL goes through the *same* fetch/verify/classify
  pipeline the Research Engine uses — a captured posting's page becomes a real `ResearchSource`
  row, not a parallel one) or board polling (Greenhouse/Lever/Ashby/USAJobs — all public,
  documented, unauthenticated APIs meant for third-party consumption; never scraped).
- **Employer verification** reuses the Research Engine's full pipeline (a targeted "is this
  employer real" query), cached 30 days per employer so postings from the same company share
  one research run. **Fraud/scam detection** is fully deterministic pattern-matching (upfront-
  payment language, pre-interview sensitive-info requests, a suspicious employer, a mismatched
  domain, urgency language, an implausible salary range) — no LLM, since this is policy
  enforcement, not language understanding.
- **Match scoring**: an LLM extracts structured requirements from the posting, each with a
  verbatim quote plain code re-verifies (a quote that can't be found is dropped, never scored).
  Everything after that is deterministic (`app/career/matching.py`) — required skills 35 points,
  years of experience 20, preferred skills 10, work mode/location 10, salary 10, industry 10,
  education 5. A component neither the posting nor the profile can speak to is left out of the
  denominator entirely, never scored zero.
- **Applications, resume tailoring, cover letters, ATS check, interview practice** each follow
  the same discipline: an LLM proposes, deterministic code verifies against real evidence before
  anything is shown, and every discard is recorded with its reason rather than silently dropped.

## Gmail / GitHub / Calendar

All three are read-only, OAuth2-based, Fernet-encrypted at rest (`app.gmail.crypto`, shared
across all three), and follow the same connect → sync → disconnect shape:

- **Gmail**: `gmail.readonly` scope only. First sync is a bounded backfill
  (`GMAIL_SYNC_WINDOW_DAYS`, default 180 — data-minimization, since nothing has judged relevance
  yet); later syncs are incremental via the History API, falling back to a fresh backfill if the
  cursor's gone stale. Stores metadata + plain-text body only, never raw MIME or attachments.
- **GitHub**: connects via a GitHub App (not an OAuth App — a classic OAuth App's `repo` scope
  includes write, so it can't be read-only for private repos), registered with no permissions
  beyond mandatory `metadata:read`. The callback refuses to connect (and revokes the token) if
  GitHub ever reports write/admin access on an installation. Sync derives skill-evidence
  proposals from language bytes, dependency manifests, and commit attribution — deterministic,
  no LLM — and a separate, on-demand recruiter-readiness review checks each repo against
  documented-good-practice signals (README quality, license, tests, CI, no committed secrets),
  computed from the last sync's snapshot so viewing it makes zero new GitHub requests.
- **Calendar**: `calendar.events.readonly`, its own independently-revocable connection (own
  callback, own OAuth state-token type, own DB row) even though it shares Gmail's Google Cloud
  project. Event reading and interview/deadline detection aren't built yet — only the connection
  itself is (see the README's Limitations).

## Reporting

The weekly digest aggregates career activity, research activity, and each integration's status
into one view, plus a set of "needs attention" signals computed from logic that already exists
elsewhere in the app (`follow_up_state` for overdue applications, profile-staleness on a match,
`is_stalled` for a hung sync, `needs_reauth` for a dead OAuth grant, pending approvals/proposals)
— the digest doesn't reimplement any of these checks, it just surfaces them in one place.
Exportable as PDF (`reportlab`). Both the digest's own "today" and every signal it surfaces are
computed in UTC consistently — see [decisions.md](decisions.md) for why that consistency is
load-bearing, not incidental.

## Audit & Approval

`app/audit/service.py` is the single implementation of the Green/Yellow/Red model:

- `log_action` — Green only (enforced: raises on anything else) — records an already-completed
  automatic action.
- `request_approval` → `decide_approval` — Yellow/Red. `decide_approval` is one atomic
  `UPDATE ... WHERE status='pending_approval'`, not a select-then-write, so the database's own
  row lock (not application logic) makes two concurrent decisions on the same row impossible.
  Approving a **Red** row additionally requires a check registered in
  `app.audit.second_checks.SECOND_CHECKS`, keyed by the row's own `action` string, run
  server-side at the moment of decision against the row's *stored* evidence — never something
  the API caller supplies. No registered check means no approval, full stop.
- `record_result` — records what actually happened after an approved Yellow/Red action executes,
  kept deliberately distinct from `log_action` so "the user said yes" and "the system then did X"
  are never conflated into one row transition.

## Scheduler

`app/core/scheduler.py` (APScheduler) promotes already-Green, already-manual actions to running
on an interval, with a master kill switch (`background_scheduler_enabled`) that reverts to
fully-manual instantly with no data-model change:

| Job | Interval |
|---|---|
| GitHub sync | 24h |
| Job-board feed polling | 6h |
| Weekly digest generation | 7d |
| Gmail sync | 6h |
| Calendar sync | 6h |

Every scheduled run carries the same audit trail a manual click would (`trigger="scheduled"` in
its evidence), and every entry point binds its own `task_id` the same way a manually-triggered
background task does — the scheduler isn't a special case for tracing purposes.

## The eval harness's isolation from production

`evals/` is a separate tool that imports *from* `backend/` (never the reverse) and runs against
its **own** dedicated Postgres database (`evals/db.py` derives its name from `DATABASE_URL` and
creates/drops it fresh every run) — eval data never touches the real `personal_agent` database.

This mattered concretely once: the LLM cost guard (`SpendGuardedProvider`) is gated behind an
explicit `start_cost_guarded_task()` that only the real app's background-task entry points call
— never the eval harness's own `record_llm_calls()` (used only for the harness's *own* cost
reporting). If the guard were keyed off the same mechanism the harness already sets, an eval
`--live` run would start writing real rows into, and could trip the cap on, the production
`LLMSpendLedger` through `db_base.async_session_factory` — which always points at the real
database regardless of which one the harness itself is using. Keeping the two mechanisms
separate is what prevents that.
