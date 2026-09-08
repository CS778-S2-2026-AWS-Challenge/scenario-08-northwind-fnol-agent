import json

from backend.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeDocumentStore,
    KnowledgeRetriever,
    KnowledgeSearch,
)


class FixtureKnowledgeDocumentStore(KnowledgeDocumentStore):
    """Synthetic store for runtime-boundary and retrieval contract tests."""

    def __init__(self, chunks: tuple[KnowledgeChunk, ...] = ()) -> None:
        self._chunks = {chunk.chunk_id: chunk for chunk in chunks}
        self._objects: dict[str, bytes] = {}

    def connection_status(self) -> str:
        return 'using_fixture'

    def get_chunk(self, chunk_id: str) -> KnowledgeChunk | None:
        return self._chunks.get(chunk_id)

    def chunks(self) -> tuple[KnowledgeChunk, ...]:
        return tuple(self._chunks.values())

    def read(self, key: str) -> bytes | None:
        return self._objects.get(key)

    def write(
        self,
        key: str,
        data: bytes,
        *,
        content_type: str,
        metadata: dict[str, str],
    ) -> None:
        del content_type, metadata
        self._objects[key] = data
        if key.endswith('/chunks.jsonl'):
            from backend.adapters.knowledge_retrieval import _chunk

            for line in data.splitlines():
                chunk = _chunk(json.loads(line))
                self._chunks[chunk.chunk_id] = chunk


def _applicable(chunk: KnowledgeChunk, request: KnowledgeSearch) -> bool:
    if (
        request.authority is None
        or request.version is None
        or request.insurer is None
        or request.product is None
        or request.effective_at is None
    ):
        return False
    if chunk.jurisdiction != request.jurisdiction or chunk.visibility != request.visibility:
        return False
    if chunk.authority != request.authority or chunk.version != request.version:
        return False
    if chunk.insurer != request.insurer or chunk.product != request.product:
        return False
    if chunk.effective_from is not None and request.effective_at < chunk.effective_from:
        return False
    return chunk.effective_to is None or request.effective_at < chunk.effective_to


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
