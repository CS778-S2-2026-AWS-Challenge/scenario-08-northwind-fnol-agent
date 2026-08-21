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
    authority: str | None = None
    version: str | None = None
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
