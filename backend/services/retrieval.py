from backend.adapters.policy_history import (
    PolicyHistoryAdapter,
    RetrievalUnavailable,
    map_history_provider_payload,
    map_policy_provider_payload,
)
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import WorkingClaim
from backend.domain.retrieval import (
    ClaimHistoryRetrievalRecord,
    ClaimHistorySearchRequest,
    ClaimHistorySearchResponse,
    PolicyRetrievalRecord,
    PolicySearchRequest,
    PolicySearchResponse,
    RetrievalStatus,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.retrieval_review import persist_retrieval_record
from backend.services.support import now_utc

NO_RECORD_LIMITATION = 'The provider holds no record for the requested reference.'


def _claim(repository: PersistenceRepository, claim_id: str) -> WorkingClaim:
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The working claim was not found.',
        )
    return claim


def _status_for(record: PolicyRetrievalRecord | ClaimHistoryRetrievalRecord) -> RetrievalStatus:
    """Uncertainty downgrades a result to ambiguous rather than hiding it.

    Ambiguity is evidence for professional review, so it is reported and
    persisted; it is never resolved into a coverage or history conclusion here.
    """
    return RetrievalStatus.AMBIGUOUS if record.uncertainty else RetrievalStatus.EVIDENCE_FOUND


def search_policy(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    payload: PolicySearchRequest,
) -> PolicySearchResponse:
    """Retrieve policy evidence, or report honestly that none was retrieved."""

    claim = _claim(repository, payload.claim_id)
    result_id = new_id('pol')

    try:
        envelope = adapter.search_policy(payload)
    except RetrievalUnavailable as unavailable:
        return PolicySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.UNAVAILABLE,
            limitations=[unavailable.detail],
            retrieved_at=now_utc(),
        )
    except LookupError:
        return PolicySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.NO_EVIDENCE,
            limitations=[NO_RECORD_LIMITATION],
            retrieved_at=now_utc(),
        )

    record = map_policy_provider_payload(
        retrieval_id=result_id,
        claim_id=claim.claim_id,
        envelope=envelope,
    )
    persist_retrieval_record(repository, record, claim.customer_id)
    return PolicySearchResponse(
        result_id=result_id,
        status=_status_for(record),
        source=record.source,
        facts=record.facts,
        uncertainty=record.uncertainty,
        retrieved_at=record.source.retrieved_at,
    )


def search_claim_history(
    repository: PersistenceRepository,
    adapter: PolicyHistoryAdapter,
    payload: ClaimHistorySearchRequest,
) -> ClaimHistorySearchResponse:
    """Retrieve purpose-limited history evidence, never a fraud conclusion."""

    claim = _claim(repository, payload.claim_id)
    result_id = new_id('his')

    try:
        envelope = adapter.search_claim_history(payload)
    except RetrievalUnavailable as unavailable:
        return ClaimHistorySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.UNAVAILABLE,
            limitations=[unavailable.detail],
            retrieved_at=now_utc(),
        )
    except LookupError:
        return ClaimHistorySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.NO_EVIDENCE,
            limitations=[NO_RECORD_LIMITATION],
            retrieved_at=now_utc(),
        )

    record = map_history_provider_payload(
        retrieval_id=result_id,
        claim_id=claim.claim_id,
        envelope=envelope,
    )
    persist_retrieval_record(repository, record, claim.customer_id)
    return ClaimHistorySearchResponse(
        result_id=result_id,
        status=_status_for(record),
        source=record.source,
        facts=record.facts,
        uncertainty=record.uncertainty,
        retrieved_at=record.source.retrieved_at,
    )
