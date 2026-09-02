from backend.core.errors import ApiError, ErrorDetail
from backend.domain.external_services import map_external_task_evidence
from backend.domain.external_task_api import ExternalTaskListResponse
from backend.domain.models import PageInfo
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import decode_cursor, encode_cursor


def list_external_tasks(
    repository: PersistenceRepository,
    claim_id: str,
    *,
    limit: int,
    cursor: str | None,
) -> ExternalTaskListResponse:
    """Return one stable page of operational external-task state.

    Args:
        repository: Provider-neutral persistence boundary.
        claim_id: Working Claim whose task records are requested.
        limit: Requested page size; values above 100 are truncated.
        cursor: Opaque cursor returned by an earlier list response.

    Returns:
        A claim-scoped page of task/evidence projections.

    Raises:
        ApiError: The claim, page size, or cursor is invalid.
        ConflictingEvidenceOriginError: Persisted links give evidence two origins.
        ExternalTaskClaimMismatchError: A persisted link crosses claim boundaries.
    """

    if limit < 1:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination limit is invalid.',
            details=[ErrorDetail(field='limit', reason='Use a positive page size.')],
        )
    page_limit = min(limit, 100)

    if repository.get_claim_internal(claim_id) is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )

    tasks = repository.list_external_tasks_internal(claim_id)
    links = repository.list_external_task_evidence_links_internal(claim_id)
    views = map_external_task_evidence(tasks, links)
    offset = decode_cursor(cursor)
    page_items = views[offset : offset + page_limit]
    next_offset = offset + len(page_items)
    next_cursor = encode_cursor(next_offset) if next_offset < len(views) else None
    return ExternalTaskListResponse(
        claim_id=claim_id,
        items=page_items,
        page=PageInfo(next_cursor=next_cursor),
    )
