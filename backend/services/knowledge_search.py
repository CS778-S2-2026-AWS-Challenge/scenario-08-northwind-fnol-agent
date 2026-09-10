from datetime import UTC, datetime

from backend.core.errors import ApiError
from backend.domain.data_query import (
    DataConnectionState,
    DataQueryError,
    DataQueryErrorCode,
    usable_connection_state,
)
from backend.domain.knowledge import (
    KnowledgeCitation,
    KnowledgeRetrievalUnavailable,
    KnowledgeRetriever,
    KnowledgeSearch,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)

NO_KNOWLEDGE_LIMITATION = (
    'No applicable approved knowledge was found for the supplied scope and effective date.'
)
UNAVAILABLE_LIMITATION = 'The knowledge service is temporarily unavailable.'
TIMEOUT_LIMITATION = 'The knowledge service did not respond within the request budget.'


def _connection_state(retriever: KnowledgeRetriever) -> DataConnectionState:
    try:
        return usable_connection_state(retriever.connection_status())
    except Exception:
        return DataConnectionState.UNAVAILABLE


def _provider_ready(state: DataConnectionState) -> bool:
    return state in {
        DataConnectionState.USING_FIXTURE,
        DataConnectionState.VERIFIED,
        DataConnectionState.CONFIGURED_SERVICE,
    }


def _unavailable_response() -> KnowledgeSearchResponse:
    return KnowledgeSearchResponse(
        status='unavailable',
        retrieved_at=datetime.now(UTC),
        connection_state=DataConnectionState.UNAVAILABLE,
        errors=[
            DataQueryError(
                code=DataQueryErrorCode.UNAVAILABLE,
                message=UNAVAILABLE_LIMITATION,
                retryable=True,
            )
        ],
        results=[],
        limitations=[UNAVAILABLE_LIMITATION],
    )


def search_knowledge(
    retriever: KnowledgeRetriever, payload: KnowledgeSearchRequest
) -> KnowledgeSearchResponse:
    # Check readiness before handing claimant data to any provider.  Unknown,
    # pending, and unavailable states must fail closed without a retrieval call.
    connection_state = _connection_state(retriever)
    if not _provider_ready(connection_state):
        return _unavailable_response()
    try:
        chunks = retriever.search(
            KnowledgeSearch(
                text=payload.question,
                jurisdiction=payload.jurisdiction,
                visibility=payload.visibility,
                document_id=payload.document_id,
                authority=payload.authority,
                version=payload.version,
                insurer=payload.insurer,
                product=payload.product,
                effective_at=payload.effective_at,
                limit=payload.limit,
            )
        )
    except KnowledgeRetrievalUnavailable as unavailable:
        timed_out = unavailable.code.strip().casefold() in {
            'timeout',
            'provider_timeout',
            'request_timeout',
        }
        message = TIMEOUT_LIMITATION if timed_out else UNAVAILABLE_LIMITATION
        return KnowledgeSearchResponse(
            status='timeout' if timed_out else 'unavailable',
            retrieved_at=datetime.now(UTC),
            connection_state=(
                DataConnectionState.DEGRADED if timed_out else DataConnectionState.UNAVAILABLE
            ),
            errors=[
                DataQueryError(
                    code=(
                        DataQueryErrorCode.TIMEOUT if timed_out else DataQueryErrorCode.UNAVAILABLE
                    ),
                    message=message,
                    retryable=True,
                )
            ],
            results=[],
            limitations=[message],
        )
    except Exception as error:
        _ = error
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The knowledge provider returned an unusable response.',
            retryable=False,
        ) from error
    # Re-check after the call so a provider that lost its verified state while
    # handling the request cannot release evidence from that uncertain window.
    connection_state = _connection_state(retriever)
    if not _provider_ready(connection_state):
        return _unavailable_response()
    if not chunks:
        return KnowledgeSearchResponse(
            status='no_evidence',
            retrieved_at=datetime.now(UTC),
            connection_state=connection_state,
            results=[],
            limitations=[NO_KNOWLEDGE_LIMITATION],
        )
    try:
        results = [
            KnowledgeCitation(
                document_id=chunk.document_id,
                chunk_id=chunk.chunk_id,
                title=chunk.title,
                section_path=chunk.section_path,
                source_uri=chunk.source_uri,
                version=chunk.version,
                checksum=chunk.checksum,
                text=chunk.text,
            )
            for chunk in chunks
        ]
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The knowledge provider returned an unusable response.',
            retryable=False,
        ) from error
    return KnowledgeSearchResponse(
        status='evidence_found',
        retrieved_at=datetime.now(UTC),
        connection_state=connection_state,
        results=results,
        limitations=[],
    )
