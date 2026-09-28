"""Bounded claimant mutations for remaining Motor and Contents data contracts."""

from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.ids import new_id
from backend.domain.models import (
    ContentsItemEvidenceAssociation,
    ContentsItemEvidenceAssociationListResponse,
    ContentsItemEvidenceAssociationMutationResponse,
    ContentsItemEvidenceAssociationProjection,
    CreateContentsItemEvidenceAssociationRequest,
    CreateMotorOtherDriverRequest,
    DriverProjection,
    MotorOtherDriverMutationResponse,
    MotorOtherDriverProjection,
    MotorOtherDriverRecord,
    PolicyholderProjection,
    WitnessProjection,
    WorkingClaim,
)
from backend.repositories.pagination import InvalidRepositoryCursorError
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.protected_values import ProtectedValueAdapter, masked_value
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


def project_claim_participants(
    claim: WorkingClaim,
) -> tuple[PolicyholderProjection | None, DriverProjection | None, list[WitnessProjection]]:
    """Build role-safe Claim participant projections without exposing licence plaintext."""
    policyholder = (
        PolicyholderProjection.model_validate(claim.policyholder.model_dump())
        if claim.policyholder is not None
        else None
    )
    driver = (
        DriverProjection.model_validate(claim.driver.model_dump(exclude={'licence_number'}))
        if claim.driver is not None
        else None
    )
    witnesses = [WitnessProjection.model_validate(item.model_dump()) for item in claim.witnesses]
    return policyholder, driver, witnesses


def _not_found(resource: str) -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message=f'The {resource} was not found.',
    )


def _revision_conflict(current_revision: int) -> ApiError:
    return ApiError(
        status_code=409,
        code='REVISION_CONFLICT',
        message='The Claim changed after this page was loaded.',
        retryable=True,
        current_revision=current_revision,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The Idempotency-Key was already used with a different request.',
    )


def _resource_conflict(field: str, reason: str) -> ApiError:
    return ApiError(
        status_code=409,
        code='RESOURCE_CONFLICT',
        message='The requested Claim data relationship already exists or is unavailable.',
        details=[ErrorDetail(field=field, reason=reason)],
    )


def _invalid_branch(field: str, reason: str) -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_FIELD_BRANCH',
        message='The requested data does not belong to this Claim family.',
        details=[ErrorDetail(field=field, reason=reason)],
    )


def _terminal_claim_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message='A terminal Claim cannot accept new Claim data.',
    )


def project_motor_other_driver(record: MotorOtherDriverRecord) -> MotorOtherDriverProjection:
    values = record.model_dump(
        exclude={'customer_id', 'source_refs', 'created_at', 'policy_number'}
    )
    values['policy_number_masked'] = record.policy_number_masked
    return MotorOtherDriverProjection.model_validate(values)


def project_contents_item_evidence_association(
    record: ContentsItemEvidenceAssociation,
) -> ContentsItemEvidenceAssociationProjection:
    return ContentsItemEvidenceAssociationProjection.model_validate(
        record.model_dump(exclude={'customer_id'})
    )


def create_motor_other_driver(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: CreateMotorOtherDriverRequest,
    idempotency_key: str | None,
    if_match: str | None,
    protected_values: ProtectedValueAdapter | None = None,
) -> MotorOtherDriverMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/motor-other-driver'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'payload': payload.model_dump(mode='json'),
            'expected_revision': expected_revision,
        }
    )
    replay = repository.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        return MotorOtherDriverMutationResponse.model_validate(replay.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('Claim')
    if claim.revision != expected_revision:
        raise _revision_conflict(claim.revision)
    if claim.terminal_disposition is not None:
        raise _terminal_claim_conflict()
    if claim.incident_type != 'motor':
        raise _invalid_branch('claim_id', 'An other-driver record is available only for Motor.')
    if repository.get_motor_other_driver(claim_id, principal.subject) is not None:
        raise _resource_conflict(
            'claim_id', 'This Motor Claim already has its bounded other-driver record.'
        )

    timestamp = now_utc()
    raw_policy_number = payload.policy_number
    record = MotorOtherDriverRecord(
        participant_id=new_id('par'),
        claim_id=claim_id,
        customer_id=principal.subject,
        **payload.model_dump(exclude={'policy_number'}),
        policy_number=(
            protected_values.seal(raw_policy_number)
            if raw_policy_number is not None and protected_values is not None
            else raw_policy_number
        ),
        policy_number_masked=(
            masked_value(raw_policy_number) if raw_policy_number is not None else None
        ),
        source_refs=[f'claim:{claim_id}:revision:{expected_revision}'],
        created_at=timestamp,
        updated_at=timestamp,
    )
    updated_claim = claim.model_copy(
        update={'revision': claim.revision + 1, 'updated_at': timestamp}
    )
    response = MotorOtherDriverMutationResponse(
        participant=project_motor_other_driver(record),
        revision=updated_claim.revision,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    try:
        repository.save_motor_other_driver_mutation(
            updated_claim, expected_revision, record, idempotency
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    except IdempotencyConflict as error:
        replay = repository.find_idempotency(principal.subject, route, key)
        if (
            replay is not None
            and replay.request_fingerprint == fingerprint
            and replay.response_payload is not None
        ):
            return MotorOtherDriverMutationResponse.model_validate(replay.response_payload)
        raise _resource_conflict(
            'claim_id', 'This Motor Claim already has its bounded other-driver record.'
        ) from error
    return response


def get_motor_other_driver(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
) -> MotorOtherDriverProjection:
    record = repository.get_motor_other_driver(claim_id, principal.subject)
    if record is None:
        raise _not_found('Motor other-driver record')
    return project_motor_other_driver(record)


def create_contents_item_evidence_association(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    item_id: str,
    payload: CreateContentsItemEvidenceAssociationRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> ContentsItemEvidenceAssociationMutationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/contents-items/{item_id}/evidence-associations'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'item_id': item_id,
            'payload': payload.model_dump(mode='json'),
            'expected_revision': expected_revision,
        }
    )
    replay = repository.find_idempotency(principal.subject, route, key)
    if replay is not None:
        if replay.request_fingerprint != fingerprint or replay.response_payload is None:
            raise _idempotency_conflict()
        return ContentsItemEvidenceAssociationMutationResponse.model_validate(
            replay.response_payload
        )

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('Claim')
    if claim.revision != expected_revision:
        raise _revision_conflict(claim.revision)
    if claim.terminal_disposition is not None:
        raise _terminal_claim_conflict()
    if claim.incident_type != 'contents':
        raise _invalid_branch('claim_id', 'Item Evidence associations require Contents.')
    if not any(item.item_id == item_id for item in claim.contents_items):
        raise _not_found('Contents item')
    if repository.get_evidence(claim_id, payload.evidence_id, principal.subject) is None:
        # Conceal both unavailable and cross-Claim Evidence behind the same response.
        raise _not_found('Evidence')
    existing = repository.list_contents_item_evidence_associations(claim_id, principal.subject)
    if any(
        item.item_id == item_id and item.evidence_id == payload.evidence_id for item in existing
    ):
        raise _resource_conflict(
            'evidence_id', 'This Evidence is already associated with the Contents item.'
        )

    timestamp = now_utc()
    association = ContentsItemEvidenceAssociation(
        association_id=new_id('iea'),
        claim_id=claim_id,
        customer_id=principal.subject,
        item_id=item_id,
        evidence_id=payload.evidence_id,
        purpose=payload.purpose,
        created_at=timestamp,
    )
    updated_claim = claim.model_copy(
        update={'revision': claim.revision + 1, 'updated_at': timestamp}
    )
    response = ContentsItemEvidenceAssociationMutationResponse(
        association=project_contents_item_evidence_association(association),
        revision=updated_claim.revision,
    )
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=claim_id,
        session_id=claim.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    try:
        repository.save_contents_item_evidence_association_mutation(
            updated_claim, expected_revision, association, idempotency
        )
    except RevisionConflict as error:
        raise _revision_conflict(error.current_revision) from error
    except KeyError as error:
        raise _not_found('Evidence') from error
    except IdempotencyConflict as error:
        replay = repository.find_idempotency(principal.subject, route, key)
        if (
            replay is not None
            and replay.request_fingerprint == fingerprint
            and replay.response_payload is not None
        ):
            return ContentsItemEvidenceAssociationMutationResponse.model_validate(
                replay.response_payload
            )
        raise _resource_conflict(
            'evidence_id', 'This Evidence is already associated with the Contents item.'
        ) from error
    return response


def list_contents_item_evidence_associations(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    item_id: str,
    *,
    limit: int,
    cursor: str | None,
) -> ContentsItemEvidenceAssociationListResponse:
    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found('Claim')
    if not any(item.item_id == item_id for item in claim.contents_items):
        raise _not_found('Contents item')
    try:
        records, next_cursor = repository.list_contents_item_evidence_association_page(
            claim_id,
            principal.subject,
            item_id,
            limit=limit,
            cursor=cursor,
        )
    except InvalidRepositoryCursorError as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The pagination cursor is invalid.',
            details=[ErrorDetail(field='cursor', reason='Use a cursor returned by this API.')],
        ) from error
    return ContentsItemEvidenceAssociationListResponse(
        items=[project_contents_item_evidence_association(item) for item in records],
        page={'next_cursor': next_cursor},
    )
