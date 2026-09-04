from pydantic import ValidationError

from backend.adapters.policy_history import (
    PolicyHistoryAdapter,
    RetrievalUnavailable,
    map_history_provider_payload,
    map_policy_provider_payload,
)
from backend.core.errors import ApiError
from backend.domain.data_query import (
    DataConnectionState,
    DataQueryError,
    DataQueryErrorCode,
    usable_connection_state,
)
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
POLICY_TIMEOUT_LIMITATION = 'The policy provider did not respond within the request budget.'
HISTORY_TIMEOUT_LIMITATION = 'The claim-history provider did not respond within the request budget.'
POLICY_UNAVAILABLE_LIMITATION = 'The policy provider is temporarily unavailable.'
HISTORY_UNAVAILABLE_LIMITATION = 'The claim-history provider is temporarily unavailable.'


def _is_timeout(code: str) -> bool:
    return code.strip().casefold() in {'timeout', 'provider_timeout', 'request_timeout'}


def _failure_projection(
    failure_code: str,
    *,
    timeout_message: str,
    unavailable_message: str,
) -> tuple[RetrievalStatus, DataConnectionState, list[DataQueryError], list[str]]:
    timed_out = _is_timeout(failure_code)
    status = RetrievalStatus.TIMEOUT if timed_out else RetrievalStatus.UNAVAILABLE
    code = DataQueryErrorCode.TIMEOUT if timed_out else DataQueryErrorCode.UNAVAILABLE
    message = timeout_message if timed_out else unavailable_message
    connection_state = (
        DataConnectionState.DEGRADED if timed_out else DataConnectionState.UNAVAILABLE
    )
    return (
        status,
        connection_state,
        [DataQueryError(code=code, message=message, retryable=True)],
        [message],
    )


def _connection_state(adapter: PolicyHistoryAdapter) -> DataConnectionState:
    try:
        return usable_connection_state(adapter.connection_status())
    except Exception:
        return DataConnectionState.UNAVAILABLE


def _provider_ready(state: DataConnectionState) -> bool:
    return state in {
        DataConnectionState.USING_FIXTURE,
        DataConnectionState.VERIFIED,
        DataConnectionState.CONFIGURED_SERVICE,
    }


def _policy_unavailable_response(result_id: str) -> PolicySearchResponse:
    _, connection_state, errors, limitations = _failure_projection(
        'PROVIDER_UNAVAILABLE',
        timeout_message=POLICY_TIMEOUT_LIMITATION,
        unavailable_message=POLICY_UNAVAILABLE_LIMITATION,
    )
    return PolicySearchResponse(
        result_id=result_id,
        status=RetrievalStatus.UNAVAILABLE,
        connection_state=connection_state,
        errors=errors,
        limitations=limitations,
        retrieved_at=now_utc(),
    )


def _history_unavailable_response(result_id: str) -> ClaimHistorySearchResponse:
    _, connection_state, errors, limitations = _failure_projection(
        'PROVIDER_UNAVAILABLE',
        timeout_message=HISTORY_TIMEOUT_LIMITATION,
        unavailable_message=HISTORY_UNAVAILABLE_LIMITATION,
    )
    return ClaimHistorySearchResponse(
        result_id=result_id,
        status=RetrievalStatus.UNAVAILABLE,
        connection_state=connection_state,
        errors=errors,
        limitations=limitations,
        retrieved_at=now_utc(),
    )


def _malformed_provider_error(kind: str, error: ValidationError) -> ApiError:
    """Map malformed provider data to a bounded dependency failure.

    Args:
        kind: Retrieval kind whose provider response failed validation.
        error: Internal validation failure; its details are intentionally not exposed.

    Returns:
        A provider-neutral API error that callers cannot mistake for evidence.

    Raises:
        None.
    """
    _ = error
    return ApiError(
        status_code=502,
        code='DEPENDENCY_FAILED',
        message=f'The {kind} provider returned an unusable response.',
        retryable=False,
    )


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
    # Never invoke a provider whose connection has not reached a verified,
    # fixture, or configured-service state.
    connection_state = _connection_state(adapter)
    if not _provider_ready(connection_state):
        return _policy_unavailable_response(result_id)

    try:
        envelope = adapter.search_policy(payload)
    except RetrievalUnavailable as unavailable:
        status, connection_state, errors, limitations = _failure_projection(
            unavailable.code,
            timeout_message=POLICY_TIMEOUT_LIMITATION,
            unavailable_message=POLICY_UNAVAILABLE_LIMITATION,
        )
        return PolicySearchResponse(
            result_id=result_id,
            status=status,
            connection_state=connection_state,
            errors=errors,
            limitations=limitations,
            retrieved_at=now_utc(),
        )
    except LookupError:
        connection_state = _connection_state(adapter)
        if not _provider_ready(connection_state):
            return _policy_unavailable_response(result_id)
        return PolicySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.NO_EVIDENCE,
            connection_state=connection_state,
            limitations=[NO_RECORD_LIMITATION],
            retrieved_at=now_utc(),
        )

    connection_state = _connection_state(adapter)
    if not _provider_ready(connection_state):
        return _policy_unavailable_response(result_id)
    try:
        record = map_policy_provider_payload(
            retrieval_id=result_id,
            claim_id=claim.claim_id,
            envelope=envelope,
        )
    except ValidationError as error:
        raise _malformed_provider_error('policy', error) from error
    persist_retrieval_record(repository, record, claim.customer_id)
    return PolicySearchResponse(
        result_id=result_id,
        status=_status_for(record),
        connection_state=connection_state,
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
    connection_state = _connection_state(adapter)
    if not _provider_ready(connection_state):
        return _history_unavailable_response(result_id)

    try:
        envelope = adapter.search_claim_history(payload)
    except RetrievalUnavailable as unavailable:
        status, connection_state, errors, limitations = _failure_projection(
            unavailable.code,
            timeout_message=HISTORY_TIMEOUT_LIMITATION,
            unavailable_message=HISTORY_UNAVAILABLE_LIMITATION,
        )
        return ClaimHistorySearchResponse(
            result_id=result_id,
            status=status,
            connection_state=connection_state,
            errors=errors,
            limitations=limitations,
            retrieved_at=now_utc(),
        )
    except LookupError:
        connection_state = _connection_state(adapter)
        if not _provider_ready(connection_state):
            return _history_unavailable_response(result_id)
        return ClaimHistorySearchResponse(
            result_id=result_id,
            status=RetrievalStatus.NO_EVIDENCE,
            connection_state=connection_state,
            limitations=[NO_RECORD_LIMITATION],
            retrieved_at=now_utc(),
        )

    connection_state = _connection_state(adapter)
    if not _provider_ready(connection_state):
        return _history_unavailable_response(result_id)
    try:
        record = map_history_provider_payload(
            retrieval_id=result_id,
            claim_id=claim.claim_id,
            envelope=envelope,
        )
    except ValidationError as error:
        raise _malformed_provider_error('claim-history', error) from error
    persist_retrieval_record(repository, record, claim.customer_id)
    return ClaimHistorySearchResponse(
        result_id=result_id,
        status=_status_for(record),
        connection_state=connection_state,
        source=record.source,
        facts=record.facts,
        uncertainty=record.uncertainty,
        retrieved_at=record.source.retrieved_at,
    )
