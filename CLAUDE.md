# Personal AI Agent — Project Brief

Read this file fully before doing any work in this repo. This is the standard every piece of work in this project is held to. Do not skip steps to move faster — this project is meant to be excellent, not merely finished.

## Philosophy

> AI researches. AI verifies. AI prepares. AI recommends. Human approves. AI executes only through authorized/allowed interfaces.

The system must never say "this job looks good." It must say something like: "This job is an 87% match because the description requires Python, PyTorch and computer vision, which are present in the profile. The posting was verified from the employer's source 2 hours ago. One uncertainty: the salary isn't published."

Every claim the system makes to the user must be traceable to evidence. If evidence isn't available, the system says "I don't know" — it never fills a gap with a guess.

## Non-negotiable standards

- **No shortcuts.** An unfinished feature is labeled unfinished, never faked as done.
- **No LLM for deterministic work.** Dates, permissions, rate limits, deduplication, auth, validation, DB operations, policy enforcement — plain code. LLMs are for understanding, reasoning, summarization, drafting, classification, research synthesis.
- **Every risky action is Green / Yellow / Red.** Green = automatic. Yellow = user confirms. Red = explicit confirmation + a second independent check. Anything sent externally (email, posts, applications) is at least Yellow.
- **Least privilege everywhere.** Every integration/agent has an explicit CAN / CANNOT list.
- **No secrets in code.** Env vars / secrets manager only. `.env` always gitignored.
- **Every feature ships with tests.** Not "add later."
- **Every commit is a real, working checkpoint.** Small, well-described, never breaks the build.
- **Audit everything.** What, why, evidence, risk level, user decision, result.
- **Design matters.** This is meant to look and feel like a considered product, not a CRUD scaffold — consistent design system, real empty/loading/error states, no unstyled default forms.

## Build order (do not skip ahead)

1. **Foundation** — repo structure, FastAPI backend, Postgres + SQLAlchemy + Alembic, auth (OAuth2, least privilege), React+TS frontend shell with a real design system, logging, secrets management, config.
2. **Personal Profile Engine** — structured profile, skill version history with evidence, preference manager, embeddings/RAG groundwork.
3. **Research Engine** — source-tier hierarchy (official > government > docs > reputable secondary > forums-as-anecdote-only), citations, confidence scoring, deduplication, fact-checking. Must be solid before anything else consumes it.
4. **"Ask your agent" semantic search** — natural-language search across profile, research, and (once connected) email/applications. Sits on top of the Research Engine's embeddings.
5. **Gmail integration** — OAuth, read-only first, then classification/summarization, then drafts (fact-checked, per the response-check pipeline), then sending only after extensive testing and always behind explicit approval.
6. **Career Intelligence** — job discovery, weighted match scoring (never keyword-only), employer verification, fraud/scam detection, application tracker, resume tailoring (diff view, not silent rewrite), cover-letter generation (fact-checked), ATS compatibility checker.
7. **LinkedIn / GitHub / Fiverr / Indeed integrations** — official APIs / authorized channels ONLY. No scraping or stealth browser automation — these platforms explicitly prohibit it.
8. **Calendar + Interview Agent** — including interview practice mode with structured, scored feedback.
9. **Reporting** — weekly digest (in-app) + exportable PDF version.
10. **Safety engineering + red-team testing** — deliberately try to break the system (prompt injection, malicious emails, "ignore previous instructions," "apply to everything," "delete everything") before trusting it with anything real.
11. **Autonomous mode** — only after everything above is solid, only up to explicitly approved autonomy levels, never unlimited authority over the user's identity or accounts.

Each phase is load-bearing for the ones after it — don't jump ahead because something is more interesting.

## Tech stack

This should feel like a modern, considered product — not a bootcamp CRUD app. Specifics:

**Backend**
- Python + FastAPI, fully async (async def routes, async SQLAlchemy 2.0 sessions — no blocking calls in request handlers)
- Pydantic v2 for all request/response schemas and settings
- PostgreSQL + pgvector (for embeddings/RAG), accessed via SQLAlchemy 2.0's async ORM + Alembic migrations
- Redis for caching and as the Celery/APScheduler broker for background jobs
- LangGraph for agent orchestration (controlled, stateful workflows — not a free-form agent loop)
- structlog for structured, queryable logs (not raw print/basic logging)
- Testing: pytest + pytest-asyncio, with real test coverage, not token tests
- Linting/formatting: ruff + mypy, wired into pre-commit hooks

**Frontend**
- React + TypeScript, built with Vite (fast dev server, instant HMR)
- TailwindCSS + shadcn/ui (Radix primitives) for a real, consistent design system — no default unstyled HTML forms
- TanStack Query for server state (loading/error/stale states handled properly, not ad-hoc useEffect fetches)
- Zustand for lightweight client state where needed
- Framer Motion for purposeful micro-interactions (not gratuitous animation)
- A command palette (Cmd/Ctrl+K) for fast navigation, dark/light theme support, and real empty/loading/error states on every screen
- Testing: Vitest + Playwright for critical flows

**Dev environment**
- Docker Compose for local Postgres + Redis so setup is one command, not manual installs
- `.env.example` always kept current; secrets never touch the repo

**Auth**: OAuth 2.0, least-privilege scopes per integration.

## Working style

- Explain what you're about to do before doing it, especially for anything touching auth, external APIs, or data handling.
- Surface trade-offs on real design decisions rather than silently picking one.
- Ask rather than assume when a requirement is ambiguous — this system will eventually touch real email, real applications, real accounts.
- Before starting a phase, restate the plan for that phase and wait for approval.
