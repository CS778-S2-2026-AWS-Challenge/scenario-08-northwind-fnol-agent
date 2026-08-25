from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
)
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.models import (
    ActorType,
    AgentAction,
    AssessorRoutingFailureCode,
    AssessorRoutingOperation,
    AssessorRoutingOperationStatus,
    AssessorRoutingResult,
    AssessorRoutingStatus,
    AuthorityOutcome,
    ClaimCreationStatus,
    CreateExternalClaimRequest,
    CustomerNextStep,
    ExternalClaimResult,
    ExternalServiceConsentStatus,
    FormStatus,
    ResponsibleParty,
    RouteAssessorRequest,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.support import now_utc, request_fingerprint


def _claim_not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The working claim was not found.',
    )


def _authorisation_error(message: str) -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=message,
    )


def _idempotency_error() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The integration request was already accepted with different data.',
    )


def _assessor_operation_id(payload: RouteAssessorRequest) -> str:
    identity = {
        'claim_id': payload.claim_id,
        'external_claim_id': payload.external_claim_id,
        'authorisation_ref': payload.authorisation_ref,
        'claimant_consent_ref': payload.claimant_consent_ref,
        'requested_action': payload.requested_action,
    }
    return f'asr_op_{request_fingerprint(identity)}'


def _assessor_failure_error(failure_code: AssessorRoutingFailureCode) -> ApiError:
    unavailable = failure_code in {
        AssessorRoutingFailureCode.TIMEOUT,
        AssessorRoutingFailureCode.UNAVAILABLE,
    }
    messages = {
        AssessorRoutingFailureCode.TIMEOUT: (
            'The assessment request did not complete. The claim is saved and the same '
            'request can be retried safely.'
        ),
        AssessorRoutingFailureCode.UNAVAILABLE: (
            'The assessment service is unavailable. The claim is saved and no assessor '
            'has been assigned.'
        ),
        AssessorRoutingFailureCode.ACCESS_DENIED: (
            'The assessment service did not accept the request authority. Northwind must '
            'review access before retrying.'
        ),
        AssessorRoutingFailureCode.MALFORMED: (
            'The assessment service returned an unusable response. The claim is saved and '
            'the adapter mapping must be reviewed.'
        ),
    }
    return ApiError(
        status_code=503 if unavailable else 502,
        code='DEPENDENCY_UNAVAILABLE' if unavailable else 'DEPENDENCY_FAILED',
        message=messages[failure_code],
        details=[ErrorDetail(field='assessor_service', reason=failure_code.value)],
        retryable=unavailable,
    )


def _save_claim(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    expected_revision: int,
) -> None:
    try:
        repository.save_claim(claim, expected_revision)
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while the integration request was running.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict


def create_external_claim(
    repository: PersistenceRepository,
    adapter: ClaimsServiceAdapter,
    payload: CreateExternalClaimRequest,
) -> tuple[ExternalClaimResult, bool]:
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    claim = repository.get_claim_internal(payload.working_claim_id)
    if claim is None:
        raise _claim_not_found()

    if claim.external_claim is not None:
        if claim.external_claim_fingerprint != fingerprint:
            raise _idempotency_error()
        return claim.external_claim, True

    if claim.revision != payload.claim_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after claim creation was authorised.',
            retryable=True,
            current_revision=claim.revision,
        )

    decision = repository.get_agent_decision_internal(
        payload.working_claim_id,
        payload.authorised_decision_id,
    )
    if (
        decision is None
        or decision.action is not AgentAction.CREATE_CLAIM
        or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        or 'CLAIM_CREATION_AUTHORISED' not in decision.reason_codes
    ):
        raise _authorisation_error(
            'Claim creation requires an authorised CREATE_CLAIM decision.',
        )
    if decision.resulting_revision != payload.claim_revision:
        raise _authorisation_error('The authorising decision does not match this claim revision.')

    confirmed_form = {
        field_code: field
        for field_code, field in claim.form.items()
        if field.status is FormStatus.CONFIRMED
    }
    if payload.confirmed_form != confirmed_form:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='The confirmed form does not match the persisted claim.',
            details=[
                ErrorDetail(
                    field='confirmed_form',
                    reason='Send the complete persisted set of confirmed fields.',
                )
            ],
        )

    evidence_records = {
        evidence_id: repository.get_evidence(
            payload.working_claim_id,
            evidence_id,
            claim.customer_id,
        )
        for evidence_id in payload.evidence_refs
    }
    missing_evidence = [
        evidence_id for evidence_id, record in evidence_records.items() if record is None
    ]
    pending_invalid: list[str] = []
    for item in payload.pending_evidence:
        evidence = evidence_records.get(item.evidence_id)
        if evidence is None or evidence.kind != item.kind:
            pending_invalid.append(item.evidence_id)
    if missing_evidence or pending_invalid:
        invalid = sorted(set(missing_evidence + pending_invalid))
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='One or more evidence references do not match the working claim.',
            details=[
                ErrorDetail(field='evidence_refs', reason=f'Invalid evidence: {evidence_id}.')
                for evidence_id in invalid
            ],
        )

    try:
        outcome = adapter.create_claim(payload, fingerprint)
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict

    timestamp = now_utc()
    created = outcome.result.creation_status is ClaimCreationStatus.CREATED
    updated_claim = claim.model_copy(
        update={
            'external_claim': outcome.result,
            'external_claim_source_revision': payload.claim_revision,
            'external_claim_fingerprint': fingerprint,
            'route': outcome.result.route,
            'claim_state': claim.claim_state.model_copy(
                update={
                    'workflow_state': (
                        WorkflowState.CREATED if created else claim.claim_state.workflow_state
                    ),
                    'next_action': AgentAction.PROCEED,
                }
            ),
            'customer_next_step': CustomerNextStep(
                status='claim_created' if created else 'claim_creation_pending',
                summary=outcome.result.next_step,
                responsible_party=ResponsibleParty.NORTHWIND,
                expected_by=outcome.result.expected_by,
            ),
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    _save_claim(repository, updated_claim, claim.revision)
    return outcome.result, outcome.replayed


def route_assessor(
    repository: PersistenceRepository,
    adapter: AssessorServiceAdapter,
    payload: RouteAssessorRequest,
) -> tuple[AssessorRoutingResult, bool]:
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    operation_id = _assessor_operation_id(payload)
    claim = repository.get_claim_internal(payload.claim_id)
    if claim is None:
        raise _claim_not_found()
    if (
        claim.external_claim is None
        or claim.external_claim.external_claim_id != payload.external_claim_id
    ):
        raise _authorisation_error('Assessor routing requires the matching created claim.')

    if claim.assessor_routing is not None:
        if claim.assessor_routing_fingerprint != fingerprint:
            raise _idempotency_error()
        return claim.assessor_routing, True

    operation = repository.get_assessor_routing_operation(operation_id)
    if operation is not None and operation.request_fingerprint != fingerprint:
        raise _idempotency_error()

    if operation is not None and operation.status is AssessorRoutingOperationStatus.ACCEPTED:
        assert operation.result is not None
        return _save_assessor_result(
            repository,
            payload.claim_id,
            fingerprint,
            operation.result,
            replayed=True,
        )
    if (
        operation is not None
        and operation.status is AssessorRoutingOperationStatus.TERMINAL_FAILURE
    ):
        assert operation.failure_code is not None
        raise _assessor_failure_error(operation.failure_code)

    consent = next(
        (
            record
            for record in reversed(claim.external_service_consents)
            if record.consent_ref == payload.claimant_consent_ref
        ),
        None,
    )
    required_consent_fields = {
        'claim_id',
        'external_claim_id',
        'authorisation_ref',
        'claimant_consent_ref',
        'requested_action',
        'location.region',
    }
    if (
        consent is None
        or consent.status is not ExternalServiceConsentStatus.GRANTED
        or consent.service_identity != 'vehicle_damage_assessment_routing'
        or consent.requested_action != payload.requested_action
        or not required_consent_fields.issubset(consent.permitted_fields)
        or consent.granted_by.actor_type is not ActorType.CLAIMANT
        or consent.granted_by.actor_id != claim.customer_id
    ):
        raise _authorisation_error(
            'Assessor routing requires matching active claimant consent for the minimum '
            'data scope.',
        )

    decision = repository.get_agent_decision_internal(
        payload.claim_id,
        payload.authorisation_ref,
    )
    if (
        decision is None
        or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        or 'ASSESSOR_RULE_AUTHORISED' not in decision.reason_codes
        or decision.resulting_revision != claim.revision
        or (operation is not None and operation.authorised_revision != claim.revision)
    ):
        raise _authorisation_error(
            'Assessor routing requires current authority for this claim revision.',
        )

    if operation is None:
        timestamp = now_utc()
        operation = AssessorRoutingOperation(
            operation_id=operation_id,
            claim_id=payload.claim_id,
            external_claim_id=payload.external_claim_id,
            authorisation_ref=payload.authorisation_ref,
            claimant_consent_ref=payload.claimant_consent_ref,
            requested_action=payload.requested_action,
            authorised_revision=claim.revision,
            request_fingerprint=fingerprint,
            status=AssessorRoutingOperationStatus.PREPARED,
            created_at=timestamp,
            updated_at=timestamp,
        )
        try:
            repository.save_assessor_routing_operation(operation)
        except IdempotencyConflict as conflict:
            raise _idempotency_error() from conflict

    try:
        outcome = adapter.route_assessor(payload, fingerprint)
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict
    except AssessorAdapterFailure as failure:
        unavailable = failure.code in {
            AssessorFixtureFailure.TIMEOUT,
            AssessorFixtureFailure.UNAVAILABLE,
        }
        failed_operation = operation.model_copy(
            update={
                'status': (
                    AssessorRoutingOperationStatus.RETRYABLE_FAILURE
                    if unavailable
                    else AssessorRoutingOperationStatus.TERMINAL_FAILURE
                ),
                'failure_code': failure.code,
                'updated_at': now_utc(),
            }
        )
        repository.save_assessor_routing_operation(failed_operation)
        raise _assessor_failure_error(failure.code) from failure

    if outcome.result.routing_status not in {
        AssessorRoutingStatus.ASSIGNED,
        AssessorRoutingStatus.QUEUED,
    }:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessment service returned a non-success routing state.',
            details=[
                ErrorDetail(
                    field='routing_status',
                    reason=outcome.result.routing_status.value,
                )
            ],
        )

    accepted_operation = operation.model_copy(
        update={
            'status': AssessorRoutingOperationStatus.ACCEPTED,
            'result': outcome.result,
            'failure_code': None,
            'updated_at': now_utc(),
        }
    )
    repository.save_assessor_routing_operation(accepted_operation)
    return _save_assessor_result(
        repository,
        payload.claim_id,
        fingerprint,
        outcome.result,
        replayed=outcome.replayed,
    )


def _save_assessor_result(
    repository: PersistenceRepository,
    claim_id: str,
    fingerprint: str,
    result: AssessorRoutingResult,
    *,
    replayed: bool,
) -> tuple[AssessorRoutingResult, bool]:
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()
    if claim.assessor_routing is not None:
        if claim.assessor_routing_fingerprint != fingerprint:
            raise _idempotency_error()
        return claim.assessor_routing, True

    timestamp = now_utc()
    assigned = result.routing_status is AssessorRoutingStatus.ASSIGNED
    updated_claim = claim.model_copy(
        update={
            'assessor_routing': result,
            'assessor_routing_fingerprint': fingerprint,
            'customer_next_step': CustomerNextStep(
                status='assessor_assigned' if assigned else 'awaiting_assessor_assignment',
                summary=result.next_step,
                responsible_party=ResponsibleParty.EXTERNAL_PARTY,
                expected_by=result.expected_by,
            ),
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    _save_claim(repository, updated_claim, claim.revision)
    return result, replayed
