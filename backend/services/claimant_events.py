from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.models import ClaimantChangeEvent
from backend.repositories.protocols import PersistenceRepository
from backend.services.support import now_utc


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def _session_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The session was not found.',
    )


def claimant_event_revision(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
) -> int:
    """Authorise an event stream and return its current Claim revision."""

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _claim_not_found()
    if repository.get_session(claim_id, session_id, principal.subject) is None:
        raise _session_not_found()
    return claim.revision


def claimant_change_after(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    session_id: str,
    after_revision: int,
) -> ClaimantChangeEvent | None:
    """Return a resource hint when shared Claim State advanced after a cursor."""

    current_revision = claimant_event_revision(repository, principal, claim_id, session_id)
    if after_revision > current_revision:
        raise ApiError(
            status_code=409,
            code='INVALID_EVENT_CURSOR',
            message='The live-update cursor is newer than the current claim.',
            retryable=True,
            current_revision=current_revision,
            details=[
                ErrorDetail(
                    field='after_revision',
                    reason='Reconnect using the current Claim revision.',
                )
            ],
        )
    if after_revision == current_revision:
        return None
    return ClaimantChangeEvent(
        event_id=str(current_revision),
        claim_id=claim_id,
        session_id=session_id,
        claim_revision=current_revision,
        resources=['claim', 'messages'],
        emitted_at=now_utc(),
    )
