from typing import Literal

from pydantic import BaseModel

SearchResultType = Literal[
    "bio",
    "work_experience",
    "education",
    "skill_evidence",
    "preferences",
    "research_claim",
    "research_source",
]

# Every result links back to exactly one real place in the app — never a bare snippet with
# nowhere to go. "profile" results land on the whole Profile page (no per-item anchors
# there yet); "research" results carry a specific query_id + anchor id so the frontend can
# select that query and jump/highlight the exact claim or source card, reusing the
# scroll-jump mechanic already built for the research report's citation markers.
LinkKind = Literal["profile", "research"]


class SearchResultLink(BaseModel):
    kind: LinkKind
    query_id: str | None = None
    anchor: str | None = None


class SearchResult(BaseModel):
    # "<owner_type>:<owner_id>" — stable across requests for the same underlying row, so
    # the frontend has a real key instead of relying on array position.
    id: str
    type: SearchResultType
    title: str
    snippet: str
    link: SearchResultLink


class SearchResponse(BaseModel):
    query: str
    results: list[SearchResult]
