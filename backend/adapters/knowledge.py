from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True, slots=True)
class KnowledgeChunk:
    document_id: str
    chunk_id: str
    title: str
    document_type: str
    version: str
    section_path: str
    page: int | None
    source_uri: str
    jurisdiction: str
    insurer: str | None
    product: str | None
    effective_from: datetime | None
    effective_to: datetime | None
    authority: str
    visibility: str
    checksum: str
    ingested_at: datetime
    text: str


@dataclass(frozen=True, slots=True)
class KnowledgeSearch:
    text: str
    jurisdiction: str
    visibility: str
    insurer: str | None = None
    product: str | None = None
    effective_at: datetime | None = None
    limit: int = 5


class KnowledgeDocumentStore(Protocol):
    def connection_status(self) -> str:
        raise NotImplementedError

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        raise NotImplementedError


class KnowledgeRetriever(Protocol):
    def connection_status(self) -> str:
        raise NotImplementedError

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        raise NotImplementedError


class FixtureKnowledgeDocumentStore(KnowledgeDocumentStore):
    """Synthetic store for runtime-boundary and retrieval contract tests."""

    def __init__(self, chunks: tuple[KnowledgeChunk, ...] = ()) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}

    def connection_status(self) -> str:
        return 'using_fixture'

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._chunks.get(chunk_id)

    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._chunks.values())


def _applicable(chunk: KnowledgeChunk, request: KnowledgeSearch) -> bool:
    if chunk.jurisdiction != request.jurisdiction or chunk.visibility != request.visibility:
        return False
    if request.insurer is not None and chunk.insurer != request.insurer:
        return False
    if request.product is not None and chunk.product != request.product:
        return False
    if request.effective_at is not None:
        if chunk.effective_from is not None and request.effective_at < chunk.effective_from:
            return False
        if chunk.effective_to is not None and request.effective_at >= chunk.effective_to:
            return False
    return True


class FixtureKnowledgeRetriever(KnowledgeRetriever):
    """Metadata-first deterministic search; it does not imply production ranking."""

    def __init__(self, store: FixtureKnowledgeDocumentStore) -> None:
        self._store = store

    def connection_status(self) -> str:
        return 'using_fixture'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        normalized = request.text.strip().casefold()
        if not normalized or request.limit <= 0:
            return []
        return [
            chunk
            for chunk in self._store.chunks()
            if _applicable(chunk, request)
            and (normalized in chunk.title.casefold() or normalized in chunk.text.casefold())
        ][: request.limit]
