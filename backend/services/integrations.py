from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
)
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.models import (
    AgentAction,
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
from backend.repositories.protocols import PersistenceRepository, RevisionConflict
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
    ):
        raise _authorisation_error(
            'Assessor routing requires matching active claimant consent for the minimum '
            'data scope.',
        )

    decision = repository.get_agent_decision_internal(payload.claim_id, payload.authorisation_ref)
    if (
        decision is None
        or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        or 'ASSESSOR_RULE_AUTHORISED' not in decision.reason_codes
        or decision.resulting_revision != claim.revision
    ):
        raise _authorisation_error(
            'Assessor routing requires an authorised rule or staff decision.',
        )

    try:
        outcome = adapter.route_assessor(payload, fingerprint)
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict
    except AssessorAdapterFailure as failure:
        unavailable = failure.code in {
            AssessorFixtureFailure.TIMEOUT,
            AssessorFixtureFailure.UNAVAILABLE,
        }
        messages = {
            AssessorFixtureFailure.TIMEOUT: (
                'The assessment request did not complete. The claim is saved and the same '
                'request can be retried safely.'
            ),
            AssessorFixtureFailure.UNAVAILABLE: (
                'The assessment service is unavailable. The claim is saved and no assessor '
                'has been assigned.'
            ),
            AssessorFixtureFailure.ACCESS_DENIED: (
                'The assessment service did not accept the request authority. Northwind must '
                'review access before retrying.'
            ),
            AssessorFixtureFailure.MALFORMED: (
                'The assessment service returned an unusable response. The claim is saved and '
                'the adapter mapping must be reviewed.'
            ),
        }
        raise ApiError(
            status_code=503 if unavailable else 502,
            code='DEPENDENCY_UNAVAILABLE' if unavailable else 'DEPENDENCY_FAILED',
            message=messages[failure.code],
            details=[ErrorDetail(field='assessor_service', reason=failure.code.value)],
            retryable=unavailable,
        ) from failure

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

    timestamp = now_utc()
    assigned = outcome.result.routing_status is AssessorRoutingStatus.ASSIGNED
    updated_claim = claim.model_copy(
        update={
            'assessor_routing': outcome.result,
            'assessor_routing_fingerprint': fingerprint,
            'customer_next_step': CustomerNextStep(
                status='assessor_assigned' if assigned else 'awaiting_assessor_assignment',
                summary=outcome.result.next_step,
                responsible_party=ResponsibleParty.EXTERNAL_PARTY,
                expected_by=outcome.result.expected_by,
            ),
            'revision': claim.revision + 1,
            'updated_at': timestamp,
        }
    )
    _save_claim(repository, updated_claim, claim.revision)
    return outcome.result, outcome.replayed
