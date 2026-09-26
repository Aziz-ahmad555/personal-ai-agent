# Personal AI Agent

[![CI](https://github.com/Aziz-ahmad555/personal-ai-agent/actions/workflows/ci.yml/badge.svg)](https://github.com/Aziz-ahmad555/personal-ai-agent/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)

A personal, single-user agent that researches, verifies, and prepares — a human always approves before anything executes. See [CLAUDE.md](CLAUDE.md) for the full philosophy, build order, and standards this project is held to.

**Backend test coverage:** 83% (measured 2026-09-26 via `pytest --cov=app`, full suite — not auto-updated here; CI computes and prints the current number on every run, in the job summary).

**Phase 1: Foundation**, **Phase 2: Personal Profile Engine**, **Phase 3: Research Engine**, **Phase 4: Semantic Search** ("Ask your agent"), and **Phase 5: Gmail integration — read-only stage** are done. **Phase 6: Career Intelligence** is done — job discovery, employer verification + fraud/scam detection, weighted match scoring, the application tracker, resume tailoring (reviewable diff), fact-checked cover letters, and the ATS compatibility checker. **Phase 7: LinkedIn/GitHub/Fiverr/Indeed** is done for what's buildable: GitHub is fully integrated (connection, repo import as skill evidence, and a recruiter-readiness review, all read-only; see below), and LinkedIn, Indeed and Fiverr are marked explicitly **unavailable** on `/integrations` — no authorized API access exists for a personal developer account, and scraping isn't an authorized channel. **Phase 8: Calendar + Interview Agent** is in progress — sub-step 1 (Calendar connection, read-only; see below) is done; reading events, interview/deadline detection, and the interview practice mode are not built yet.

### Phase 8, sub-step 1: Calendar connection, read-only

The `/calendar` page connects the account's primary Google Calendar, read-only (`calendar.events.readonly`). It reuses the same Google Cloud project and OAuth client as Gmail (`GOOGLE_CLIENT_ID`/`SECRET`), but is its **own, independently revocable connection** — its own callback path, its own state-token type (`calendar_oauth_state`, distinct from Gmail's and GitHub's, so one integration's OAuth state can never be replayed against another's callback), and its own row in the database. Disconnecting Calendar never touches Gmail, and vice versa.

Mirrors the connection pattern established by Gmail and refined by GitHub: encrypted tokens at rest (reusing `app.gmail.crypto`, already generic over which integration owns the token), a distinct `ReauthRequiredError` when the refresh grant is dead, and audited connect/disconnect (green) with a real revoke call to Google on disconnect that reports honestly whether Google actually confirmed it rather than assuming success. Added to the `/integrations` overview alongside GitHub and Gmail.

Verified against the real backend and Postgres (not just the test suite): the OAuth-start endpoint returns a correctly formed `accounts.google.com` URL using the account's actual `GOOGLE_CLIENT_ID` and the redirect URI configured in Google Cloud Console, and the migration applies cleanly. The real Google consent flow (signing in and granting access) is the user's own action and wasn't completed by the agent.

Not built yet: reading events, interview/deadline pattern detection (sub-step 2), and the interview practice mode with generated questions and scored feedback (sub-step 3, deferred — needs the LLM).

### Phase 7, sub-step 3: GitHub recruiter-readiness review (read-only)
The `/github` page reviews each of your own public repositories for what a visitor looks for, plus your GitHub profile, and says what to fix first. **Deterministic code, no LLM, and no score**: every check is pass, warn, fail or **unknown**, with the evidence it used and a link to it. The review is computed on demand from the last sync's snapshot, so viewing it makes no GitHub requests (a test asserts that).

**Checks per repo:** description (20+ characters); README present; README explains the project (150+ words and a real intro paragraph), says how to run it (an install/usage section or run commands), has a screenshot/GIF/demo, has a code example; license (a license file GitHub can't classify still counts); topics; automated tests (test files or folders); CI (GitHub Actions, CircleCI, GitLab, Travis, Azure, Jenkins); `.gitignore`; no secret-looking files committed (`.env`, `*.pem`, `id_rsa*`, `credentials.json`; example/sample files excluded), judged by file name only; no junk committed (`.DS_Store`, `__pycache__`, `node_modules`, `*.part`); a push in the last 12 months; not a placeholder name. **Account checks:** name, bio, location or website, a profile README repo (`you/you`), and how many repos have a description, README and license. Forks, archived repos and repos that couldn't be read aren't reviewed, and say why. Severity: no license or README and committed secrets are failures; missing tests and CI are warnings.

**Unknown is a real answer.** Missing data is never turned into a pass or a fail: a repo synced before these checks existed shows "Sync again to include this", a README that couldn't be read says why, a truncated file list makes "no license/tests" unknown rather than missing. A hit (say a `.env` in the root) is always reported even from old data; only an *absence* needs complete data. When there's no README, its four content checks are left out rather than counted twice.

**"Fix first"** ranks failures before warnings, then by how much the check matters (a committed secret outranks everything). **"Copy as checklist"** exports the review as Markdown (`[x]` pass, `[ ]` needs work, `[?]` unknown), audited as a green export; nothing is sent anywhere. The page lists what the review can't see: pinned repos (they need a different API), README quality beyond structure, test contents (a `debug_test.py` script counts by name), private repos, unrecognised CI systems.

**What the sync now records** (no extra requests except one README read per repo): the notable paths from the file tree it already fetches (tests, CI, secret and junk names, capped), README *structure* (word count, headings, code blocks, images; never the text), and your public profile fields from the `/user` response it already makes. Found by running it on a real account: no license on any of the three repos, no README on the flagship one, and a partial-download file committed in another. Not built yet: the optional LLM critique of README writing (sub-step 4).

### Phase 7, sub-step 2: GitHub repo import and skill-evidence proposals (read-only)
"Sync now" on `/github` reads the connected account's **own public repositories** and proposes profile skills they evidence. **Nothing reaches the profile until the user accepts a proposal**; there is no LLM anywhere in this path, so the same repos always give the same proposals.

**What a sync reads** (about 5 requests per repo, capped at 300 per sync, with backoff on 5xx and bounded waits on rate limits): the repo list via `/users/{login}/repos` (not `/user/repos`, which for a GitHub App token with no installation only returns repos the app can reach); per repo its language bytes, the commit count and dates GitHub attributes to the account (two requests via the `Link` header, never the full history), the whole file tree in one request to find dependency manifests (`requirements*.txt`, `pyproject.toml`, `package.json`, up to two folders deep, skipping `node_modules`/`.venv`/build output, since real projects keep them in `backend/` and `frontend/`), and about 90 days of public activity. Forks and archived repos are listed but not read and never count as evidence. A repo is all read or not read, never half; anything unreadable is a warning on the run, and a run that dies is recorded as failed (an orphaned "running" run is reported failed after 10 minutes).

**How evidence is judged.** A language needs at least 5 KB in a repo to count; Jupyter Notebook bytes are never counted as Python (notebook JSON dwarfs the code); file types that aren't skills (Dockerfile, Makefile) are not proposed; dependencies map to skills through a fixed table (`app/github/catalog.py`) and are matched to your existing skills through the same alias table as match scoring. **Attribution is stated, not assumed**: a repo you own but with no commits attributed to your account (for example commits made under an email not linked to GitHub) is kept as clearly-labelled "owned, no attributed commits" evidence, and "couldn't look up commits" is never shown as zero. Everything left out, and why, is listed under "Not proposed, and why".

**Accepting** is a Yellow action through the audit system's real workflow (request, your decision, result). It adds a skill version through the profile's own code path (so embeddings and history stay consistent), with evidence text built only from recorded facts and shown to you beforehand. An existing skill keeps its current level unless you pick another; **a new skill needs you to choose the level**, since byte counts can't say how proficient anyone is. Dismissing records a rejected decision and changes nothing. A dismissed or accepted proposal isn't re-asked when its repos merely grow; only new evidence (another repo, a new way it shows the skill) makes a new proposal. Disconnecting can also delete the synced snapshot; skills you already accepted are yours and stay.

Found by running it on a real account: dependency files are usually not in the repo root; a notebook-heavy repo would have made a "% of code" call the owner a notebook developer; one repo had no attributed commits at all; and the test database (which doesn't expire objects) hid a failure-path bug that a real database error exposed, now covered by a regression test. Not built yet: the recruiter-readiness analysis (sub-step 3) and the optional LLM README critique (sub-step 4).

### Phase 7, sub-step 1: GitHub connection (read-only) and the Integrations page
Phase 7 covers GitHub only. **LinkedIn, Indeed and Fiverr are deliberately not integrated**: there's no authorized API access for a personal developer account, and scraping or browser automation isn't an authorized channel. They appear on the `/integrations` page as "Unavailable" with that reason, and no route or code exists for them (a test asserts it).

GitHub connects through a **GitHub App** (user authorization flow), not an OAuth App, because a classic OAuth App can't be read-only for private repos (its `repo` scope includes write). The app is registered with **no permissions** beyond the mandatory `metadata:read`, so it reads public information only, and the callback **refuses to connect** (and revokes the token) if GitHub reports any write or admin permission on an installation, so it stays read-only even if the app is later given more access. Tokens are Fernet-encrypted at rest (same key as Gmail) and never returned by any endpoint or written to the audit log. Expiring tokens are supported: the refresh token rotates on every use and the new one is stored each time; a refused refresh marks the connection `needs_reauth`. Disconnecting revokes the token at GitHub and clears it locally, and says honestly when GitHub couldn't confirm the revocation. Connect, disconnect and failed attempts are audited (green). All GitHub HTTP in tests is mocked.

**Registering the GitHub App** (once): GitHub > Settings > Developer settings > GitHub Apps > New GitHub App. Callback URL `http://localhost:8000/github/oauth/callback`; untick Webhook > Active; leave every permission at "No access"; keep "Expire user authorization tokens" ticked; "Only on this account". Generate a client secret, then set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env` (see `.env.example`).

Not built yet: importing repositories as profile evidence (sub-step 2), the recruiter-readiness analysis (sub-step 3), and the optional LLM README critique (sub-step 4). Also fixed here: the Gmail and GitHub pages cleared their OAuth error from the URL before it could render, so a failed connect showed no error.

### Public landing page (`/`)
`/` is a public page with a 3D scene per section (evidence graph, converging citations, trust ladder, risk gauge); the app's dashboard moved to `/dashboard`. Logged-in users reach the page from the footer link and the command palette ("Go to home page"), and see "Open the app" instead of "Sign in". All scenes draw into **one** persistent `@react-three/fiber` `<Canvas>` through drei `<View>`s (one WebGL context, page scrolls natively, only visible scenes render); text and score readouts are real HTML. Scroll drives the citation lock-in, the ladder parallax and the gauge needle, which settles on the risk tier whose copy is in view. Under `prefers-reduced-motion` the scenes draw a static frame, with no auto-rotate or scroll-driven camera moves. If WebGL is unavailable, the context is lost, or the canvas throws, each section falls back to a static SVG (`/?webgl=off` forces this for checking). The page is lazy-loaded so the app bundle doesn't carry three.js, fonts are self-hosted via fontsource, and its palette is scoped to `.landing` so the app theme is untouched. Copy lives in `frontend/src/features/landing/copy.ts`; lines outside the brief's verbatim text are drafted in the same voice and still to be compared with the design prototype. The evidence card is labeled as an example, since it's illustrative rather than a real posting. React is pinned to 19.2.8 because `@react-three/fiber` 9 doesn't yet support React 19.3.
### Phase 6, sub-step 7: Career Intelligence — ATS compatibility checker
"ATS compatibility" on a job reports how the resume that would be sent is likely to fare when an applicant-tracking system parses it and matches it against the posting. **Mostly plain, deterministic code — no LLM**, so no quota risk — and read-only: it reports, never edits. No ATS vendor publishes its scoring, so it checks well-documented pitfalls and keyword coverage and says so; every result carries a "what this can't tell you" list (it can't predict a specific employer's ranking, matches skills by name and common aliases, and reads the resume text this app produces, not a PDF or Word file).
**Keyword coverage** runs against the posting's quote-verified requirements (from the match, which is required first so the check stays instant). Each skill is `in_context` (used in the summary or a role — the strongest place), `listed_only` (only in the Skills list: findable, but weaker, and it points at the roles its evidence links it to), or `gap` (with the reason — no evidence recorded, or not in the profile — and never suggested for insertion). Coverage is `null`, not 0, when the posting listed no skills. **Structure** covers standard section headings, contact details (the profile stores none, so this honestly fails until you add your own), date presence/consistency/newest-first order, a sensible length, and characters that trip parsers — which the normal Markdown export itself has (em/en dashes, middle dots, `#` markers).
The **ATS-safe export** is plain text with uppercase headings and no Markdown, symbols replaced by plain equivalents (accented letters kept so names aren't misspelled), verified to pass the hazard check the Markdown export fails. It checks the resume as it stands for the job: the tailored draft with only its accepted changes if any were accepted, else the profile-built one. Found while building it: a phone-number pattern that missed "(555) 123-4567", and that a run of years like "2019 2020 2021" must not count as a phone number. Green risk; each check and export is audit-logged. Not built: reading PDF/Word files, vendor-specific scoring, auto-fixing, and checking a pasted external resume.

### Phase 6, sub-step 6: Career Intelligence — fact-checked cover letters
"Cover letter" on a job drafts a letter in which **every factual sentence traces to evidence**, then hands it to you to review paragraph by paragraph; nothing goes in the letter until you accept it and nothing is ever sent. One LLM call writes the letter as sentences that each declare their support — one of your roles, an evidence-backed skill, your summary, or a verbatim quote from the posting (or "framing": greetings and transitions that must contain no facts). Then **plain code fact-checks every sentence** (`app/career/cover_verify.py`): citations must resolve; posting quotes must appear verbatim; a number must come from the cited *profile* item (a posting's "5+ years" can't become "I have 5 years"); a skill may only be claimed if evidence backs it for that role or citation; new proper names are rejected; framing may contain no numbers, skills, or names. The rule that matters most: a skill the posting wants but your profile lacks can't appear in the letter in any form — otherwise "I have Kubernetes experience", citing the posting's own words, would pass a quote check while being false.
Unsupported sentences are dropped and listed with their reasons; a body paragraph left with no verified facts is dropped; if nothing survives, the run fails with a clear message rather than producing filler. Skills the posting wants that you have no evidence for are listed as gaps, never claimed. "Where this comes from" traces each sentence to its source. You may **edit** any paragraph: your own wording is stored beside the fact-checked original, badged "Edited by you — not fact-checked", restorable, and the export notice says how many paragraphs are your own unchecked wording (audit entries record that an edit happened, never the text). The salutation is a neutral "Dear Hiring Team," (a recipient is never guessed), the sign-off uses the profile's name if it has one, and no contact details are invented. Export is plain text of accepted paragraphs only. Green risk; drafting, each decision, edit, export, and delete are audit-logged. Stale detection, orphaned-run handling, and the base-resume assembly are shared with resume tailoring. Not built: the ATS checker, PDF export, and sending a letter anywhere (which would be a Yellow action).

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
The `/career` page also covers adding postings (paste or URL), the employer/fraud check, and job-board feed management.

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

## Privacy

This is a single-user, self-hosted agent: everything it stores lives in **your own local Postgres database** (the Docker Compose container above), never a third-party server this project controls. Nothing leaves that database except the specific third-party call a feature actually makes — Tavily for a search, Voyage for an embedding, Gemini/Anthropic/Groq for an LLM step, or the Gmail/Calendar/GitHub APIs for those integrations — and only the minimum that call needs, never a bulk export.

**What's stored:** your profile (bio, work history, education, skills and their evidence history), preferences, research queries/claims/sources, career data (postings, matches, employer/fraud checks, applications, tailored resumes, cover letters, practice sessions), a weekly digest snapshot, and — once connected — Gmail message metadata + plain-text body (no raw MIME, no attachments; see Phase 5 above), a read-only snapshot of Calendar events, and GitHub repo/skill-evidence metadata. Every risky action taken or proposed is separately recorded in the audit trail (`AuditLog`: what, why, evidence, risk level, decision, result) via `app/audit/`.

**What's specifically protected:** passwords are hashed (never stored or logged in plain text); Gmail/Calendar/GitHub OAuth tokens are Fernet-encrypted at rest (`TOKEN_ENCRYPTION_KEY`) and never returned by any endpoint or written to a log or the audit trail. A real secrets scan (regex-based, against the full git history, not just the working tree) has been run against this repo and found no live credentials.

**Retention:** nothing expires automatically. Gmail's first sync is bounded to a rolling window (`GMAIL_SYNC_WINDOW_DAYS`, data-minimization by default) rather than the whole mailbox; everything else persists until you remove it.

**Deleting your data**, two ways:
- **Per integration**: each of Gmail/Calendar/GitHub's own `/connection` DELETE endpoint disconnects and revokes the grant at the provider (Google/GitHub), with an explicit choice to also purge that integration's synced data — never a silent default either way.
- **Everything, for real**: `POST /auth/delete-account/request` returns a live evidence snapshot (real row counts, real connection statuses) as a pending red-risk approval; `POST /auth/delete-account/{id}/decide` with `{"approved": true}` is your second, explicit confirmation — it re-verifies that snapshot against the database at that exact moment (refusing if anything's changed since the request, rather than deleting against stale evidence), then revokes every connected integration at its provider and deletes every row this account owns, all in the same call. This is a genuine full-account wipe (`app/auth/account_deletion.py`), not a per-integration purge repeated three times. One honest tradeoff: the account's own audit-log rows are themselves owned by the account, so they're deleted along with everything else — the one thing that outlives a completed deletion is a structured log line written just before it, in the app's own log output, outside Postgres entirely.

## CI

`.github/workflows/ci.yml` runs on every push and PR, two independent jobs: **backend** (`ruff check`, `ruff format --check`, `mypy app` strict, `pytest --cov=app` — the coverage number lands in the run's own job summary) and **frontend** (`oxlint`, `tsc -b`, `vitest run`, `npm run build`). Both must pass; neither touches a real database, Redis, or any external API — the backend suite runs entirely against in-memory SQLite (see `tests/conftest.py`), the frontend suite mocks every network call.

`.github/workflows/evals.yml` is `workflow_dispatch`-only — it never runs on push, since a `--live` run makes real Tavily/LLM calls (real cost). It spins up its own throwaway Postgres+pgvector service container for the retrieval bucket; `--live` additionally needs `TAVILY_API_KEY`/`VOYAGE_API_KEY`/`GROQ_API_KEY`/etc. added as repository secrets (Settings → Secrets and variables → Actions) — without them it still runs everything else in `--replay` mode for free.

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

Run tests (add `--cov=app --cov-report=term` for a coverage report, same as CI):

```bash
pytest
```

Lint / type-check / format:

```bash
ruff check .
ruff format --check .
mypy app
```

**Pre-commit hooks** (`backend/.pre-commit-config.yaml` — ruff, ruff-format, mypy, trailing-whitespace, and friends): the config ships in the repo, but installing the actual git hook is a one-time local step `pip install -e ".[dev]"` doesn't do for you:

```bash
pre-commit install
```

Run once per clone, from `backend/`. After that, every `git commit` runs these checks on the changed files automatically; CI (`.github/workflows/ci.yml`) runs the same checks again on every push as the actual gate, so a skipped or bypassed local hook still can't reach `main` unnoticed.

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
