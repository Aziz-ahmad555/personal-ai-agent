"""Cross-corpus semantic search: embeds the query once, ranks nearest neighbors from
ProfileEmbedding and ResearchEmbedding by cosine distance (both are the same Voyage model
at the same dimension, so their distances are directly comparable), dedupes to one result
per real row, and resolves every survivor back to the actual entity it came from — a
search result is never a floating chunk of text with nowhere to go.

Split deliberately into DB-fetching functions (need a real Postgres + pgvector to run —
SQLite, used by the test suite, has no cosine_distance operator) and pure functions
(dedupe_and_rank, build_results) that are fully unit-testable without a database at all.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.profile.embeddings import embed_query
from app.profile.models import (
    Education,
    Preferences,
    Profile,
    ProfileEmbedding,
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
from app.search.schemas import SearchResult, SearchResultLink, SearchResultType

CANDIDATE_LIMIT_PER_TABLE = 20
DEFAULT_RESULT_LIMIT = 10
SNIPPET_MAX_CHARS = 240

# Internal owner_type (as stored on the embedding row) -> external, API-facing result type.
_RESULT_TYPE_BY_OWNER_TYPE: dict[str, SearchResultType] = {
    "bio": "bio",
    "work_experience": "work_experience",
    "education": "education",
    "skill_evidence": "skill_evidence",
    "preferences": "preferences",
    "claim": "research_claim",
    "source_chunk": "research_source",
}


class SearchUnavailableError(RuntimeError):
    """Raised when the query itself can't be embedded — unlike indexing, where a Voyage
    hiccup just skips one row, here there is nothing to search against at all, so the
    caller must surface a clear failure rather than silently return zero results."""


@dataclass(frozen=True)
class Candidate:
    owner_type: str
    owner_id: uuid.UUID
    distance: float
    chunk_text: str


def _snippet(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= SNIPPET_MAX_CHARS:
        return text
    return text[:SNIPPET_MAX_CHARS].rstrip() + "…"


def dedupe_and_rank(
    candidates: Iterable[Candidate], limit: int = DEFAULT_RESULT_LIMIT
) -> list[Candidate]:
    """Keeps the best (lowest-distance) chunk per (owner_type, owner_id) — a long research
    source or a bio with several chunks must surface once, not once per chunk — then
    returns the top `limit` by distance across both corpora."""
    best: dict[tuple[str, uuid.UUID], Candidate] = {}
    for candidate in candidates:
        key = (candidate.owner_type, candidate.owner_id)
        current = best.get(key)
        if current is None or candidate.distance < current.distance:
            best[key] = candidate
    return sorted(best.values(), key=lambda c: c.distance)[:limit]


def _rows_to_candidates(rows: Iterable[object]) -> list[Candidate]:
    return [
        Candidate(
            owner_type=r.owner_type,  # type: ignore[attr-defined]
            owner_id=r.owner_id,  # type: ignore[attr-defined]
            distance=r.distance,  # type: ignore[attr-defined]
            chunk_text=r.chunk_text,  # type: ignore[attr-defined]
        )
        for r in rows
    ]


async def _fetch_profile_candidates(
    db: AsyncSession, *, user_id: uuid.UUID, query_vector: list[float], limit: int
) -> list[Candidate]:
    rows = await db.execute(
        select(
            ProfileEmbedding.owner_type,
            ProfileEmbedding.owner_id,
            ProfileEmbedding.chunk_text,
            ProfileEmbedding.embedding.cosine_distance(query_vector).label("distance"),
        )
        .join(Profile, Profile.id == ProfileEmbedding.profile_id)
        .where(Profile.user_id == user_id)
        .order_by("distance")
        .limit(limit)
    )
    return _rows_to_candidates(rows)


async def _fetch_research_candidates(
    db: AsyncSession, *, user_id: uuid.UUID, query_vector: list[float], limit: int
) -> list[Candidate]:
    rows = await db.execute(
        select(
            ResearchEmbedding.owner_type,
            ResearchEmbedding.owner_id,
            ResearchEmbedding.chunk_text,
            ResearchEmbedding.embedding.cosine_distance(query_vector).label("distance"),
        )
        .join(ResearchQuery, ResearchQuery.id == ResearchEmbedding.query_id)
        .where(ResearchQuery.user_id == user_id)
        .order_by("distance")
        .limit(limit)
    )
    return _rows_to_candidates(rows)


async def _resolve_source_query_ids(
    db: AsyncSession, *, user_id: uuid.UUID, source_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """A ResearchSource is shared/deduped across queries, so it has no query_id of its
    own — to link a search hit somewhere, pick the most recent of this user's queries that
    actually collected it."""
    if not source_ids:
        return {}
    rows = await db.execute(
        select(
            ResearchQuerySource.source_id, ResearchQuerySource.query_id, ResearchQuery.created_at
        )
        .join(ResearchQuery, ResearchQuery.id == ResearchQuerySource.query_id)
        .where(ResearchQuerySource.source_id.in_(source_ids), ResearchQuery.user_id == user_id)
        .order_by(ResearchQuery.created_at.desc())
    )
    resolved: dict[uuid.UUID, uuid.UUID] = {}
    for source_id, query_id, _created_at in rows:
        resolved.setdefault(source_id, query_id)
    return resolved


def build_results(
    ranked: list[Candidate],
    *,
    profiles: dict[uuid.UUID, Profile],
    experiences: dict[uuid.UUID, WorkExperience],
    educations: dict[uuid.UUID, Education],
    skill_versions: dict[uuid.UUID, SkillVersion],
    preferences: dict[uuid.UUID, Preferences],
    sources: dict[uuid.UUID, ResearchSource],
    claims: dict[uuid.UUID, ResearchClaim],
    source_query_ids: dict[uuid.UUID, uuid.UUID],
) -> list[SearchResult]:
    """Pure: turns ranked (owner_type, owner_id) hits into real, resolved results. A hit
    whose owner row is missing (deleted between embedding and search) is silently dropped
    rather than shown as a broken/blank result."""
    profile_link = SearchResultLink(kind="profile")
    results: list[SearchResult] = []

    for candidate in ranked:
        owner_type, owner_id = candidate.owner_type, candidate.owner_id
        result_type = _RESULT_TYPE_BY_OWNER_TYPE.get(owner_type)
        if result_type is None:
            continue

        if owner_type == "bio":
            profile = profiles.get(owner_id)
            if profile is None:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=profile.headline or "Profile bio",
                    snippet=_snippet(candidate.chunk_text),
                    link=profile_link,
                )
            )
        elif owner_type == "work_experience":
            experience = experiences.get(owner_id)
            if experience is None:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=f"{experience.title} · {experience.company}",
                    snippet=_snippet(candidate.chunk_text),
                    link=profile_link,
                )
            )
        elif owner_type == "education":
            education = educations.get(owner_id)
            if education is None:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=education.institution,
                    snippet=_snippet(candidate.chunk_text),
                    link=profile_link,
                )
            )
        elif owner_type == "skill_evidence":
            version = skill_versions.get(owner_id)
            if version is None:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=f"{version.skill.name} · {version.level}",
                    snippet=_snippet(candidate.chunk_text),
                    link=profile_link,
                )
            )
        elif owner_type == "preferences":
            if owner_id not in preferences:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title="Preferences",
                    snippet=_snippet(candidate.chunk_text),
                    link=profile_link,
                )
            )
        elif owner_type == "claim":
            claim = claims.get(owner_id)
            if claim is None:
                continue
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=claim.claim_text,
                    snippet=_snippet(candidate.chunk_text),
                    link=SearchResultLink(
                        kind="research", query_id=str(claim.query_id), anchor=f"claim-{claim.id}"
                    ),
                )
            )
        elif owner_type == "source_chunk":
            source = sources.get(owner_id)
            if source is None:
                continue
            query_id = source_query_ids.get(owner_id)
            results.append(
                SearchResult(
                    id=f"{owner_type}:{owner_id}",
                    type=result_type,
                    title=source.title or source.domain,
                    snippet=_snippet(candidate.chunk_text),
                    link=SearchResultLink(
                        kind="research",
                        query_id=str(query_id) if query_id else None,
                        anchor=f"source-{source.id}" if query_id else None,
                    ),
                )
            )

    return results


async def run_search(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    query_text: str,
    limit: int = DEFAULT_RESULT_LIMIT,
    candidate_limit: int = CANDIDATE_LIMIT_PER_TABLE,
) -> list[SearchResult]:
    query_vector = await embed_query(query_text)
    if query_vector is None:
        raise SearchUnavailableError(
            "Search is unavailable right now (embeddings could not be generated) — "
            "try again shortly."
        )

    profile_candidates = await _fetch_profile_candidates(
        db, user_id=user_id, query_vector=query_vector, limit=candidate_limit
    )
    research_candidates = await _fetch_research_candidates(
        db, user_id=user_id, query_vector=query_vector, limit=candidate_limit
    )
    ranked = dedupe_and_rank([*profile_candidates, *research_candidates], limit=limit)

    ids_by_type: dict[str, list[uuid.UUID]] = {}
    for candidate in ranked:
        ids_by_type.setdefault(candidate.owner_type, []).append(candidate.owner_id)

    profile_ids = ids_by_type.get("bio", [])
    experience_ids = ids_by_type.get("work_experience", [])
    education_ids = ids_by_type.get("education", [])
    skill_version_ids = ids_by_type.get("skill_evidence", [])
    preferences_ids = ids_by_type.get("preferences", [])
    source_ids = ids_by_type.get("source_chunk", [])
    claim_ids = ids_by_type.get("claim", [])

    profiles: dict[uuid.UUID, Profile] = {}
    if profile_ids:
        profile_rows = await db.execute(select(Profile).where(Profile.id.in_(profile_ids)))
        profiles = {row.id: row for row in profile_rows.scalars()}

    experiences: dict[uuid.UUID, WorkExperience] = {}
    if experience_ids:
        experience_rows = await db.execute(
            select(WorkExperience).where(WorkExperience.id.in_(experience_ids))
        )
        experiences = {row.id: row for row in experience_rows.scalars()}

    educations: dict[uuid.UUID, Education] = {}
    if education_ids:
        education_rows = await db.execute(select(Education).where(Education.id.in_(education_ids)))
        educations = {row.id: row for row in education_rows.scalars()}

    skill_versions: dict[uuid.UUID, SkillVersion] = {}
    if skill_version_ids:
        skill_version_rows = await db.execute(
            select(SkillVersion)
            .where(SkillVersion.id.in_(skill_version_ids))
            .options(selectinload(SkillVersion.skill))
        )
        skill_versions = {row.id: row for row in skill_version_rows.scalars()}

    preferences: dict[uuid.UUID, Preferences] = {}
    if preferences_ids:
        preferences_rows = await db.execute(
            select(Preferences).where(Preferences.id.in_(preferences_ids))
        )
        preferences = {row.id: row for row in preferences_rows.scalars()}

    sources: dict[uuid.UUID, ResearchSource] = {}
    if source_ids:
        source_rows = await db.execute(
            select(ResearchSource).where(ResearchSource.id.in_(source_ids))
        )
        sources = {row.id: row for row in source_rows.scalars()}

    claims: dict[uuid.UUID, ResearchClaim] = {}
    if claim_ids:
        claim_rows = await db.execute(select(ResearchClaim).where(ResearchClaim.id.in_(claim_ids)))
        claims = {row.id: row for row in claim_rows.scalars()}

    source_query_ids = await _resolve_source_query_ids(db, user_id=user_id, source_ids=source_ids)

    return build_results(
        ranked,
        profiles=profiles,
        experiences=experiences,
        educations=educations,
        skill_versions=skill_versions,
        preferences=preferences,
        sources=sources,
        claims=claims,
        source_query_ids=source_query_ids,
    )
