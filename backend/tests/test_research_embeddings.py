"""app.research.embeddings.embed_and_store_batch: many sources or claims go out in as few Voyage
requests as the API allows, not one request per item. The database is a recording fake — the
function only ever calls db.add() on it."""

import uuid

import pytest

from app.research import embeddings
from app.research.models import ResearchEmbedding


class _RecordingSession:
    def __init__(self) -> None:
        self.added: list[object] = []

    def add(self, obj: object) -> None:
        self.added.append(obj)


def _unit_vector(index: int) -> list[float]:
    vector = [0.0] * 512
    vector[index % 512] = 1.0
    return vector


@pytest.fixture
def voyage_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    async def _fake_embed_texts(texts: list[str], *, input_type: str = "document") -> list:
        calls.append(list(texts))
        return [_unit_vector(len(calls) * 1000 + i) for i in range(len(texts))]

    monkeypatch.setattr(embeddings, "embed_texts", _fake_embed_texts)
    return calls


async def test_many_items_are_embedded_in_one_voyage_request(voyage_calls: list[list[str]]) -> None:
    db = _RecordingSession()
    items = [(uuid.uuid4(), f"Source number {i} text") for i in range(8)]

    by_owner = await embeddings.embed_and_store_batch(
        db, query_id=uuid.uuid4(), owner_type="source_chunk", items=items
    )

    assert len(voyage_calls) == 1
    assert len(voyage_calls[0]) == 8
    assert set(by_owner) == {owner for owner, _ in items}


async def test_a_long_text_is_chunked_and_each_chunk_stored_with_its_index(
    voyage_calls: list[list[str]],
) -> None:
    db = _RecordingSession()
    owner = uuid.uuid4()
    long_text = "x" * (embeddings.CHUNK_SIZE * 3)

    by_owner = await embeddings.embed_and_store_batch(
        db, query_id=uuid.uuid4(), owner_type="source_chunk", items=[(owner, long_text)]
    )

    assert len(voyage_calls) == 1
    assert len(voyage_calls[0]) == 3
    assert len(by_owner[owner]) == 3
    stored = [obj for obj in db.added if isinstance(obj, ResearchEmbedding)]
    assert [row.chunk_index for row in stored] == [0, 1, 2]


async def test_more_chunks_than_one_request_allows_are_split_into_batches(
    voyage_calls: list[list[str]],
) -> None:
    db = _RecordingSession()
    items = [(uuid.uuid4(), f"text {i}") for i in range(embeddings.VOYAGE_MAX_BATCH_INPUTS + 2)]

    by_owner = await embeddings.embed_and_store_batch(
        db, query_id=uuid.uuid4(), owner_type="claim", items=items
    )

    assert [len(call) for call in voyage_calls] == [embeddings.VOYAGE_MAX_BATCH_INPUTS, 2]
    assert len(by_owner) == len(items)


async def test_empty_text_makes_no_request_and_returns_nothing(
    voyage_calls: list[list[str]],
) -> None:
    db = _RecordingSession()

    by_owner = await embeddings.embed_and_store_batch(
        db, query_id=uuid.uuid4(), owner_type="source_chunk", items=[(uuid.uuid4(), "   ")]
    )

    assert voyage_calls == []
    assert by_owner == {}
    assert db.added == []


async def test_unavailable_embeddings_skip_cleanly_without_storing_anything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _unavailable(texts: list[str], *, input_type: str = "document") -> None:
        return None

    monkeypatch.setattr(embeddings, "embed_texts", _unavailable)
    db = _RecordingSession()

    by_owner = await embeddings.embed_and_store_batch(
        db,
        query_id=uuid.uuid4(),
        owner_type="source_chunk",
        items=[(uuid.uuid4(), "some source text")],
    )

    assert by_owner == {}
    assert db.added == []
