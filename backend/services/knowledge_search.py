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


def search_knowledge(
    retriever: KnowledgeRetriever, payload: KnowledgeSearchRequest
) -> KnowledgeSearchResponse:
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
    except KnowledgeRetrievalUnavailable:
        return KnowledgeSearchResponse(
            status='unavailable', results=[], limitations=[UNAVAILABLE_LIMITATION]
        )
    if not chunks:
        return KnowledgeSearchResponse(
            status='no_evidence', results=[], limitations=[NO_KNOWLEDGE_LIMITATION]
        )
    return KnowledgeSearchResponse(
        status='evidence_found',
        results=[
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
        ],
        limitations=[],
    )
