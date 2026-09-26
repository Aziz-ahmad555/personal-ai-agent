"""Profile/RAG retrieval eval — real cosine-distance search (pgvector, real Postgres, see
evals/db.py) against a frozen, real-embeddings corpus (evals/datasets/retrieval_eval.json,
generated once by evals/scripts/build_retrieval_fixture.py). Scores hit rate (is the expected
item the top-1 result) and MRR (how far down the ranking it landed when it isn't).

Runs app.search.service.run_search itself, not a reimplementation — the one thing monkeypatched
is embed_query, so a replay run never calls the real Voyage API (the frozen vectors already
came from a real one-time call); in --live mode nothing is monkeypatched and a fresh real call
embeds each query text.
"""

import json
import uuid
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.models import User
from app.profile.models import (
    Education,
    Preferences,
    Profile,
    ProfileEmbedding,
    Skill,
    SkillVersion,
    WorkExperience,
)
from app.research.models import (
    ResearchClaim,
    ResearchEmbedding,
    ResearchQuery,
    ResearchQuerySource,
    ResearchSource,
)
from app.search import service as search_service
from evals.config import DATASETS_DIR
from evals.report import BucketReport, TaskResult


def _load_data() -> dict[str, Any]:
    data: dict[str, Any] = json.loads((DATASETS_DIR / "retrieval_eval.json").read_text())
    return data


async def _seed(db: AsyncSession, corpus: list[dict[str, Any]]) -> tuple[uuid.UUID, dict[str, str]]:
    """Creates one eval user with the full corpus seeded, and returns (user_id, key ->
    real owner_id) so queries can check "did the expected key's real row come back"."""
    user = User(email=f"eval-retrieval-{uuid.uuid4()}@example.com", hashed_password="x")
    db.add(user)
    await db.flush()

    profile = Profile(user_id=user.id, headline="Backend Engineer")
    db.add(profile)
    await db.flush()

    query = ResearchQuery(user_id=user.id, query_text="Nimbus Data Systems", status="completed")
    db.add(query)
    await db.flush()

    owner_ids: dict[str, uuid.UUID] = {}
    by_key = {c["key"]: c for c in corpus}

    if "bio" in by_key:
        owner_ids["bio"] = profile.id  # bio's owner_id IS the profile id, per app.search.service

    if "exp_acme" in by_key or "exp_widget" in by_key:
        for key in ("exp_acme", "exp_widget"):
            if key not in by_key:
                continue
            exp = WorkExperience(
                profile_id=profile.id,
                company="Acme Corp" if key == "exp_acme" else "Widget Inc",
                title="Senior Backend Engineer" if key == "exp_acme" else "Backend Engineer",
                start_date=date(2020, 1, 1),
            )
            db.add(exp)
            await db.flush()
            owner_ids[key] = exp.id

    if "education" in by_key:
        edu = Education(profile_id=profile.id, institution="State University")
        db.add(edu)
        await db.flush()
        owner_ids["education"] = edu.id

    skill_keys = (
        ("skill_python", "Python"),
        ("skill_postgres", "PostgreSQL"),
        ("skill_kubernetes", "Kubernetes"),
    )
    for key, skill_name in skill_keys:
        if key not in by_key:
            continue
        skill = Skill(profile_id=profile.id, name=skill_name)
        db.add(skill)
        await db.flush()
        version = SkillVersion(skill_id=skill.id, level="advanced", evidence=by_key[key]["text"])
        db.add(version)
        await db.flush()
        owner_ids[key] = version.id

    if "preferences" in by_key:
        prefs = Preferences(user_id=user.id)
        db.add(prefs)
        await db.flush()
        owner_ids["preferences"] = prefs.id

    for key in ("claim_nimbus_experience", "claim_nimbus_remote"):
        if key not in by_key:
            continue
        claim = ResearchClaim(
            query_id=query.id,
            claim_text=by_key[key]["text"],
            status="single_source",
            confidence_score=60,
            confidence_rationale="Eval fixture claim, seeded directly, not via scoring.py.",
        )
        db.add(claim)
        await db.flush()
        owner_ids[key] = claim.id

    if "source_nimbus_posting" in by_key:
        source = ResearchSource(
            normalized_url="nimbus.example.com/careers/senior-backend-engineer",
            original_url="https://nimbus.example.com/careers/senior-backend-engineer",
            domain="nimbus.example.com",
            tier="official",
            tier_rationale="employer's own domain",
            title="Senior Backend Engineer — Nimbus Data Systems",
            content=by_key["source_nimbus_posting"]["text"],
        )
        db.add(source)
        await db.flush()
        db.add(ResearchQuerySource(query_id=query.id, source_id=source.id, search_rank=1))
        owner_ids["source_nimbus_posting"] = source.id

    research_owner_types = {"claim", "source_chunk"}
    for item in corpus:
        is_profile_owned = item["owner_type"] not in research_owner_types
        if is_profile_owned:
            db.add(
                ProfileEmbedding(
                    profile_id=profile.id,
                    owner_type=item["owner_type"],
                    owner_id=owner_ids[item["key"]],
                    chunk_text=item["text"],
                    embedding=item["embedding"],
                )
            )
        else:
            db.add(
                ResearchEmbedding(
                    query_id=query.id,
                    owner_type=item["owner_type"],
                    owner_id=owner_ids[item["key"]],
                    chunk_text=item["text"],
                    embedding=item["embedding"],
                )
            )
    await db.commit()

    key_to_owner_id = {key: str(owner_id) for key, owner_id in owner_ids.items()}
    return user.id, key_to_owner_id


async def run(
    session_factory: async_sessionmaker[AsyncSession], *, replay: bool
) -> BucketReport:
    data = _load_data()

    if replay:
        query_vectors = {q["text"]: q["embedding"] for q in data["queries"]}

        async def _fake_embed_query(text: str) -> list[float] | None:
            return query_vectors.get(text)

        setattr(search_service, "embed_query", _fake_embed_query)  # noqa: B010

    async with session_factory() as db:
        user_id, key_to_owner_id = await _seed(db, data["corpus"])

        tasks: list[TaskResult] = []
        for q in data["queries"]:
            results = await search_service.run_search(db, user_id=user_id, query_text=q["text"])
            expected_owner_id = key_to_owner_id.get(q["expected_key"])
            result_owner_ids = [r.id.split(":", 1)[1] for r in results]
            hit_at_1 = bool(result_owner_ids) and result_owner_ids[0] == expected_owner_id
            rank = (
                result_owner_ids.index(expected_owner_id) + 1
                if expected_owner_id in result_owner_ids
                else None
            )
            mrr = 1.0 / rank if rank else 0.0
            tasks.append(
                TaskResult(
                    task_id=f"retrieval:{q['expected_key']}",
                    passed=hit_at_1,
                    score=mrr,
                    detail=(
                        f"query={q['text']!r} expected={q['expected_key']!r} "
                        f"rank={rank if rank else 'not found in top-K'}"
                    ),
                )
            )

    return BucketReport(name="profile_rag_retrieval", tasks=tasks)
