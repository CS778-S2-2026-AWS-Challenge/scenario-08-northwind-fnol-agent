from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorFixtureFailure,
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
)
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.external_services import (
    ASSESSOR_CONSENT_FIELDS,
    ASSESSOR_SERVICE_IDENTITY,
    ExternalTaskAuthorisation,
    ExternalTaskDelivery,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskRequest,
    assert_disclosure_within_consent,
    assert_request_matches_task,
)
from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentDecisionRecord,
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
    ExternalServiceConsent,
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
from backend.services.external_service_entry import (
    ExternalServiceEntryDecision,
    assert_task_matches_entry,
)
from backend.services.support import now_utc, request_fingerprint

_ASSESSOR_REQUEST_PURPOSE = (
    'Route the vehicle damage assessment request using the confirmed incident region. '
    'This does not decide coverage or approve repairs.'
)


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


def assessor_operation_id(payload: RouteAssessorRequest) -> str:
    identity = {
        'claim_id': payload.claim_id,
        'external_claim_id': payload.external_claim_id,
        'authorisation_ref': payload.authorisation_ref,
        'claimant_consent_ref': payload.claimant_consent_ref,
        'requested_action': payload.requested_action,
    }
    return f'asr_op_{request_fingerprint(identity)}'


def _external_task_id(operation_id: str) -> str:
    return f'tsk_{request_fingerprint({"operation_id": operation_id})[:24]}'


def _external_request_id(operation_id: str) -> str:
    return f'erq_{request_fingerprint({"operation_id": operation_id})[:24]}'


def _external_service_unavailable(decision: ExternalServiceEntryDecision) -> ApiError:
    return ApiError(
        status_code=503,
        code='DEPENDENCY_UNAVAILABLE',
        message=decision.limitation or 'The assessment service is unavailable.',
        details=[ErrorDetail(field='assessor_service', reason=decision.entry.value)],
        retryable=False,
    )


def _prepare_external_request(
    repository: PersistenceRepository,
    *,
    claim: WorkingClaim,
    consent: ExternalServiceConsent,
    operation: AssessorRoutingOperation,
    entry_decision: ExternalServiceEntryDecision,
) -> tuple[ExternalTaskRecord, ExternalTaskRequest]:
    source = entry_decision.integration_source
    if source is None:
        raise _external_service_unavailable(entry_decision)
    task = ExternalTaskRecord(
        task_id=_external_task_id(operation.operation_id),
        claim_id=operation.claim_id,
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=operation.requested_action,
        integration_source=source,
        status=ExternalTaskOperationStatus.PREPARED,
        created_at=operation.created_at,
        updated_at=operation.created_at,
    )
    request = ExternalTaskRequest(
        request_id=_external_request_id(operation.operation_id),
        task_id=task.task_id,
        claim_id=operation.claim_id,
        service_identity=task.service_identity,
        requested_action=task.requested_action,
        purpose=_ASSESSOR_REQUEST_PURPOSE,
        disclosed_fields=sorted(ASSESSOR_CONSENT_FIELDS),
        authorisation=ExternalTaskAuthorisation(
            northwind_authority_ref=operation.authorisation_ref,
            claimant_consent_ref=operation.claimant_consent_ref,
            authorised_revision=operation.authorised_revision,
        ),
        prepared_at=operation.created_at,
    )
    assert_task_matches_entry(task, entry_decision)
    assert_request_matches_task(request, task)
    assert_disclosure_within_consent(
        request,
        consent,
        claim_customer_id=claim.customer_id,
    )
    try:
        repository.save_external_task(task, claim.customer_id)
        existing = next(
            (
                held
                for held in repository.list_external_task_requests_internal(claim.claim_id)
                if held.request_id == request.request_id
            ),
            None,
        )
        if existing is None:
            repository.save_external_task_request(request, claim.customer_id)
        else:
            assert_request_matches_task(existing, task)
            request = existing
    except (IdempotencyConflict, KeyError, ValueError) as conflict:
        raise _idempotency_error() from conflict
    return task, request


def _record_external_send(
    repository: PersistenceRepository,
    *,
    request: ExternalTaskRequest,
    customer_id: str,
    operation_id: str,
) -> ExternalTaskRequest:
    if request.sent_at is not None:
        return request
    sent = request.model_copy(
        update={
            'sent_at': now_utc(),
            'operation_id': operation_id,
        }
    )
    try:
        repository.save_external_task_request(sent, customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    return sent


def _record_external_acceptance(
    repository: PersistenceRepository,
    *,
    task: ExternalTaskRecord,
    customer_id: str,
    provider_reference: str,
) -> None:
    accepted = task.model_copy(
        update={
            'status': ExternalTaskOperationStatus.ACCEPTED,
            'delivery': ExternalTaskDelivery.SUBMITTED,
            'delivery_evidence': (
                f'{task.integration_source.value} routing acknowledgement: {provider_reference}'
            ),
            'provider_reference': provider_reference,
            'updated_at': now_utc(),
        }
    )
    try:
        repository.save_external_task(accepted, customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict


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
            'assignee_id': (
                'stf_demo' if payload.route == 'standard_motor_intake' else claim.assignee_id
            ),
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
    entry_decision: ExternalServiceEntryDecision,
    payload: RouteAssessorRequest,
    *,
    authorisation_decision: AgentDecisionRecord | None = None,
) -> tuple[AssessorRoutingResult, bool]:
    fingerprint = request_fingerprint(payload.model_dump(mode='json'))
    operation_id = assessor_operation_id(payload)
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
        task_id = _external_task_id(operation.operation_id)
        task = next(
            (
                item
                for item in repository.list_external_tasks_internal(operation.claim_id)
                if item.task_id == task_id
            ),
            None,
        )
        if task is not None and task.status is ExternalTaskOperationStatus.PREPARED:
            provider_reference = (
                operation.result.assessor_reference or operation.result.queue_reference
            )
            assert provider_reference is not None
            _record_external_acceptance(
                repository,
                task=task,
                customer_id=claim.customer_id,
                provider_reference=provider_reference,
            )
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
    if (
        consent is None
        or consent.status is not ExternalServiceConsentStatus.GRANTED
        or consent.service_identity != ASSESSOR_SERVICE_IDENTITY
        or consent.requested_action != payload.requested_action
        or not ASSESSOR_CONSENT_FIELDS.issubset(consent.permitted_fields)
        or consent.granted_by.actor_type is not ActorType.CLAIMANT
        or consent.granted_by.actor_id != claim.customer_id
    ):
        raise _authorisation_error(
            'Assessor routing requires matching active claimant consent for the minimum '
            'data scope.',
        )

    decision = (
        authorisation_decision
        if operation is None and authorisation_decision is not None
        else repository.get_agent_decision_internal(
            payload.claim_id,
            payload.authorisation_ref,
        )
    )
    if (
        decision is None
        or decision.decision_id != payload.authorisation_ref
        or decision.claim_id != payload.claim_id
        or decision.authority.outcome is not AuthorityOutcome.AUTHORISED
        or 'ASSESSOR_RULE_AUTHORISED' not in decision.reason_codes
        or decision.resulting_revision != claim.revision
        or (operation is not None and operation.authorised_revision != claim.revision)
    ):
        raise _authorisation_error(
            'Assessor routing requires current authority for this claim revision.',
        )

    if entry_decision.integration_source is None:
        raise _external_service_unavailable(entry_decision)

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
            if authorisation_decision is None:
                repository.save_assessor_routing_operation(operation)
            else:
                repository.save_assessor_routing_preparation(
                    operation,
                    authorisation_decision,
                    claim.customer_id,
                )
        except IdempotencyConflict as conflict:
            raise _idempotency_error() from conflict

    task, external_request = _prepare_external_request(
        repository,
        claim=claim,
        consent=consent,
        operation=operation,
        entry_decision=entry_decision,
    )

    try:
        outcome = adapter.route_assessor(payload, fingerprint)
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict
    except AssessorAdapterFailure as failure:
        _record_external_send(
            repository,
            request=external_request,
            customer_id=claim.customer_id,
            operation_id=operation.operation_id,
        )
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

    _record_external_send(
        repository,
        request=external_request,
        customer_id=claim.customer_id,
        operation_id=operation.operation_id,
    )

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
    provider_reference = outcome.result.assessor_reference or outcome.result.queue_reference
    assert provider_reference is not None
    repository.save_assessor_routing_operation(accepted_operation)
    _record_external_acceptance(
        repository,
        task=task,
        customer_id=claim.customer_id,
        provider_reference=provider_reference,
    )
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
