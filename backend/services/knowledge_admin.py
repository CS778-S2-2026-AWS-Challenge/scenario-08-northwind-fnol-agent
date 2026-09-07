from datetime import UTC, datetime
from hashlib import sha256
from urllib.parse import urlparse

from backend.core.errors import ApiError
from backend.domain.knowledge import KnowledgePublicationStatus, KnowledgeSource
from backend.domain.knowledge_admin import (
    KnowledgeSourceCreate,
    KnowledgeSourceRecord,
    KnowledgeVersionState,
)
from backend.repositories.knowledge_admin import KnowledgeAdminRepository
from backend.services.knowledge_ingestion import validate_manifest_source

_FORBIDDEN_DOCUMENT_TYPES = frozenset(
    {'customer_policy', 'claim_state', 'claim_history', 'staff_decision'}
)


def _error(code: str, message: str, status_code: int = 422) -> ApiError:
    return ApiError(status_code=status_code, code=code, message=message)


def to_source(payload: KnowledgeSourceCreate) -> KnowledgeSource:
    if payload.document_type.casefold() in _FORBIDDEN_DOCUMENT_TYPES:
        raise _error(
            'KNOWLEDGE_DOCUMENT_TYPE_FORBIDDEN',
            'Customer policy, Claim State, claim history, and staff decisions cannot be '
            'uploaded as RAG documents.',
        )
    parsed = urlparse(payload.source_uri)
    if parsed.scheme.casefold() not in {'https', 'northwind'} or not parsed.hostname:
        raise _error('KNOWLEDGE_SOURCE_INVALID', 'source_uri must use an approved URI scheme.')
    expected_checksum = payload.expected_checksum
    if payload.content is not None:
        checksum = sha256(payload.content.encode('utf-8')).hexdigest()
        if expected_checksum is not None and expected_checksum.casefold() != checksum:
            raise _error('KNOWLEDGE_CHECKSUM_MISMATCH', 'expected_checksum does not match content.')
        expected_checksum = checksum
    if expected_checksum is None:
        raise _error(
            'KNOWLEDGE_CHECKSUM_REQUIRED',
            'A source checksum is required before indexing.',
        )
    source = KnowledgeSource(
        document_id=payload.document_id,
        source_key=payload.source_key,
        title=payload.title,
        document_type=payload.document_type,
        version=payload.version,
        source_uri=payload.source_uri,
        jurisdiction=payload.jurisdiction,
        insurer=payload.insurer,
        product=payload.product,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        authority=payload.authority,
        visibility=payload.visibility,
        publication_status=KnowledgePublicationStatus.APPROVED,
        expected_checksum=expected_checksum,
    )
    try:
        validate_manifest_source(source)
    except ValueError as error:
        raise _error('KNOWLEDGE_SOURCE_INVALID', str(error)) from error
    return source


def record_from_source(
    repository: KnowledgeAdminRepository,
    source: KnowledgeSource,
    author: str,
    *,
    content: str | None,
) -> KnowledgeSourceRecord:
    now = datetime.now(UTC)
    return KnowledgeSourceRecord(
        knowledge_id=repository.new_knowledge_id(),
        document_id=source.document_id,
        version=source.version,
        source_key=source.source_key,
        title=source.title,
        document_type=source.document_type,
        source_uri=source.source_uri,
        jurisdiction=source.jurisdiction,
        insurer=source.insurer,
        product=source.product,
        effective_from=source.effective_from,
        effective_to=source.effective_to,
        authority=source.authority,
        visibility=source.visibility,
        expected_checksum=source.expected_checksum,
        state=KnowledgeVersionState.DRAFT,
        revision=1,
        author=author,
        updated_at=now,
    )
