# Changelog

## v1.0.0 — 2026-10-05

First release. A personal, single-user AI agent that researches, verifies and prepares, with a human approving anything risky. Every claim it makes should be traceable to evidence; where the evidence isn't there, it says so.

### What it does

- **Profile Engine:** structured profile (bio, work history, education, skills), with skill versions over time, each backed by recorded evidence. Embedded via Voyage AI for retrieval.
- **Research Engine:** a LangGraph pipeline (search → collect → dedupe → extract → report) that turns a question into a sourced answer. Every claim carries a verbatim citation re-verified against the fetched page, a deterministic confidence score (source tier, corroboration, recency), and an honest "uncertainties" list.
- **Semantic Search:** one cross-corpus query (pgvector) over the profile and every research claim and source, resolved back to real rows.
- **Career Intelligence:** job discovery (manual capture, plus Greenhouse/Lever/Ashby/USAJobs board polling), employer verification and fraud/scam detection, weighted match scoring based on evidence rather than keywords, an application tracker, resume tailoring as a reviewable diff, fact-checked cover letters, an ATS compatibility checker, and interview practice with per-question verdicts and written feedback (no numeric score).
- **Gmail (read-only):** OAuth2 with `gmail.readonly` only, encrypted tokens, incremental sync with automatic backfill fallback.
- **GitHub (read-only):** repo import as skill evidence (deterministic, no LLM) and a recruiter-readiness review of your own public repositories.
- **Calendar (read-only):** syncs your primary calendar and classifies each event as an interview, a deadline or other, using deterministic phrase and domain matching that shows the evidence behind each result. It proposes links to tracked applications, and you can correct any classification. Calendar never writes to Google and has no reminders yet (see [Limitations](#limitations-and-roadmap)).
- **Reporting:** a weekly digest covering career, research, Gmail, GitHub and Calendar activity, with "needs attention" signals, exportable as PDF.
- **Audit and approval:** every risky action is Green (automatic), Yellow (you confirm), or Red (you confirm, and the server independently re-verifies before honoring it).
- **Scheduling:** read-only sync and digest jobs can run on a schedule, with a kill switch and a reauth banner.
- **Privacy and data control:** Fernet-encrypted OAuth tokens, a per-task LLM token limit and daily spend cap, per-integration disconnect-and-purge, and a two-step full-account deletion.

LinkedIn, Indeed and Fiverr are not integrated, on purpose: none offer authorized API access for a personal developer account, and scraping or browser automation would violate their terms.

### Results

Measured from the eval harness (`evals/run_all.py`). Methodology and full breakdown: [docs/evaluation.md](docs/evaluation.md).

| Suite | Result | What it means |
|---|---|---|
| Profile/RAG retrieval | **87.5% hit@1** (14/16), mean score 0.9375 | Given a query, does the right profile/research chunk come back top-ranked? |
| Research Engine (citation correctness) | **4/4** | A fabricated citation marker is stripped before storage; a real one always survives |
| Career Intelligence (hallucination precision/recall) | **13/13** | Cover-letter/resume drafts: every genuinely-grounded sentence kept, every hallucinated or injected one caught |
| Approval/audit adversarial set | **25/25** + 1/1 isolation | Prompt-injection and audit-bypass attack cases (7 from the original red-team pass + 18 added for this harness) |
| Live end-to-end injection check | **1/1** | One real draft, real model, real verifier — no hallucinated claim survived |
| LLM-judge calibration | **14/14 (100%)** | The judge's faithful/relevant verdicts agree with hand-assigned human labels on every gold-set example |
| Judge-scored faithfulness/relevance | **15/15** | Scenario grid: faithful+relevant, unfaithful, irrelevant, hedged, contradicted-by-a-second-source, etc. |
| Baseline comparison | 3/3 | See note below — this one doesn't show what you'd expect |
| Backend test suite | **814 passed** | Full suite, `pytest --cov=app` |
| Frontend test suite | **240 passed** | `vitest run` |
| Backend coverage | **84%** | 9,183 statements, 1,509 missed — measured 2026-10-05 |

Cost of a full `--live` eval run: an estimated **$0.0041**, about 26 seconds.

### Known limitations

These are documented decisions and open gaps, as listed in the README:

- **Refresh-token reuse.** JWT refresh tokens aren't rotated or tracked, so a captured one stays valid until expiry. Accepted for a single-user, local-only app where the realistic threat model doesn't include a network attacker capturing this device's token — but this **must** be fixed before any multi-device or public deployment. Documented, with a regression test that currently records (not enforces) the gap, in `app/auth/router.py`'s `refresh` docstring.
- **A citation-marker fabrication is caught; an uncited assertion isn't.** `report.py`'s marker-stripping drops any sentence whose `[claim_id]` doesn't resolve — but if a model asserts a fact with *no* citation marker at all, nothing currently catches that. A separate, harder problem the module doesn't attempt to solve yet.
- **Retrieval depends on a live embeddings API.** The eval harness's own most recent runs hit a transient Voyage outage; `/search` fails clearly (503) rather than guessing when this happens, but it does mean search has a real external dependency with no offline fallback.
- **The one-active-practice-session lock is in-process only.** `asyncio.Lock`, not a distributed lock — correct for a single-instance deployment (which this is), would need rework before running as more than one worker.
- **Calendar has no reminders or notifications, and never writes to your calendar** (read-only by design). Event sync and interview/deadline classification are built; application links are proposals you can correct.
- **The optional LLM README critique** for the GitHub recruiter-readiness review isn't built.

### Not in v1.0.0

v2 backlog: LinkedIn tooling, Slack/WhatsApp integrations, a voice interface or mobile app, multi-user accounts, fine-tuning a custom model.
