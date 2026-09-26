"""One-time (re-runnable, but not part of the regular eval run) fixture builder: calls the
real Voyage embeddings API once for a small synthetic corpus and query set, then freezes the
resulting vectors into evals/datasets/retrieval_eval.json so evals/buckets/retrieval.py's
--replay mode never needs a live embeddings call again. Re-run this only if the corpus or
query wording changes, or if the embedding model (settings.voyage_model) changes.
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))

from app.profile.embeddings import embed_texts  # noqa: E402

# --- The synthetic corpus: one eval user's profile + one research query's claims. Owner
# identity is by key here (real UUIDs only exist once evals/buckets/retrieval.py seeds this
# into the eval database) — the eval matches results by these stable keys, not by UUID. ---

CORPUS: list[dict[str, str]] = [
    {
        "key": "bio",
        "owner_type": "bio",
        "text": (
            "Backend engineer with 6 years building Python services on PostgreSQL, focused "
            "on reliability, distributed systems, and clean API design."
        ),
    },
    {
        "key": "exp_acme",
        "owner_type": "work_experience",
        "text": (
            "Senior Backend Engineer at Acme Corp. Built and maintained Python and PostgreSQL "
            "services handling millions of daily requests. Led the migration of a monolith to "
            "a microservices architecture, deployed on Kubernetes."
        ),
    },
    {
        "key": "exp_widget",
        "owner_type": "work_experience",
        "text": (
            "Backend Engineer at Widget Inc. Built REST APIs in Django, integrated Stripe for "
            "payment processing, and wrote comprehensive pytest test suites covering auth and "
            "billing flows."
        ),
    },
    {
        "key": "education",
        "owner_type": "education",
        "text": "Bachelor of Science in Computer Science, State University.",
    },
    {
        "key": "skill_python",
        "owner_type": "skill_evidence",
        "text": "Python: 6 years of professional experience across Acme Corp and Widget Inc.",
    },
    {
        "key": "skill_postgres",
        "owner_type": "skill_evidence",
        "text": "PostgreSQL: 6 years, including schema design and query optimization at scale.",
    },
    {
        "key": "skill_kubernetes",
        "owner_type": "skill_evidence",
        "text": "Kubernetes: deployed and managed production clusters during the Acme Corp microservices migration.",
    },
    {
        "key": "preferences",
        "owner_type": "preferences",
        "text": (
            "Prefers fully remote roles, open to relocation only for an exceptional "
            "opportunity, minimum acceptable base salary is $150,000."
        ),
    },
    {
        "key": "claim_nimbus_experience",
        "owner_type": "claim",
        "text": "Nimbus Data Systems requires 5 or more years of backend engineering experience for this role.",
    },
    {
        "key": "claim_nimbus_remote",
        "owner_type": "claim",
        "text": "Nimbus Data Systems offers a fully remote work culture for this position.",
    },
    {
        "key": "source_nimbus_posting",
        "owner_type": "source_chunk",
        "text": (
            "Nimbus Data Systems is hiring a Senior Backend Engineer, fully remote, USA. "
            "5+ years of backend engineering experience required. Python and PostgreSQL "
            "experience required. Kubernetes experience preferred."
        ),
    },
]

QUERIES: list[dict[str, str]] = [
    {"text": "backend engineer with distributed systems experience", "expected_key": "bio"},
    {"text": "who has hands-on Kubernetes production experience", "expected_key": "skill_kubernetes"},
    {"text": "experience integrating Stripe payments", "expected_key": "exp_widget"},
    {"text": "led a monolith to microservices migration", "expected_key": "exp_acme"},
    {"text": "what degree does this candidate hold", "expected_key": "education"},
    {"text": "python skill evidence and years of experience", "expected_key": "skill_python"},
    {"text": "salary floor and remote work preference", "expected_key": "preferences"},
    {"text": "postgresql query optimization experience", "expected_key": "skill_postgres"},
    {"text": "django rest api experience", "expected_key": "exp_widget"},
    {"text": "does nimbus data systems require 5 years of experience", "expected_key": "claim_nimbus_experience"},
    {"text": "is the nimbus data systems role fully remote", "expected_key": "claim_nimbus_remote"},
    {"text": "raw text of the nimbus data systems job posting", "expected_key": "source_nimbus_posting"},
    {"text": "pytest test suite coverage for auth and billing", "expected_key": "exp_widget"},
    {"text": "candidate's minimum acceptable base salary", "expected_key": "preferences"},
    {"text": "computer science degree and university", "expected_key": "education"},
    {"text": "six years of professional python experience", "expected_key": "skill_python"},
]


async def main() -> None:
    # Two batched calls total (not one call per item/query) — this account has no payment
    # method on file, so Voyage caps it at 3 requests/minute; a loop of individual calls
    # blows through that immediately.
    corpus_texts = [c["text"] for c in CORPUS]
    corpus_vectors = await embed_texts(corpus_texts, input_type="document")
    if corpus_vectors is None:
        print("FAILED: embeddings unavailable (check VOYAGE_API_KEY) — no fixture written.")
        return

    query_texts = [q["text"] for q in QUERIES]
    query_vectors = await embed_texts(query_texts, input_type="query")
    if query_vectors is None:
        print("FAILED: could not embed queries — no fixture written.")
        return

    out = {
        "corpus": [{**c, "embedding": vec} for c, vec in zip(CORPUS, corpus_vectors, strict=True)],
        "queries": [{**q, "embedding": vec} for q, vec in zip(QUERIES, query_vectors, strict=True)],
    }
    out_path = Path(__file__).resolve().parents[1] / "datasets" / "retrieval_eval.json"
    out_path.write_text(json.dumps(out, indent=2))
    print(f"Wrote {out_path} ({len(CORPUS)} corpus items, {len(QUERIES)} queries).")


if __name__ == "__main__":
    asyncio.run(main())
