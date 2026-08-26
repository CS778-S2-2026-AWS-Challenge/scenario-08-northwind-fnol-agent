import json
import re
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import PurePosixPath
from typing import Protocol
from urllib.parse import urlparse

from backend.domain.knowledge import KnowledgeChunk, KnowledgePublicationStatus, KnowledgeSource

INGESTION_PIPELINE_IDENTITY = 'markdown-sections-v1+keyword-index-v1+state-v2'
SUPPORTED_VISIBILITY = frozenset({'public', 'customer_and_staff', 'staff_only'})
SUPPORTED_SOURCE_URI_SCHEMES = frozenset({'https', 'northwind'})


class KnowledgeIngestionError(ValueError):
    pass


class KnowledgeSourceNotFound(KnowledgeIngestionError):
    pass


class KnowledgeManifestError(KnowledgeIngestionError):
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


def _citation_identifier(value: str, position: int) -> str:
    identifier = re.sub(r'[^A-Za-z0-9_-]+', '-', value).strip('-')
    return identifier or f'SECTION-{position:03d}'


def _terms(text: str) -> set[str]:
    return {term for term in re.findall(r"[a-z0-9']+", text.casefold()) if len(term) > 2}


def _source_metadata_fingerprint(source: KnowledgeSource) -> str:
    governed_metadata = {
        'document_id': source.document_id,
        'source_key': source.source_key,
        'title': source.title,
        'document_type': source.document_type,
        'version': source.version,
        'source_uri': source.source_uri,
        'jurisdiction': source.jurisdiction,
        'insurer': source.insurer,
        'product': source.product,
        'effective_from': source.effective_from.isoformat() if source.effective_from else None,
        'effective_to': source.effective_to.isoformat() if source.effective_to else None,
        'authority': source.authority,
        'visibility': source.visibility,
        'publication_status': source.publication_status.value,
        'expected_checksum': source.expected_checksum,
    }
    canonical = json.dumps(governed_metadata, sort_keys=True, separators=(',', ':')).encode()
    return sha256(canonical).hexdigest()


def _require_manifest_text(source: KnowledgeSource, field: str) -> str:
    value = getattr(source, field)
    if not isinstance(value, str) or not value.strip():
        raise KnowledgeManifestError(f'Knowledge manifest {field} must be a non-empty string.')
    if value != value.strip():
        raise KnowledgeManifestError(f'Knowledge manifest {field} must be canonical text.')
    return value


def validate_manifest_source(source: KnowledgeSource) -> None:
    """Fail closed before a governed source can authorise object-store access."""
    for field in (
        'document_id',
        'title',
        'document_type',
        'version',
        'jurisdiction',
        'authority',
    ):
        _require_manifest_text(source, field)
    for field in ('document_id', 'version'):
        value = getattr(source, field)
        if re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', value) is None:
            raise KnowledgeManifestError(
                f'Knowledge manifest {field} contains unsupported path characters.'
            )

    source_key = _require_manifest_text(source, 'source_key')
    key = PurePosixPath(source_key)
    if (
        '\\' in source_key
        or source_key.startswith('/')
        or '//' in source_key
        or '..' in key.parts
        or not source_key.startswith('knowledge/')
        or source_key.startswith('knowledge/indexed/')
        or key.suffix.casefold() != '.md'
    ):
        raise KnowledgeManifestError(
            'Knowledge manifest source_key must identify a Markdown source '
            'in the knowledge namespace.'
        )

    source_uri = _require_manifest_text(source, 'source_uri')
    parsed_uri = urlparse(source_uri)
    try:
        uri_host = parsed_uri.hostname
    except ValueError:
        uri_host = None
    if (
        any(character.isspace() for character in source_uri)
        or parsed_uri.scheme.casefold() not in SUPPORTED_SOURCE_URI_SCHEMES
        or not uri_host
        or parsed_uri.username is not None
        or parsed_uri.password is not None
    ):
        raise KnowledgeManifestError('Knowledge manifest source_uri is invalid or unsupported.')

    visibility = _require_manifest_text(source, 'visibility')
    if visibility not in SUPPORTED_VISIBILITY:
        raise KnowledgeManifestError('Knowledge manifest visibility is unsupported.')

    for field in ('insurer', 'product'):
        value = getattr(source, field)
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                raise KnowledgeManifestError(
                    f'Knowledge manifest {field} must be omitted or a non-empty string.'
                )
            if value != value.strip():
                raise KnowledgeManifestError(f'Knowledge manifest {field} must be canonical text.')
    if source.document_type == 'synthetic_policy_wording' and (
        source.insurer is None or source.product is None
    ):
        raise KnowledgeManifestError(
            'Synthetic policy manifest entries require insurer and product applicability.'
        )

    for field in ('effective_from', 'effective_to'):
        value = getattr(source, field)
        if value is not None and (not isinstance(value, datetime) or value.utcoffset() is None):
            raise KnowledgeManifestError(
                f'Knowledge manifest {field} must be a timestamp with an explicit timezone.'
            )
    if (
        source.effective_from is not None
        and source.effective_to is not None
        and source.effective_to <= source.effective_from
    ):
        raise KnowledgeManifestError(
            'Knowledge manifest effective_to must be later than effective_from.'
        )

    checksum = source.expected_checksum
    if source.publication_status is KnowledgePublicationStatus.APPROVED and checksum is None:
        raise KnowledgeManifestError('Approved manifest entry requires a source checksum.')
    if checksum is not None and (
        not isinstance(checksum, str) or re.fullmatch(r'[0-9a-fA-F]{64}', checksum) is None
    ):
        raise KnowledgeManifestError(
            'Knowledge manifest checksum must be a 64-character SHA-256 hexadecimal digest.'
        )


class KnowledgeIngestionService:
    def __init__(
        self, store: KnowledgeObjectStore, approved_sources: dict[tuple[str, str], KnowledgeSource]
    ) -> None:
        for identity, source in approved_sources.items():
            validate_manifest_source(source)
            if identity != (source.document_id, source.version):
                raise KnowledgeManifestError(
                    'Knowledge manifest lookup identity does not match its governed source.'
                )
        self._store = store
        self._approved_sources = approved_sources

    def ingest(self, requested_source: KnowledgeSource) -> KnowledgeIngestionResult:
        if not requested_source.version.strip():
            raise KnowledgeIngestionError('Knowledge source version is required.')
        identity = (requested_source.document_id, requested_source.version)
        source = self._approved_sources.get(identity)
        if source is None:
            raise KnowledgeIngestionError(
                'Knowledge source is not registered in the approved manifest.'
            )
        if source.publication_status is not KnowledgePublicationStatus.APPROVED:
            raise KnowledgeIngestionError(
                'Knowledge source is not approved in the controlled manifest.'
            )
        if requested_source != source:
            raise KnowledgeIngestionError(
                'Knowledge source metadata does not match the controlled manifest.'
            )
        if source.expected_checksum is None:
            raise KnowledgeManifestError('Approved manifest entry requires a source checksum.')
        raw = self._store.read(source.source_key)
        if raw is None:
            raise KnowledgeSourceNotFound(f'Knowledge source not found: {source.source_key}')
        checksum = sha256(raw).hexdigest()
        if checksum != source.expected_checksum.casefold():
            raise KnowledgeIngestionError('Knowledge source checksum does not match the manifest.')
        metadata_fingerprint = _source_metadata_fingerprint(source)

        prefix = f'knowledge/indexed/{source.document_id}/{source.version}'
        state_key = f'{prefix}/ingestion.json'
        existing = self._store.read(state_key)
        if existing is not None:
            try:
                state = json.loads(existing)
                recorded_checksum = state['source_checksum']
                chunk_count = state['chunk_count']
                chunks_checksum = state['chunks_checksum']
            except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as error:
                raise KnowledgeIngestionError(
                    'Existing ingestion state is invalid and cannot be trusted.'
                ) from error
            if not isinstance(chunk_count, int) or chunk_count < 1:
                raise KnowledgeIngestionError(
                    'Existing ingestion state is invalid and cannot be trusted.'
                )
            if not isinstance(chunks_checksum, str) or len(chunks_checksum) != 64:
                raise KnowledgeIngestionError(
                    'Existing ingestion state is invalid and cannot be trusted.'
                )
            if recorded_checksum != checksum:
                raise KnowledgeIngestionError(
                    'An immutable document version already exists with different content.'
                )
            if state.get('source_metadata_fingerprint') != metadata_fingerprint:
                raise KnowledgeIngestionError(
                    'An immutable document version already exists with different governed metadata.'
                )
            if state.get('pipeline_identity') != INGESTION_PIPELINE_IDENTITY:
                raise KnowledgeIngestionError(
                    'An indexed document version already exists from a different '
                    'ingestion pipeline.'
                )
            return KnowledgeIngestionResult(
                source.document_id, source.version, checksum, chunk_count, 'unchanged'
            )

        chunks = self._chunk(source, raw, checksum)
        chunk_payload = b''.join(
            json.dumps(self._serialise_chunk(chunk), sort_keys=True).encode() + b'\n'
            for chunk in chunks
        )
        chunks_checksum = sha256(chunk_payload).hexdigest()
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
            'chunks_checksum': chunks_checksum,
            'source_metadata_fingerprint': metadata_fingerprint,
            'pipeline_identity': INGESTION_PIPELINE_IDENTITY,
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
            identifier = _citation_identifier(section_code, position)
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
