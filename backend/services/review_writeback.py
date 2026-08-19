from typing import Any

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    SignalDecisionRecord,
    SignalDecisionRequest,
    SignalDecisionResponse,
    WorkbenchClaimDetail,
    WorkingClaim,
)
from backend.domain.retrieval import ReviewSignalRecord
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.staff_actions import decide_signal
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)
from backend.services.workbench import get_workbench_claim_detail


def _staff_claim(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkingClaim:
    if principal.actor_type != 'staff':
        raise ApiError(status_code=403, code='ACCESS_DENIED', message='Staff access is required.')
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )
    return claim


def _persisted_signal(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    signal_id: str,
) -> ReviewSignalRecord | None:
    return next(
        (
            signal
            for signal in repository.list_review_signals(claim.claim_id, claim.customer_id)
            if signal.signal_id == signal_id
        ),
        None,
    )


def _retry(
    repository: PersistenceRepository,
    actor_id: str,
    route: str,
    key: str,
    fingerprint: str,
) -> dict[str, Any] | None:
    record = repository.find_idempotency(actor_id, route, key)
    if record is None:
        return None
    if record.request_fingerprint != fingerprint:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The idempotency key was reused with a different request.',
        )
    if record.response_payload is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The staff operation could not be restored.',
            retryable=True,
        )
    return record.response_payload


def _save_decision(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
    idempotency: IdempotencyRecord,
    decision: SignalDecisionRecord,
) -> None:
    try:
        repository.save_staff_mutation(
            claim,
            expected_revision,
            idempotency,
            signal_decision=decision,
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise ApiError(
            status_code=409,
            code='IDEMPOTENCY_CONFLICT',
            message='The staff operation was already accepted with different data.',
        ) from conflict


def _source_evidence(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    signal: ReviewSignalRecord,
) -> list[dict[str, Any]]:
    records = repository.list_retrieval_records(claim.claim_id, claim.customer_id)
    by_id = {record.retrieval_id: record for record in records}
    return [
        by_id[source_ref].model_dump(mode='json')
        for source_ref in signal.source_refs
        if source_ref in by_id
    ]


def get_review_connected_workbench_detail(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> WorkbenchClaimDetail:
    detail = get_workbench_claim_detail(repository, principal, claim_id)
    claim = _staff_claim(repository, principal, claim_id)
    persisted_signals = repository.list_review_signals(claim_id, claim.customer_id)

    signals_by_id: dict[str, dict[str, Any]] = {}
    signal_order: list[str] = []
    for existing_signal in detail.signals:
        signal_id = str(existing_signal.get('signal_id') or existing_signal.get('code') or '')
        if not signal_id:
            continue
        signals_by_id[signal_id] = dict(existing_signal)
        signal_order.append(signal_id)

    for persisted_signal in persisted_signals:
        value: dict[str, Any] = persisted_signal.model_dump(mode='json')
        value['source_evidence'] = _source_evidence(repository, claim, persisted_signal)
        existing = signals_by_id.get(persisted_signal.signal_id)
        if existing is not None and isinstance(existing.get('decisions'), list):
            value['decisions'] = existing['decisions']
        if persisted_signal.signal_id not in signals_by_id:
            signal_order.append(persisted_signal.signal_id)
        signals_by_id[persisted_signal.signal_id] = value

    return detail.model_copy(
        update={'signals': [signals_by_id[signal_id] for signal_id in signal_order]}
    )


def decide_review_signal(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    signal_id: str,
    payload: SignalDecisionRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> SignalDecisionResponse:
    claim = _staff_claim(repository, principal, claim_id)
    signal = _persisted_signal(repository, claim, signal_id)
    if signal is None:
        return decide_signal(
            repository,
            principal,
            claim_id,
            signal_id,
            payload,
            idempotency_key,
            if_match,
        )

    key = require_idempotency_key(idempotency_key)
    expected = parse_if_match(if_match)
    route = f'/api/v1/workbench/claims/{claim_id}/signals/{signal_id}/decisions'
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    replay = _retry(repository, principal.subject, route, key, fingerprint)
    if replay is not None:
        return SignalDecisionResponse.model_validate(replay)
    if claim.revision != expected:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )

    timestamp = now_utc()
    evidence_refs = list(dict.fromkeys([*signal.source_refs, *payload.evidence_refs]))
    decision = SignalDecisionRecord(
        decision=payload.decision,
        reason_codes=payload.reason_codes,
        summary=payload.summary,
        evidence_refs=evidence_refs,
        signal_decision_id=new_id('sdec'),
        claim_id=claim_id,
        signal_id=signal_id,
        actor_id=principal.subject,
        created_at=timestamp,
    )
    updated = claim.model_copy(update={'revision': claim.revision + 1, 'updated_at': timestamp})
    response = SignalDecisionResponse(signal_decision=decision, revision=updated.revision)
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id='',
        response_payload=response.model_dump(mode='json'),
    )
    _save_decision(repository, updated, expected, idempotency, decision)
    return response
