# Design decisions

Short records of the real decisions behind this project's architecture — what was chosen, why,
and what it costs. Two of these (Tavily, Voyage) are framed around the actual technical fit
rather than a comparison shootout that never happened; that's stated explicitly where it
applies, rather than implied otherwise.

## 1. Groq as the default LLM provider

**Decision:** `LLM_PROVIDER=groq` is the default, with Gemini and Anthropic available as drop-in
alternatives behind the same `LLMProvider` interface.

**Why:** Gemini was the original default. In real use, its free tier proved too tight: a hard
20-requests/day cap at the time this was evaluated, on top of a same-day 5-requests/minute wall
and sustained server overload. None of that is a fit for a pipeline that makes several LLM calls
per research query or per career-intelligence action. Groq's free tier is far more generous, and
switching providers touches exactly one setting — no pipeline code changes, because every
provider is written against the same `generate_structured()` Protocol.

**Tradeoff accepted:** Groq's own model catalog and rate limits can change too (it already has,
once, mid-project) — the provider abstraction exists specifically so that's a config change, not
a rewrite, if it happens again.

## 2. LangGraph for the Research Engine, not a free-form agent loop

**Decision:** The Research Engine's five steps (search, collect, dedupe, extract, report) are
wired as an explicit LangGraph graph with a typed state dict, not an agent that decides its own
next action in a loop.

**Why:** CLAUDE.md's own standard is "controlled, stateful workflows — not a free-form agent
loop," and the pipeline needs exactly that: each stage has a single, known responsibility, and
every stage's input/output needs to be inspectable for debugging and testing, not hidden inside
one opaque decision loop. A `TypedDict` state that flows node-to-node makes each node
independently unit-testable against a known input shape, and makes "the query failed" a single
readable field (`state["error"]`) that every later node checks and short-circuits on, rather than
an exception surfacing from an unpredictable depth.

**Tradeoff accepted:** the pipeline can't dynamically reorder or skip its own steps — which is
the point. A research query's stages are always the same five, always in the same order.

## 3. The audit/second-check architecture: real enforcement, not a label

**Decision:** Green/Yellow/Red risk levels are enforced in code, not just documented as a
convention — and a Red action's "independent second check" is a server-side function, registered
per action, run at the moment of decision against the row's own stored evidence, never something
the API caller can supply or assert.

**Why:** the first version of this had two real gaps a red-team pass found. First,
`log_action` accepted any risk level with only a string-validity check — nothing stopped a
red-risk action from being recorded as already-completed with no approval step at all. Second,
`second_check_passed` was a plain boolean field in the same `decide` request the same caller
sent — meaning "the independent check passed" was, in practice, whatever the caller claimed. The
fix for both: `log_action` now raises on anything above Green, and `second_check_passed` was
removed from the client-facing schema entirely, replaced by a registry
(`app.audit.second_checks.SECOND_CHECKS`) of real re-verification functions that
`decide_approval` calls itself. A Red action with no registered check can't be approved at all —
deliberately loud (every approval attempt fails) rather than silently unverified.

This was also an explicit two-part decision on *how far* to take "second check": deterministic
server-side re-verification was approved and built now; a human-factor re-authentication step
(re-entering a password before a Red action, say) was explicitly deferred to a later phase rather
than built speculatively.

**Tradeoff accepted:** every new Red action requires writing a real second-check function before
it can ship — there's no "add the risk level now, wire up verification later" path, by design.

## 4. Deterministic verification is the actual prompt-injection defense — not the model

**Decision:** Every LLM output that could contain a fabricated or injected claim is checked
against real, stored evidence by plain code before it's shown to the user or persisted —
`cover_verify.py`, `resume_verify.py`, `practice_verify.py`, `verify_citation_excerpt`. Labeling
untrusted content in prompts (`wrap_untrusted`) is also done, but is explicitly documented as
defense-in-depth, never the load-bearing guardrail.

**Why:** trusting a model to resist adversarial instructions embedded in text it's asked to
process is not a real security boundary — it degrades with phrasing, and there's no way to prove
it holds for inputs not yet seen. A deterministic check ("does this exact quote appear verbatim
in the source," "does this skill have recorded evidence," "does this number appear in the cited
item") is falsifiable, testable, and doesn't depend on the model's behavior at all. The eval
harness's own adversarial set (25 cases) and red-team injection tests exist specifically to prove
this holds even when the attacker controls the source text verbatim — the harder case a simple
citation-format check couldn't catch on its own.

**Tradeoff accepted:** this means every new LLM-generated feature needs its own verifier written
before it ships, not just a well-crafted prompt. Slower to build; the only version of "safe"
that's actually demonstrable rather than assumed.

## 5. LinkedIn, Indeed, and Fiverr are not integrated

**Decision:** Phase 7 covers GitHub only. LinkedIn, Indeed, and Fiverr appear on `/integrations`
explicitly marked "Unavailable," with the reason shown, and no route or code exists for any of
them.

**Why:** none offer authorized API access for a personal developer account — LinkedIn's API is
restricted to approved partners, Indeed's job-posting API requires a publisher agreement, and
Fiverr has no public API at all for this use case. Scraping or browser automation would work
technically but isn't an authorized channel for any of the three, and CLAUDE.md is explicit that
integrations happen through official APIs or authorized channels only — never scraping or
stealth automation, since these platforms explicitly prohibit it in their terms.

**Tradeoff accepted:** the Career Intelligence feature set is missing what's arguably the single
most common job-search platform. There's no technical workaround planned — this stays out of
scope unless an authorized path (an official partner API) becomes available.

## 6. Tavily for search, Voyage for embeddings — the technical fit, honestly stated

**Decision:** Tavily is the Research Engine's search provider; Voyage AI is the embeddings
provider for both the Profile Engine and Research Engine.

**Why, honestly:** these were the starting choices for this project, not the result of an
in-project comparison against alternatives (Brave's search API, OpenAI's embeddings) that
actually happened — this record documents why they continue to fit, not a bake-off. Tavily is
built specifically for LLM/RAG pipelines: it returns per-result metadata (a snippet, a rank)
shaped for exactly the citation-and-tiering pipeline this app builds on top of it, rather than
raw search-engine HTML requiring separate extraction. Voyage's retrieval models are trained
*asymmetrically* — a distinct `input_type` for the document side versus the query side — which
this app actually uses (`embed_texts(..., input_type="document")` when indexing,
`embed_query()` with `input_type="query"` for search), a real quality property a symmetric
embedding model wouldn't offer.

**Tradeoff accepted:** neither choice has been benchmarked against an alternative within this
project. If a future need (cost, rate limits, a specific retrieval quality gap) justifies
switching, that justification will be new evidence gathered at that time — not a retroactive
claim that today's choice was already proven best.
