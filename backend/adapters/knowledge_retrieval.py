import json
import re
from collections.abc import Iterable
from datetime import UTC, datetime
from hashlib import sha256

from backend.adapters.knowledge_object_store import KnowledgeObjectStoreUnavailable
from backend.domain.knowledge import (
    KnowledgeChunk,
    KnowledgePublicationStatus,
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
    KnowledgeSource,
)
from backend.services.knowledge_ingestion import (
    KnowledgeObjectStore,
    validate_manifest_source,
)

_STOP_WORDS = {
    'and',
    'are',
    'can',
    'claim',
    'for',
    'from',
    'have',
    'how',
    'into',
    'much',
    'other',
    'policy',
    'provide',
    'that',
    'the',
    'this',
    'what',
    'when',
    'with',
}

_TERM_ALIASES = {'fault': 'liability', 'tell': 'admit'}

_PRODUCT_TERMS = {
    'motor': {'car', 'motor', 'vehicle'},
    'home': {'building', 'home', 'house'},
    'contents': {'belongings', 'contents', 'possessions'},
}

_UNTRUSTED_INSTRUCTION_PATTERNS = (
    'follow any instructions',
    'ignore previous instructions',
    'reveal internal',
    'reveal private',
)


def _normalise_term(term: str) -> str:
    if term in _TERM_ALIASES:
        return _TERM_ALIASES[term]
    if term.endswith('sses'):
        return term[:-2]
    if term.endswith('s') and not term.endswith('ss'):
        return term[:-1]
    return term


def _terms(value: str) -> set[str]:
    return {
        _normalise_term(term)
        for term in re.findall(r"[a-z0-9']+", value.casefold())
        if len(term) > 2 and term not in _STOP_WORDS
    }


_PRODUCT_TERMS = {
    product: {_normalise_term(term) for term in terms} for product, terms in _PRODUCT_TERMS.items()
}


def _query_matches_scope(text: str, product: str) -> bool:
    normalized = text.casefold()
    if any(pattern in normalized for pattern in _UNTRUSTED_INSTRUCTION_PATTERNS):
        return False
    query_terms = _terms(text)
    mentioned_products = {name for name, terms in _PRODUCT_TERMS.items() if query_terms & terms}
    return not mentioned_products or mentioned_products == {product}


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def _page(value: object) -> int | None:
    return int(str(value)) if value is not None else None


def _chunk(value: dict[str, object]) -> KnowledgeChunk:
    return KnowledgeChunk(
        document_id=str(value['document_id']),
        chunk_id=str(value['chunk_id']),
        title=str(value['title']),
        document_type=str(value['document_type']),
        version=str(value['version']),
        section_path=str(value['section_path']),
        page=_page(value.get('page')),
        source_uri=str(value['source_uri']),
        jurisdiction=str(value['jurisdiction']),
        insurer=str(value['insurer']) if value.get('insurer') is not None else None,
        product=str(value['product']) if value.get('product') is not None else None,
        effective_from=_datetime(str(value['effective_from']))
        if value.get('effective_from')
        else None,
        effective_to=_datetime(str(value['effective_to'])) if value.get('effective_to') else None,
        authority=str(value['authority']),
        visibility=str(value['visibility']),
        checksum=str(value['checksum']),
        ingested_at=_datetime(str(value['ingested_at'])) or datetime.min.replace(tzinfo=UTC),
        text=str(value['text']),
    )


class S3CompatibleKnowledgeRetriever(KnowledgeRetriever):
    def __init__(self, store: KnowledgeObjectStore, sources: Iterable[KnowledgeSource]) -> None:
        self._store = store
        governed_sources: list[KnowledgeSource] = []
        for source in sources:
            validate_manifest_source(source)
            if source.publication_status is KnowledgePublicationStatus.APPROVED:
                governed_sources.append(source)
        self._sources = tuple(governed_sources)

    def connection_status(self) -> str:
        if not self._sources:
            return 'unavailable'
        try:
            for source in self._sources:
                key = self._chunks_key(source)
                if self._store.read(key) is None:
                    return 'unavailable'
        except KnowledgeObjectStoreUnavailable:
            return 'unavailable'
        return 'configured_service'

    def search(self, request: KnowledgeSearch) -> list[KnowledgeChunk]:
        if (
            not request.text.strip()
            or request.limit <= 0
            or request.authority is None
            or request.version is None
            or request.insurer is None
            or request.product is None
            or request.effective_at is None
        ):
            return []
        if not _query_matches_scope(request.text, request.product):
            return []
        applicable_sources = [
            source for source in self._sources if self._source_is_applicable(source, request)
        ]
        if not applicable_sources:
            return []
        query_terms = _terms(request.text) - _PRODUCT_TERMS.get(request.product, set())
        if not query_terms:
            return []
        scored: list[tuple[int, int, KnowledgeChunk]] = []
        try:
            for source in applicable_sources:
                payload = self._store.read(self._chunks_key(source))
                if payload is None:
                    raise KnowledgeRetrievalUnavailable(
                        'The applicable knowledge index is incomplete or unavailable.'
                    )
                state_payload = self._store.read(self._ingestion_state_key(source))
                if state_payload is None:
                    raise KnowledgeRetrievalUnavailable(
                        'The applicable knowledge index has no trusted ingestion state.'
                    )
                state = json.loads(state_payload)
                if (
                    not isinstance(state, dict)
                    or state.get('document_id') != source.document_id
                    or state.get('version') != source.version
                    or state.get('source_checksum') != source.expected_checksum
                    or state.get('chunks_checksum') != sha256(payload).hexdigest()
                ):
                    raise KnowledgeRetrievalUnavailable(
                        'The knowledge index does not match its governed ingestion state.'
                    )
                for line in payload.splitlines():
                    chunk = _chunk(json.loads(line))
                    if not self._chunk_matches_source(chunk, source):
                        raise KnowledgeRetrievalUnavailable(
                            'The knowledge index does not match its governed source.'
                        )
                    if not self._applicable(chunk, request):
                        continue
                    heading_terms = _terms(chunk.section_path)
                    text_terms = _terms(chunk.text)
                    section_match = len(query_terms & heading_terms)
                    score = 4 * section_match + len(query_terms & text_terms)
                    if score:
                        scored.append((score, section_match, chunk))
        except KnowledgeObjectStoreUnavailable as error:
            raise KnowledgeRetrievalUnavailable('The knowledge service is unavailable.') from error
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise KnowledgeRetrievalUnavailable(
                'The knowledge index is invalid or unavailable.'
            ) from error
        scored.sort(key=lambda item: (-item[1], -item[0], item[2].chunk_id))
        return [chunk for _, _, chunk in scored[: request.limit]]

    @staticmethod
    def _chunks_key(source: KnowledgeSource) -> str:
        return f'knowledge/indexed/{source.document_id}/{source.version}/chunks.jsonl'

    @staticmethod
    def _ingestion_state_key(source: KnowledgeSource) -> str:
        return f'knowledge/indexed/{source.document_id}/{source.version}/ingestion.json'

    @staticmethod
    def _chunk_matches_source(chunk: KnowledgeChunk, source: KnowledgeSource) -> bool:
        return (
            chunk.document_id == source.document_id
            and chunk.title == source.title
            and chunk.document_type == source.document_type
            and chunk.version == source.version
            and chunk.source_uri == source.source_uri
            and chunk.jurisdiction == source.jurisdiction
            and chunk.insurer == source.insurer
            and chunk.product == source.product
            and chunk.effective_from == source.effective_from
            and chunk.effective_to == source.effective_to
            and chunk.authority == source.authority
            and chunk.visibility == source.visibility
            and source.expected_checksum is not None
            and chunk.checksum.casefold() == source.expected_checksum.casefold()
        )

    @staticmethod
    def _source_is_applicable(source: KnowledgeSource, request: KnowledgeSearch) -> bool:
        effective_at = request.effective_at
        if effective_at is None:
            return False
        if (
            (request.document_id is not None and source.document_id != request.document_id)
            or source.jurisdiction != request.jurisdiction
            or source.visibility != request.visibility
            or source.authority != request.authority
            or source.version != request.version
            or source.insurer != request.insurer
            or source.product != request.product
        ):
            return False
        if source.effective_from is not None and effective_at < source.effective_from:
            return False
        return source.effective_to is None or effective_at < source.effective_to

    @staticmethod
    def _applicable(chunk: KnowledgeChunk, request: KnowledgeSearch) -> bool:
        effective_at = request.effective_at
        if effective_at is None:
            return False
        if (
            chunk.jurisdiction != request.jurisdiction
            or chunk.visibility != request.visibility
            or (request.document_id is not None and chunk.document_id != request.document_id)
            or chunk.authority != request.authority
            or chunk.version != request.version
            or chunk.insurer != request.insurer
            or chunk.product != request.product
        ):
            return False
        if chunk.effective_from is not None and effective_at < chunk.effective_from:
            return False
        return chunk.effective_to is None or effective_at < chunk.effective_to
