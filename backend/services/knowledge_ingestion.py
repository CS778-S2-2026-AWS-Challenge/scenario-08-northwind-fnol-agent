import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Protocol

from backend.domain.knowledge import KnowledgeChunk, KnowledgePublicationStatus, KnowledgeSource


class KnowledgeIngestionError(ValueError):
    pass


class KnowledgeSourceNotFound(KnowledgeIngestionError):
    pass


class KnowledgeObjectStore(Protocol):
    def read(self, key: str) -> bytes | None:
        raise NotImplementedError

    def write(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class KnowledgeIngestionResult:
    document_id: str
    version: str
    source_checksum: str
    chunk_count: int
    status: str


def _slug(value: str) -> str:
    return re.sub(r'[^a-z0-9]+', '-', value.casefold()).strip('-')


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9']+", text.casefold()) if len(term) > 2}


class KnowledgeIngestionService:
    def __init__(self, store: KnowledgeObjectStore) -> None:
        self._store = store

    def ingest(self, source: KnowledgeSource) -> KnowledgeIngestionResult:
        if not source.version.strip():
            raise KnowledgeIngestionError('Knowledge source version is required.')
        if source.publication_status is not KnowledgePublicationStatus.APPROVED:
            raise KnowledgeIngestionError('Only approved knowledge sources may be ingested.')
        raw = self._store.read(source.source_key)
        if raw is None:
            raise KnowledgeSourceNotFound(f'Knowledge source not found: {source.source_key}')
        checksum = sha256(raw).hexdigest()
        if source.expected_checksum is not None and checksum != source.expected_checksum:
            raise KnowledgeIngestionError('Knowledge source checksum does not match the manifest.')

        prefix = f'knowledge/indexed/{source.document_id}/{source.version}'
        state_key = f'{prefix}/ingestion.json'
        existing = self._store.read(state_key)
        if existing is not None:
            state = json.loads(existing)
            if state['source_checksum'] != checksum:
                raise KnowledgeIngestionError(
                    'An immutable document version already exists with different content.'
                )
            return KnowledgeIngestionResult(
                source.document_id, source.version, checksum, state['chunk_count'], 'unchanged'
            )

        chunks = self._chunk(source, raw, checksum)
        chunk_payload = b''.join(
            json.dumps(self._serialise_chunk(chunk), sort_keys=True).encode() + b'\n'
            for chunk in chunks
        )
        index: dict[str, list[str]] = {}
        for chunk in chunks:
            for term in _terms(f'{chunk.title} {chunk.section_path} {chunk.text}'):
                index.setdefault(term, []).append(chunk.chunk_id)
        index_payload = json.dumps(index, sort_keys=True).encode()
        state = {
            'document_id': source.document_id,
            'version': source.version,
            'source_key': source.source_key,
            'source_checksum': checksum,
            'chunk_count': len(chunks),
            'status': 'indexed',
        }
        metadata = {'document-id': source.document_id, 'version': source.version}
        self._store.write(
            f'{prefix}/chunks.jsonl',
            chunk_payload,
            content_type='application/x-ndjson',
            metadata=metadata,
        )
        self._store.write(
            f'{prefix}/keyword-index.json',
            index_payload,
            content_type='application/json',
            metadata=metadata,
        )
        self._store.write(
            state_key,
            json.dumps(state, sort_keys=True).encode(),
            content_type='application/json',
            metadata=metadata,
        )
        return KnowledgeIngestionResult(
            source.document_id, source.version, checksum, len(chunks), 'indexed'
        )

    @staticmethod
    def _chunk(source: KnowledgeSource, raw: bytes, checksum: str) -> list[KnowledgeChunk]:
        try:
            text = raw.decode('utf-8')
        except UnicodeDecodeError as error:
            raise KnowledgeIngestionError('Knowledge source must be valid UTF-8 text.') from error
        text = re.sub(r'\A---\s*\n.*?\n---\s*\n', '', text, count=1, flags=re.DOTALL)
        sections = [part.strip() for part in re.split(r'(?=^## )', text, flags=re.MULTILINE)]
        sections = [part for part in sections if part]
        if not sections:
            raise KnowledgeIngestionError('Knowledge source contains no indexable text.')
        ingested_at = datetime.now(UTC)
        chunks: list[KnowledgeChunk] = []
        for position, section in enumerate(sections, start=1):
            heading = section.splitlines()[0].removeprefix('## ').strip()
            section_code = heading.split(' - ', 1)[0]
            identifier = _slug(section_code) or f'section-{position:03d}'
            chunks.append(
                KnowledgeChunk(
                    document_id=source.document_id,
                    chunk_id=f'{source.document_id}#{identifier}',
                    title=source.title,
                    document_type=source.document_type,
                    version=source.version,
                    section_path=heading,
                    page=None,
                    source_uri=source.source_uri,
                    jurisdiction=source.jurisdiction,
                    insurer=source.insurer,
                    product=source.product,
                    effective_from=source.effective_from,
                    effective_to=source.effective_to,
                    authority=source.authority,
                    visibility=source.visibility,
                    checksum=checksum,
                    ingested_at=ingested_at,
                    text=section,
                )
            )
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise KnowledgeIngestionError(
                'Knowledge source contains duplicate section identifiers.'
            )
        return chunks

    @staticmethod
    def _serialise_chunk(chunk: KnowledgeChunk) -> dict[str, object]:
        result = asdict(chunk)
        for field in ('effective_from', 'effective_to', 'ingested_at'):
            value = result[field]
            result[field] = value.isoformat() if isinstance(value, datetime) else None
        return result
