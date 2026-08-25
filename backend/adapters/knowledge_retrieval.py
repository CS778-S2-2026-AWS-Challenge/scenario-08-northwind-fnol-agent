import json
import re
from datetime import UTC, datetime

from backend.adapters.knowledge_object_store import KnowledgeObjectStoreUnavailable
from backend.domain.knowledge import (
    KnowledgeChunk,
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
)
from backend.services.knowledge_ingestion import KnowledgeObjectStore

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

MVP_KNOWLEDGE_DOCUMENTS = {
    ('motor', 'MVP-2026.1'): 'nw-policy-motor-standard-mvp-2026-1',
    ('home', 'MVP-2026.1'): 'nw-policy-home-standard-mvp-2026-1',
    ('contents', 'MVP-2026.1'): 'nw-policy-contents-standard-mvp-2026-1',
}


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
    def __init__(self, store: KnowledgeObjectStore, documents: dict[tuple[str, str], str]) -> None:
        self._store = store
        self._documents = documents

    def connection_status(self) -> str:
        try:
            for (product, version), document_id in self._documents.items():
                key = f'knowledge/indexed/{document_id}/{version}/chunks.jsonl'
                if self._store.read(key) is None:
                    return 'unavailable'
                if not product:
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
        document_id = self._documents.get((request.product, request.version))
        if document_id is None:
            return []
        if request.document_id is not None and request.document_id != document_id:
            return []
        if not _query_matches_scope(request.text, request.product):
            return []
        key = f'knowledge/indexed/{document_id}/{request.version}/chunks.jsonl'
        try:
            payload = self._store.read(key)
        except KnowledgeObjectStoreUnavailable as error:
            raise KnowledgeRetrievalUnavailable('The knowledge service is unavailable.') from error
        if payload is None:
            return []
        query_terms = _terms(request.text) - _PRODUCT_TERMS.get(request.product, set())
        if not query_terms:
            return []
        scored: list[tuple[int, int, KnowledgeChunk]] = []
        try:
            for line in payload.splitlines():
                chunk = _chunk(json.loads(line))
                if not self._applicable(chunk, request):
                    continue
                heading_terms = _terms(chunk.section_path)
                text_terms = _terms(chunk.text)
                section_match = len(query_terms & heading_terms)
                score = 4 * section_match + len(query_terms & text_terms)
                if score:
                    scored.append((score, section_match, chunk))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as error:
            raise KnowledgeRetrievalUnavailable(
                'The knowledge index is invalid or unavailable.'
            ) from error
        scored.sort(key=lambda item: (-item[1], -item[0], item[2].chunk_id))
        return [chunk for _, _, chunk in scored[: request.limit]]

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
