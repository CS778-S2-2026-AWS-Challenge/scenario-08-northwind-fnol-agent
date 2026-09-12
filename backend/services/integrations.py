from datetime import timedelta

from backend.adapters.claims_service import (
    AdapterIdempotencyConflict,
    AssessorAdapterFailure,
    AssessorReconciliationRequest,
    AssessorResultRequest,
    AssessorServiceAdapter,
    ClaimsServiceAdapter,
)
from backend.adapters.evidence_storage import (
    EvidenceContentConflict,
    EvidenceStorage,
    EvidenceStorageUnavailable,
    EvidenceUploadTooLarge,
)
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.evidence import evidence_state_for, evidence_summary_for
from backend.domain.external_services import (
    ASSESSOR_CONSENT_FIELDS,
    ASSESSOR_SERVICE_IDENTITY,
    ExternalTaskAuthorisation,
    ExternalTaskDelivery,
    ExternalTaskEvidenceLink,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
    ExternalTaskRequest,
    ExternalTaskResult,
    ExternalTaskResultVerification,
    UntraceableExternalEvidenceError,
    assert_disclosure_within_consent,
    assert_request_matches_task,
    assert_task_transition_is_permitted,
    classify_external_task_failure,
    external_task_for_evidence,
    verify_external_task_result,
)
from backend.domain.models import (
    ActorReference,
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
    ClaimTerminalDisposition,
    CreateExternalClaimRequest,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    EvidenceWaitType,
    ExternalClaimResult,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    FormStatus,
    IntegrationSource,
    ResponsibleParty,
    RouteAssessorRequest,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkflowState,
    WorkingClaim,
)
from backend.domain.retrieval import RetrievalSource
from backend.repositories.protocols import (
    IdempotencyConflict,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.external_service_entry import (
    ExternalServiceEntryDecision,
    assert_task_matches_entry,
)
from backend.services.support import now_utc, request_fingerprint, require_idempotency_key

# The Evidence kind the awaited assessment is recorded under. `tag_projection`
# already recognises it, so material a task owes raises the same staff signals as
# material that arrived.
_AWAITED_ASSESSMENT_KIND = 'assessment_report'
_REPLAYABLE_TASK_STATUSES = frozenset(
    {ExternalTaskOperationStatus.PREPARED, ExternalTaskOperationStatus.ACCEPTED}
)

# The routing operation records the same outcome the task does. Only these three
# reach the map: an attempt that raised from the adapter neither stayed prepared nor
# was accepted.
_OPERATION_STATUS_BY_TASK_STATUS = {
    ExternalTaskOperationStatus.RETRYABLE_FAILURE: (
        AssessorRoutingOperationStatus.RETRYABLE_FAILURE
    ),
    ExternalTaskOperationStatus.TERMINAL_FAILURE: AssessorRoutingOperationStatus.TERMINAL_FAILURE,
    ExternalTaskOperationStatus.UNKNOWN_OUTCOME: AssessorRoutingOperationStatus.UNKNOWN_OUTCOME,
}

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


def _external_result_id(task_id: str) -> str:
    return f'res_{request_fingerprint({"task_id": task_id})[:24]}'


def _external_service_unavailable(decision: ExternalServiceEntryDecision) -> ApiError:
    """Report that no entry could serve this call, on the documented contract.

    `docs/api.md` ties `retryable` to the error code rather than to the cause, and
    `503 DEPENDENCY_UNAVAILABLE` is documented as retryable wherever it is raised.
    That holds here in the sense the recovery matrix uses: no request was sent, so
    nothing happened that a repeat could duplicate, and an unchanged attempt may be
    made again with the same operation identity. Whether the next attempt succeeds
    depends on the runtime capability, which is not what this flag reports.
    """

    return ApiError(
        status_code=503,
        code='DEPENDENCY_UNAVAILABLE',
        message=decision.limitation or 'The assessment service is unavailable.',
        details=[ErrorDetail(field='assessor_service', reason=decision.entry.value)],
        retryable=True,
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
    stored_task = next(
        (
            held
            for held in repository.list_external_tasks_internal(operation.claim_id)
            if held.task_id == task.task_id
        ),
        None,
    )
    if stored_task is not None:
        # A retry continues the task it already has. Rebuilding it as `prepared`
        # would assert that the earlier attempt had not been sent, which erases the
        # recorded failure and is what the transition guard refuses outright.
        task = stored_task
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
) -> ExternalTaskRecord:
    accepted = _accepted_external_task(task=task, provider_reference=provider_reference)
    try:
        repository.save_external_task(accepted, customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    return accepted


def _accepted_external_task(
    *,
    task: ExternalTaskRecord,
    provider_reference: str,
) -> ExternalTaskRecord:
    """Build the accepted successor of one external task.

    Args:
        task: Current task state to reconcile or advance.
        provider_reference: New acknowledgement supplied by the provider path.

    Returns:
        The validated accepted task successor.

    Raises:
        TaskTransitionNotPermittedError: Acceptance would violate task lifecycle.
    """

    updated_at = now_utc()
    # Preparation and provider acceptance can occur within one clock tick. The
    # persistence contract requires every changed task state to advance time.
    if updated_at <= task.updated_at:
        updated_at = task.updated_at + timedelta(microseconds=1)
    accepted = ExternalTaskRecord.model_validate(
        {
            **task.model_dump(),
            'status': ExternalTaskOperationStatus.ACCEPTED,
            'delivery': ExternalTaskDelivery.SUBMITTED,
            'delivery_evidence': (
                task.delivery_evidence
                if task.delivery is ExternalTaskDelivery.SUBMITTED
                else (
                    f'{task.integration_source.value} routing acknowledgement: {provider_reference}'
                )
            ),
            'failure_code': None,
            'provider_reference': provider_reference,
            'updated_at': updated_at,
        }
    )
    assert_task_transition_is_permitted(task, accepted)
    return accepted


def _record_awaited_material(
    repository: PersistenceRepository,
    *,
    task: ExternalTaskRecord,
    claim: WorkingClaim,
) -> None:
    """Record what an accepted task now owes the claim, and tie it to that task.

    `ExternalTaskEvidenceLink` ties an evidence record to the task that *produced or
    owes* it. Neither half had a producer: a claim that had requested an assessment
    looked exactly like one that had not, and nothing in the application ever
    constructed a link, so `external_task_for_evidence` had nothing to resolve.

    This records the owed half. The material is `pending` with `not_available`, the
    registered shape for a document that does not exist yet, and it stays that way until
    something records a provider result. An acknowledgement is not completion, so nothing
    here may read as an assessment that exists.

    The link is written with the record rather than left optional. External-system
    material without one is refused by `external_task_for_evidence` as untraceable, so
    creating the evidence alone would produce exactly the state that guard exists to
    reject.

    Both halves are checked, not one. An interrupted attempt can leave the evidence
    stored and the link lost, and a recorder that returned on the evidence alone could
    never repair that: it would read the record it wrote first and report success over a
    claim whose material still named no task. Whichever half is missing is written.

    What was stored is then read back and resolved through the guard before returning.
    The two writes are not one transaction, so a caller cannot conclude from a write
    that returned quietly that both halves are present; the only answer that means
    anything is the one the traceability boundary itself gives. If it cannot resolve the
    record to its task, the request fails as unfinished rather than reporting a success
    that left the invariant broken.

    Args:
        repository: Authoritative persistence boundary.
        task: The accepted task that owes the material.
        claim: The claim the task belongs to.

    Returns:
        None.
    """

    awaited, link = _awaited_material_records(task=task, claim=claim)
    evidence_id = awaited.evidence_id
    held = repository.get_evidence(claim.claim_id, evidence_id, claim.customer_id)
    linked = any(
        link.evidence_id == evidence_id and link.task_id == task.task_id
        for link in repository.list_external_task_evidence_links_internal(claim.claim_id)
    )
    if held is not None and linked:
        return

    try:
        if held is None:
            repository.save_evidence(awaited, claim.customer_id)
        if not linked:
            repository.save_external_task_evidence_link(link, claim.customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict

    stored = repository.get_evidence(claim.claim_id, evidence_id, claim.customer_id)
    if stored is None:
        raise _idempotency_error()
    try:
        external_task_for_evidence(
            stored,
            repository.list_external_task_evidence_links_internal(claim.claim_id),
        )
    except UntraceableExternalEvidenceError as untraceable:
        raise _idempotency_error() from untraceable


def _awaited_material_records(
    *,
    task: ExternalTaskRecord,
    claim: WorkingClaim,
) -> tuple[EvidenceRecord, ExternalTaskEvidenceLink]:
    """Build the pending material and traceability link an accepted task owes.

    Args:
        task: Accepted external task that owes the assessment material.
        claim: Claim that owns the task and evidence.

    Returns:
        The deterministic pending Evidence record and its immutable task link.

    Raises:
        ValueError: The task and Claim identities cannot form valid records.
    """

    evidence_id = f'evd_{task.task_id.removeprefix("tsk_")}'
    recorded_at = task.updated_at
    awaited = EvidenceRecord(
        evidence_id=evidence_id,
        claim_id=claim.claim_id,
        kind=_AWAITED_ASSESSMENT_KIND,
        status=EvidenceStatus.PENDING,
        file_status=EvidenceFileStatus.NOT_AVAILABLE,
        source=EvidenceSource.EXTERNAL_SYSTEM,
        needed_for=['later_action'],
        provenance={'external_task_id': task.task_id, 'service': task.service_identity},
        wait_type=EvidenceWaitType.EXTERNAL_AGENCY,
        responsible_party=ResponsibleParty.EXTERNAL_PARTY,
        context_summary=(
            'The assessment requested from the controlled assessor service has not been '
            'returned. The claim is waiting on the assessor, not on the claimant.'
        ),
        created_at=recorded_at,
        updated_at=recorded_at,
    )
    return awaited, ExternalTaskEvidenceLink(
        task_id=task.task_id,
        evidence_id=evidence_id,
        claim_id=claim.claim_id,
        linked_at=recorded_at,
    )


def _find_external_task(
    repository: PersistenceRepository,
    *,
    claim_id: str,
    task_id: str,
) -> ExternalTaskRecord | None:
    return next(
        (
            task
            for task in repository.list_external_tasks_internal(claim_id)
            if task.task_id == task_id
        ),
        None,
    )


def _bind_returned_evidence_to_claim(
    repository: PersistenceRepository,
    *,
    claim: WorkingClaim,
    evidence: EvidenceRecord,
) -> WorkingClaim:
    records = repository.list_evidence(claim.claim_id, claim.customer_id)
    updated_at = max(now_utc(), evidence.updated_at)
    updated_claim = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'updated_at': updated_at,
            'evidence_summary': evidence_summary_for(records),
            'claim_state': claim.claim_state.model_copy(
                update={'evidence': evidence_state_for(records)}
            ),
        }
    )
    _save_claim(repository, updated_claim, claim.revision)
    return updated_claim


def _checked_external_result(
    repository: PersistenceRepository,
    *,
    result: ExternalTaskResult,
    task: ExternalTaskRecord,
    claim: WorkingClaim,
    receipt_fingerprint: str,
) -> ExternalTaskResult:
    evidence = [
        record
        for evidence_id in result.evidence_ids
        if (
            record := repository.get_evidence(
                claim.claim_id,
                evidence_id,
                claim.customer_id,
            )
        )
        is not None
    ]
    if len(evidence) != len(result.evidence_ids):
        raise _idempotency_error()
    if any(
        record.provenance.get('result_receipt_fingerprint') != receipt_fingerprint
        for record in evidence
    ):
        raise _idempotency_error()
    if result.verification is not ExternalTaskResultVerification.UNVERIFIED:
        return result
    links = repository.list_external_task_evidence_links_internal(claim.claim_id)
    checked = verify_external_task_result(
        result,
        task=task,
        links=links,
        claim=claim,
        evidence=evidence,
        checked_at=now_utc(),
    )
    try:
        repository.save_external_task_result(checked, claim.customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    return checked


def receive_assessor_result(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    adapter: AssessorServiceAdapter,
    claim_id: str,
    task_id: str,
    idempotency_key: str,
    expected_revision: int,
    actor_id: str,
) -> tuple[ExternalTaskResult, bool]:
    """Receive, persist, and verify one result from the controlled assessor path.

    The result is obtained through the installed adapter rather than invented from the
    routing acknowledgement. Its report is persisted as the material the accepted task
    already owes, then checked through the authoritative result-verification function.
    The only Claim mutation binds the Evidence lifecycle to a new revision; report
    content never changes a Claim fact, workflow state, or coverage decision.

    Args:
        repository: Authoritative Claim, task, Evidence, and result persistence boundary.
        storage: Configured object store for the returned report bytes.
        adapter: Assessor adapter that supplies the provider-neutral returned report.
        claim_id: Claim whose accepted external task is returning a result.
        task_id: Immutable external-task identity for the receive operation.
        idempotency_key: Required client identity for unchanged receipt retries.
        expected_revision: Working Claim revision the first receipt expects to update.
        actor_id: Authenticated integration-service identity that scopes the retry key.

    Returns:
        The checked result and whether an earlier receive operation was replayed.

    Raises:
        ApiError: The Claim/task state is invalid, provenance conflicts, storage is
            unavailable, or persistence cannot preserve idempotency and traceability.
    """

    key = require_idempotency_key(idempotency_key)
    receipt_fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'task_id': task_id,
            'idempotency_key': key,
            'expected_revision': expected_revision,
            'actor_id': actor_id,
        }
    )
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()
    task = _find_external_task(repository, claim_id=claim_id, task_id=task_id)
    if task is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The external task was not found.',
        )
    if (
        task.status is not ExternalTaskOperationStatus.ACCEPTED
        or task.service_identity != ASSESSOR_SERVICE_IDENTITY
        or task.provider_reference is None
    ):
        raise _authorisation_error(
            'An assessor result requires an accepted task with provider acknowledgement.'
        )
    if (
        claim.assessor_routing is None
        or claim.assessor_routing.routing_status is not AssessorRoutingStatus.ASSIGNED
        or claim.assessor_routing.assessor_reference != task.provider_reference
    ):
        raise _authorisation_error(
            'An assessor result requires the matching assigned assessor record.'
        )

    existing = next(
        (
            result
            for result in repository.list_external_task_results_internal(claim_id)
            if result.task_id == task_id
        ),
        None,
    )
    if existing is not None:
        checked = _checked_external_result(
            repository,
            result=existing,
            task=task,
            claim=claim,
            receipt_fingerprint=receipt_fingerprint,
        )
        return checked, True

    evidence_id = f'evd_{task.task_id.removeprefix("tsk_")}'
    partial_evidence = repository.get_evidence(claim_id, evidence_id, claim.customer_id)
    has_partial_receipt = (
        partial_evidence is not None
        and partial_evidence.status is EvidenceStatus.RECEIVED
        and partial_evidence.file_status is EvidenceFileStatus.READY
    )
    if (
        has_partial_receipt
        and partial_evidence is not None
        and partial_evidence.provenance.get('result_receipt_fingerprint') != receipt_fingerprint
    ):
        raise _idempotency_error()
    resumes_partial_receipt = has_partial_receipt
    if claim.revision != expected_revision and not resumes_partial_receipt:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed before the assessment result was received.',
            retryable=True,
            current_revision=claim.revision,
        )

    fingerprint = request_fingerprint(
        {
            'task_id': task.task_id,
            'claim_id': task.claim_id,
            'provider_reference': task.provider_reference,
            'accepted_at': task.updated_at.isoformat(),
            'result_receipt_fingerprint': receipt_fingerprint,
        }
    )
    try:
        outcome = adapter.receive_result(
            AssessorResultRequest(
                task_id=task.task_id,
                claim_id=task.claim_id,
                provider_reference=task.provider_reference,
                accepted_at=task.updated_at,
            ),
            fingerprint,
        )
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict
    except (AssessorAdapterFailure, ValueError) as failure:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessment service returned an unusable result.',
            retryable=False,
        ) from failure
    report = outcome.report
    bounded_text = (
        (report.summary, 500),
        (report.source_system, 100),
        (report.source_reference, 200),
        (report.original_filename, 255),
        (report.media_type, 200),
    )
    if (
        any(not value.strip() or len(value) > maximum for value, maximum in bounded_text)
        or not isinstance(report.content, bytes)
        or not report.content
    ):
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessment service returned an unusable result.',
            retryable=False,
        )
    try:
        source_time_is_valid = (
            report.source_timestamp.tzinfo is not None
            and report.source_timestamp.utcoffset() is not None
            and report.source_timestamp >= task.updated_at
        )
    except (AttributeError, TypeError):
        source_time_is_valid = False
    if (
        adapter.integration_source is not task.integration_source
        or task.integration_source is not IntegrationSource.FIXTURE
        or not report.simulation_only
        or not source_time_is_valid
    ):
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessment result provenance does not match the accepted task.',
            retryable=False,
        )
    source = RetrievalSource(
        system=report.source_system,
        reference=report.source_reference,
        retrieved_at=report.source_timestamp,
    )

    _record_awaited_material(repository, task=task, claim=claim)
    awaited = repository.get_evidence(claim_id, evidence_id, claim.customer_id)
    if awaited is None:
        raise _idempotency_error()
    try:
        linked_task_id = external_task_for_evidence(
            awaited,
            repository.list_external_task_evidence_links_internal(claim_id),
        )
    except UntraceableExternalEvidenceError as conflict:
        raise _idempotency_error() from conflict
    if linked_task_id != task.task_id:
        raise _idempotency_error()
    try:
        stored = storage.store_generated_content(
            claim_id=claim_id,
            evidence_id=evidence_id,
            content=report.content,
            media_type=report.media_type,
        )
    except EvidenceStorageUnavailable as error:
        raise ApiError(
            status_code=503,
            code='DEPENDENCY_UNAVAILABLE',
            message='Evidence storage is temporarily unavailable. The result was not recorded.',
            retryable=True,
        ) from error
    except EvidenceUploadTooLarge as error:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessment service returned a report larger than the storage limit.',
            retryable=False,
        ) from error
    except EvidenceContentConflict as conflict:
        raise _idempotency_error() from conflict

    ready = awaited.file_status is EvidenceFileStatus.READY
    if ready:
        expected_provenance = {
            'storage_key': stored.storage_key,
            'upload_checksum': stored.checksum,
            'source_system': report.source_system,
            'source_reference': report.source_reference,
            'source_timestamp': report.source_timestamp.isoformat(),
            'simulation_only': report.simulation_only,
            'result_receipt_fingerprint': receipt_fingerprint,
        }
        if (
            awaited.status is not EvidenceStatus.RECEIVED
            or awaited.original_filename != report.original_filename
            or awaited.media_type != report.media_type
            or awaited.size_bytes != len(report.content)
            or any(
                awaited.provenance.get(key) != value for key, value in expected_provenance.items()
            )
        ):
            raise _idempotency_error()
        arrived = awaited
    else:
        if (
            awaited.status is not EvidenceStatus.PENDING
            or awaited.file_status is not EvidenceFileStatus.NOT_AVAILABLE
            or awaited.source is not EvidenceSource.EXTERNAL_SYSTEM
        ):
            raise _authorisation_error(
                'The assessment result cannot replace the current Evidence state.'
            )
        received_at = max(now_utc(), report.source_timestamp, awaited.updated_at)
        arrived = awaited.model_copy(
            update={
                'status': EvidenceStatus.RECEIVED,
                'file_status': EvidenceFileStatus.READY,
                'original_filename': report.original_filename,
                'media_type': report.media_type,
                'size_bytes': len(report.content),
                'provenance': {
                    **awaited.provenance,
                    'storage_key': stored.storage_key,
                    'upload_checksum': stored.checksum,
                    'source_system': report.source_system,
                    'source_reference': report.source_reference,
                    'source_timestamp': report.source_timestamp.isoformat(),
                    'simulation_only': report.simulation_only,
                    'result_receipt_fingerprint': receipt_fingerprint,
                },
                'wait_type': None,
                'responsible_party': None,
                'expected_by': None,
                'expected_timing': None,
                'context_summary': (
                    'A controlled simulation-only assessment report was returned and requires '
                    'Northwind review.'
                ),
                'updated_at': received_at,
            }
        )
        try:
            repository.save_evidence(arrived, claim.customer_id)
        except KeyError as conflict:
            raise _idempotency_error() from conflict

    evidence_records = repository.list_evidence(claim.claim_id, claim.customer_id)
    if claim.evidence_summary != evidence_summary_for(
        evidence_records
    ) or claim.claim_state.evidence != evidence_state_for(evidence_records):
        claim = _bind_returned_evidence_to_claim(
            repository,
            claim=claim,
            evidence=arrived,
        )
    received_at = arrived.updated_at
    unverified = ExternalTaskResult(
        result_id=_external_result_id(task.task_id),
        task_id=task.task_id,
        claim_id=claim.claim_id,
        source=source,
        summary=report.summary,
        evidence_ids=[arrived.evidence_id],
        received_at=received_at,
    )
    try:
        repository.save_external_task_result(unverified, claim.customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    checked = _checked_external_result(
        repository,
        result=unverified,
        task=task,
        claim=claim,
        receipt_fingerprint=receipt_fingerprint,
    )
    return checked, outcome.replayed


def _record_external_failure(
    repository: PersistenceRepository,
    *,
    task: ExternalTaskRecord,
    customer_id: str,
    failure_code: ExternalTaskFailureCode,
    delivery: ExternalTaskDelivery,
    delivery_evidence: str | None,
) -> ExternalTaskRecord:
    """Record on the task what the attempt actually came to.

    Until this ran, a failed attempt left the task at `prepared`, which asserts
    that the request had not been sent. The failure was recorded on the routing
    operation and not on the task, so nothing reading the task could tell a
    finished failure from a request still in flight, and the delivery, failure,
    and recovery vocabulary the task carries was never populated at runtime.

    The recovery matrix decides what the failure means; this records it. Delivery
    is what the adapter observed, not what the failure code suggests: whether the
    request reached the provider is what separates a retryable failure from an
    unknown outcome, and only the adapter is in a position to know it. #612 carries
    that requirement from the #425 review in as many words — Runtime must not infer
    submission from a generic timeout code.

    A task that has already been recorded as submitted keeps that delivery and its
    original evidence. `assert_task_transition_is_permitted` refuses both lowering
    delivery and rewriting the evidence, and it is right to: what reached the
    provider happened once, and a later attempt describes what happened next rather
    than replacing the account of the first.

    Args:
        repository: Persistence boundary for the claim.
        task: External task state as it stands before the failure.
        customer_id: Customer who owns the parent claim.
        failure_code: Provider-neutral reason the attempt failed.
        delivery: Whether the adapter observed this attempt reaching the provider.
        delivery_evidence: What the adapter saw reach the provider, when it did.

    Returns:
        The task as recorded, carrying the status the recovery matrix settled.

    Raises:
        ApiError: The write conflicts with a concurrent change to the task.
    """
    if task.delivery is ExternalTaskDelivery.SUBMITTED:
        delivery = ExternalTaskDelivery.SUBMITTED
        delivery_evidence = task.delivery_evidence
    classification = classify_external_task_failure(
        failure_code=failure_code,
        delivery=delivery,
    )
    updated_at = now_utc()
    # The same coarse-clock case the acceptance write handles: preparation and
    # failure can land in one tick, and a changed task state must advance time.
    if updated_at <= task.updated_at:
        updated_at = task.updated_at + timedelta(microseconds=1)
    failed = task.model_copy(
        update={
            'status': classification.operation_status,
            'delivery': delivery,
            'delivery_evidence': delivery_evidence,
            'failure_code': failure_code,
            'updated_at': updated_at,
        }
    )
    assert_task_transition_is_permitted(task, failed)
    try:
        repository.save_external_task(failed, customer_id)
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    return failed


def unreconciled_assessor_task(
    repository: PersistenceRepository,
    claim_id: str,
) -> ExternalTaskRecord | None:
    """Find an assessor task on this claim whose outcome nobody has established yet.

    Read from the claim's tasks rather than from one operation, because an unresolved
    outcome constrains the claim, not the attempt that produced it. A second attempt
    arrives under its own operation identity and would find nothing if it asked only
    about itself.
    """

    return next(
        (
            task
            for task in repository.list_external_tasks_internal(claim_id)
            if task.service_identity == ASSESSOR_SERVICE_IDENTITY
            and task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
        ),
        None,
    )


def _dispatch_in_progress_error() -> ApiError:
    """Refuse a caller that did not win the right to send this request.

    Two things reach this. One is a genuine race, where another caller holds the
    reservation and will settle it in a moment. The other is a dispatch that was
    reserved and never settled, which is the case `docs/claim-creation-boundary.md`
    refuses to let fall back to a sendable state: nothing established that the provider
    was not reached, so repeating the send could duplicate it. Neither is distinguishable
    from the other here, and neither may dispatch, so both get the same answer.

    Retryable, because the ordinary case clears within one attempt. What it does not
    permit is a second call to the provider now.
    """

    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=(
            'Another attempt to send this assessment request is already in progress. '
            'Its outcome must be established before the request is sent again.'
        ),
        details=[ErrorDetail(field='assessor_service', reason='dispatch_in_progress')],
        retryable=True,
    )


def unreconciled_outcome_error() -> ApiError:
    """Refuse a request that could repeat an external action nobody has accounted for.

    `SPEC/08-acceptance-scenarios.md` MVP-AT-10 requires that the outcome "remains
    `unknown_outcome`; status is checked with the existing identity before any retry,
    and no duplicate external action is created". This is that refusal, and it is not
    retryable: repeating the same call is exactly what it exists to prevent. What
    unblocks it is reconciliation, not time.
    """

    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=(
            'The previous assessment request may already have reached the assessor. '
            'Northwind must establish what happened to it before another request is sent.'
        ),
        details=[
            ErrorDetail(
                field='assessor_service',
                reason=ExternalTaskOperationStatus.UNKNOWN_OUTCOME.value,
            )
        ],
        retryable=False,
    )


def _assessor_failure_error(
    failure_code: AssessorRoutingFailureCode,
    *,
    task: ExternalTaskRecord | None = None,
) -> ApiError:
    # An attempt that may have been submitted is reported as what it is, whatever
    # its failure code says in isolation. Returning the retryable timeout message
    # here would tell the claimant that the same request can safely be sent again,
    # which is the one thing that is not true of an unresolved outcome.
    if task is not None and task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
        return unreconciled_outcome_error()
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
        repository.save_claim(
            claim,
            expected_revision,
            branch_evaluation=build_applied_branch_evaluation(
                claim,
                repository=repository,
                recomputation_reason='integration_result_changed',
            ),
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while the integration request was running.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict


def reconcile_assessor_routing(
    repository: PersistenceRepository,
    adapter: AssessorServiceAdapter,
    claim_id: str,
    task_id: str,
    idempotency_key: str,
    expected_revision: int,
) -> tuple[AssessorRoutingResult, bool]:
    """Settle one persisted unknown assessor request from a provider status check.

    The caller supplies no provider state. Runtime resolves the existing task, request,
    and operation, then asks the installed adapter about that immutable identity. Only a
    confirmed acceptance advances state; an inconclusive check leaves every record at
    `unknown_outcome` and keeps the routing refusal in force.

    Args:
        repository: Authoritative Claim and external-operation persistence boundary.
        adapter: Provider-neutral assessor status-check boundary.
        claim_id: Claim that owns the unresolved external task.
        task_id: Existing task whose outcome is being reconciled.
        idempotency_key: Required HTTP retry key for this state-changing operation.
        expected_revision: Current Claim revision required by the first settlement.

    Returns:
        The accepted routing result and whether an earlier settlement was replayed.

    Raises:
        ApiError: Identity, authority, revision, provider status, or persistence is invalid.
    """

    require_idempotency_key(idempotency_key)
    claim = repository.get_claim_internal(claim_id)
    if claim is None:
        raise _claim_not_found()
    task = _find_external_task(repository, claim_id=claim_id, task_id=task_id)
    if task is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The external task was not found.',
        )
    requests = [
        request
        for request in repository.list_external_task_requests_internal(claim_id)
        if request.task_id == task_id
    ]
    if len(requests) != 1:
        raise _idempotency_error()
    external_request = requests[0]
    # A reserved request that was never recorded as sent is the interruption window:
    # the attempt held the right to dispatch and nothing recorded what came of it. That
    # is precisely what needs reconciling, so it is admitted here rather than refused;
    # refusing it left the claim unable to route and unable to reconcile, which is the
    # blocking finding on #766.
    interrupted_dispatch = (
        external_request.sent_at is None and external_request.dispatch_reserved_at is not None
    )
    if external_request.operation_id is None or not (
        external_request.sent_at is not None or interrupted_dispatch
    ):
        raise _authorisation_error(
            'Assessor reconciliation requires the persisted sent or reserved request identity.'
        )
    operation = repository.get_assessor_routing_operation(external_request.operation_id)
    if operation is None:
        raise _idempotency_error()

    consent = next(
        (
            record
            for record in claim.external_service_consents
            if record.consent_ref == operation.claimant_consent_ref
        ),
        None,
    )
    decision = repository.get_agent_decision_internal(claim_id, operation.authorisation_ref)
    request_matches_operation = (
        external_request.claim_id == operation.claim_id == claim_id
        and external_request.service_identity == task.service_identity
        and external_request.requested_action == operation.requested_action
        and external_request.authorisation.northwind_authority_ref == operation.authorisation_ref
        and external_request.authorisation.claimant_consent_ref == operation.claimant_consent_ref
        and external_request.authorisation.authorised_revision == operation.authorised_revision
    )
    identity_is_valid = (
        request_matches_operation
        and task.service_identity == ASSESSOR_SERVICE_IDENTITY
        # An interrupted dispatch never recorded a delivery, which is the whole of its
        # problem; a settled unknown outcome recorded one.
        and (
            task.delivery is ExternalTaskDelivery.SUBMITTED
            or task.status is ExternalTaskOperationStatus.PREPARED
        )
        and claim.external_claim is not None
        and claim.external_claim.external_claim_id == operation.external_claim_id
        and consent is not None
        and consent.service_identity == task.service_identity
        and consent.requested_action == task.requested_action
        and decision is not None
        and decision.claim_id == claim_id
        and decision.decision_id == operation.authorisation_ref
    )
    if not identity_is_valid:
        raise _authorisation_error(
            'Assessor reconciliation requires matching persisted task, request, authority, '
            'consent, and Claim identity.'
        )

    if (
        task.status is ExternalTaskOperationStatus.ACCEPTED
        and operation.status is AssessorRoutingOperationStatus.ACCEPTED
        and operation.result is not None
    ):
        provider_reference = operation.result.assessor_reference or operation.result.queue_reference
        awaited, link = _awaited_material_records(task=task, claim=claim)
        stored_evidence = repository.get_evidence(
            claim_id,
            awaited.evidence_id,
            claim.customer_id,
        )
        linked = link in repository.list_external_task_evidence_links_internal(claim_id)
        if (
            provider_reference is not None
            and task.provider_reference == provider_reference
            and claim.assessor_routing == operation.result
            and claim.assessor_routing_fingerprint == operation.request_fingerprint
            and stored_evidence == awaited
            and linked
        ):
            return operation.result, True
        raise _idempotency_error()
    # Two shapes are unresolved. One settled into `unknown_outcome` because the adapter
    # reported a delivery it could not account for. The other never settled at all: its
    # dispatch was reserved and the attempt did not return. Both mean the same thing —
    # the provider may have been reached and nobody knows — and both are refused a
    # further routing request, so both must be reconcilable.
    settled_unknown = (
        task.status is ExternalTaskOperationStatus.UNKNOWN_OUTCOME
        and operation.status is AssessorRoutingOperationStatus.UNKNOWN_OUTCOME
    )
    reserved_unsettled = (
        interrupted_dispatch
        and task.status is ExternalTaskOperationStatus.PREPARED
        and operation.status is AssessorRoutingOperationStatus.PREPARED
    )
    if not (settled_unknown or reserved_unsettled) or claim.assessor_routing is not None:
        raise _authorisation_error(
            'Only a matching unresolved assessor task and operation can be reconciled.'
        )
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed before the assessor outcome was reconciled.',
            retryable=True,
            current_revision=claim.revision,
        )
    if adapter.integration_source is not task.integration_source:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessor status source does not match the original request.',
            retryable=False,
        )

    command = AssessorReconciliationRequest(
        task_id=task.task_id,
        request_id=external_request.request_id,
        operation_id=operation.operation_id,
        claim_id=claim_id,
        external_claim_id=operation.external_claim_id,
        authorisation_ref=operation.authorisation_ref,
        claimant_consent_ref=operation.claimant_consent_ref,
        requested_action=operation.requested_action,
        request_fingerprint=operation.request_fingerprint,
    )
    status_fingerprint = request_fingerprint(
        {
            'task_id': command.task_id,
            'request_id': command.request_id,
            'operation_id': command.operation_id,
            'claim_id': command.claim_id,
            'request_fingerprint': command.request_fingerprint,
        }
    )
    try:
        outcome = adapter.reconcile_assessor(command, status_fingerprint)
    except AdapterIdempotencyConflict as conflict:
        raise _idempotency_error() from conflict
    except AssessorAdapterFailure as failure:
        unavailable = failure.code in {
            AssessorRoutingFailureCode.TIMEOUT,
            AssessorRoutingFailureCode.UNAVAILABLE,
        }
        raise ApiError(
            status_code=503 if unavailable else 502,
            code='DEPENDENCY_UNAVAILABLE' if unavailable else 'DEPENDENCY_FAILED',
            message='The assessor status check could not establish the request outcome.',
            retryable=unavailable,
        ) from failure
    except ValueError as failure:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessor status check returned an unusable result.',
            retryable=False,
        ) from failure
    if outcome is None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message=(
                'The assessor has not established the request outcome. The existing request '
                'remains under reconciliation and must not be sent again.'
            ),
            details=[
                ErrorDetail(
                    field='assessor_service',
                    reason=ExternalTaskOperationStatus.UNKNOWN_OUTCOME.value,
                )
            ],
            retryable=True,
        )
    result = outcome.result
    if result.routing_status not in {
        AssessorRoutingStatus.ASSIGNED,
        AssessorRoutingStatus.QUEUED,
    }:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessor status check returned a non-accepted routing state.',
            retryable=False,
        )
    provider_reference = result.assessor_reference or result.queue_reference
    if provider_reference is None:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The assessor status check accepted the request without a reference.',
            retryable=False,
        )

    accepted_task = _accepted_external_task(
        task=task,
        provider_reference=provider_reference,
    )
    accepted_operation = operation.model_copy(
        update={
            'status': AssessorRoutingOperationStatus.ACCEPTED,
            'result': result,
            'failure_code': None,
            'updated_at': max(
                now_utc(),
                accepted_task.updated_at,
                operation.updated_at + timedelta(microseconds=1),
            ),
        }
    )
    updated_claim = _claim_with_assessor_result(
        claim,
        fingerprint=operation.request_fingerprint,
        result=result,
    )
    awaited, link = _awaited_material_records(task=accepted_task, claim=updated_claim)
    # An interrupted dispatch never recorded its send. The status check has just
    # established that the provider did receive it, so the record says so now rather
    # than leaving an accepted task whose request claims it was never sent.
    settled_request = (
        external_request
        if external_request.sent_at is not None
        else external_request.model_copy(update={'sent_at': external_request.dispatch_reserved_at})
    )
    branch_evaluation = build_applied_branch_evaluation(
        updated_claim,
        repository=repository,
        recomputation_reason='integration_result_changed',
    )
    try:
        repository.save_assessor_reconciliation(
            updated_claim,
            expected_revision,
            accepted_task,
            accepted_operation,
            settled_request,
            awaited,
            link,
            branch_evaluation,
            claim.customer_id,
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while the assessor outcome was reconciled.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except (IdempotencyConflict, KeyError) as conflict:
        raise _idempotency_error() from conflict
    return result, outcome.replayed


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

    if claim.terminal_disposition is not None:
        raise ApiError(
            status_code=409,
            code='INVALID_STATE_TRANSITION',
            message='A terminal Claim cannot start Claim creation.',
        )

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
    external_claim_ref = outcome.result.external_claim_id or outcome.result.claim_number
    if created and external_claim_ref is None:
        raise ApiError(
            status_code=502,
            code='DEPENDENCY_FAILED',
            message='The claims service created a Claim without a stable reference.',
            details=[
                ErrorDetail(
                    field='external_claim',
                    reason='A created result requires an external Claim identifier.',
                )
            ],
        )
    resulting_revision = claim.revision + 1
    updated_claim = claim.model_copy(
        update={
            'external_claim': outcome.result,
            'external_claim_source_revision': payload.claim_revision,
            'external_claim_fingerprint': fingerprint,
            'terminal_disposition': (
                ClaimTerminalDisposition(
                    value=TerminalDispositionValue.COMPLETED,
                    reason_code=TerminalDispositionReasonCode.CLAIM_CREATED,
                    source_refs=[decision.decision_id, external_claim_ref],
                    recorded_by=ActorReference(
                        actor_type=ActorType.SYSTEM,
                        actor_id='claims_service_integration',
                    ),
                    recorded_at=timestamp,
                    recorded_revision=resulting_revision,
                )
                if created and external_claim_ref is not None
                else None
            ),
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
                responsible_party=ResponsibleParty.SYSTEM,
                expected_by=outcome.result.expected_by,
            ),
            'revision': resulting_revision,
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
        # A replay reports success only over a task that ended accepted with its owed
        # material resolvable. An interrupted attempt can leave the task advanced but
        # its material half-written, so acceptance and reconciliation are decided
        # separately: a still-prepared task takes the transition, and every accepted
        # task has its owed material reconciled and read back.
        #
        # Anything else is refused rather than skipped. A task that is missing, or that
        # came to a failure, should not sit under an accepted operation: the task is
        # written before the provider is called, and a failed attempt records the
        # failure on the task and the operation together. Skipping reconciliation there
        # would still save the routing and report an accepted request whose task, and
        # whose owed material, do not exist. The task is not rebuilt either: its
        # integration source comes from the entry decision at send time, and rebuilding
        # it now would record today's source as the one the request went through.
        # Nothing a retry can do recreates that record, so the refusal is not offered
        # as retryable.
        if task is None or task.status not in _REPLAYABLE_TASK_STATUSES:
            raise _idempotency_error()
        if task.status is ExternalTaskOperationStatus.PREPARED:
            provider_reference = (
                operation.result.assessor_reference or operation.result.queue_reference
            )
            assert provider_reference is not None
            task = _record_external_acceptance(
                repository,
                task=task,
                customer_id=claim.customer_id,
                provider_reference=provider_reference,
            )
        _record_awaited_material(repository, task=task, claim=claim)
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

    # Everything below this line can reach the provider, so the unresolved outcome is
    # refused here rather than on the operation that produced it. The operation
    # identity is derived from the caller's idempotency key, so a client that simply
    # presents a new key would otherwise build a fresh authority, operation, and task
    # and send the request a second time. What must not be repeated belongs to the
    # claim's external task, which is where this reads it.
    if unreconciled_assessor_task(repository, payload.claim_id) is not None:
        raise unreconciled_outcome_error()

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
        permission_audit_events: tuple[AuditEventEnvelope, ...] = ()
        if authorisation_decision is not None:
            permission_audit_events = (
                AuditEventEnvelope(
                    event_id=(
                        'aud_'
                        + request_fingerprint(
                            {
                                'event_type': AuditEventType.PERMISSION_AUTHORISED.value,
                                'decision_id': decision.decision_id,
                            }
                        )[:24]
                    ),
                    event_type=AuditEventType.PERMISSION_AUTHORISED,
                    outcome=AuditOutcome.SUCCEEDED,
                    subject=AuditSubject(
                        subject_type=AuditSubjectType.CLAIM,
                        subject_id=claim.claim_id,
                        claim_id=claim.claim_id,
                    ),
                    actor=AuditActor(
                        actor_type=ActorType.SYSTEM,
                        actor_id=decision.authority.proposed_by,
                        auth_source=decision.authority.validated_by,
                    ),
                    reason=decision.customer_reason,
                    source_refs=[
                        decision.decision_id,
                        decision.trigger_message_id,
                        consent.consent_ref,
                    ],
                    permission=AuditPermission(
                        required_permission=payload.requested_action,
                        outcome=AuditPermissionOutcome.AUTHORISED,
                    ),
                    consent_ref=consent.consent_ref,
                    consent_state=consent.status.value,
                    visibility=AuditVisibility.AUDIT_ONLY,
                    correlation_id=operation.operation_id,
                    claim_revision=claim.revision,
                    created_at=timestamp,
                ),
            )
        try:
            if authorisation_decision is None:
                repository.save_assessor_routing_operation(operation)
            else:
                repository.save_assessor_routing_preparation(
                    operation,
                    authorisation_decision,
                    claim.customer_id,
                    audit_events=permission_audit_events,
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

    # Nothing below may reach the provider without holding this. The reservation is a
    # persistence compare-and-set rather than a check made here, because two callers
    # racing on the same request would both pass a check and both dispatch. Whoever
    # loses is refused before the adapter is called.
    reserved = repository.reserve_external_dispatch(
        claim.claim_id,
        external_request.request_id,
        claim.customer_id,
        now_utc(),
        operation.operation_id,
    )
    if reserved is None:
        raise _dispatch_in_progress_error()
    external_request = reserved

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
        failed_task = _record_external_failure(
            repository,
            task=task,
            customer_id=claim.customer_id,
            failure_code=ExternalTaskFailureCode(failure.code.value),
            delivery=failure.delivery,
            delivery_evidence=failure.delivery_evidence,
        )
        # The operation takes the status the task was given rather than deciding a
        # second time from the failure code. The two used to be settled by separate
        # rules, which is how the same attempt could be an unknown outcome on the task
        # and a retryable failure on the operation the moment delivery mattered.
        failed_operation = operation.model_copy(
            update={
                'status': _OPERATION_STATUS_BY_TASK_STATUS[failed_task.status],
                'failure_code': failure.code,
                'updated_at': now_utc(),
            }
        )
        repository.save_assessor_routing_operation(failed_operation)
        # An attempt that settled releases its hold: the task status now says what may
        # happen next, and a retryable failure that the matrix permits to be retried
        # must be able to take the reservation again. An unknown outcome keeps it,
        # which is the point of holding it at all — nothing establishes that the
        # provider was not reached, so nothing may send again until reconciliation.
        if failed_task.status is not ExternalTaskOperationStatus.UNKNOWN_OUTCOME:
            repository.release_external_dispatch(
                claim.claim_id,
                external_request.request_id,
                claim.customer_id,
            )
        raise _assessor_failure_error(failure.code, task=failed_task) from failure

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
    accepted_task = _record_external_acceptance(
        repository,
        task=task,
        customer_id=claim.customer_id,
        provider_reference=provider_reference,
    )
    _record_awaited_material(repository, task=accepted_task, claim=claim)
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

    updated_claim = _claim_with_assessor_result(claim, fingerprint=fingerprint, result=result)
    _save_claim(repository, updated_claim, claim.revision)
    return result, replayed


def _claim_with_assessor_result(
    claim: WorkingClaim,
    *,
    fingerprint: str,
    result: AssessorRoutingResult,
) -> WorkingClaim:
    """Build the next Claim revision for one accepted assessor routing result.

    Args:
        claim: Current authoritative Claim State.
        fingerprint: Original assessor request fingerprint.
        result: Provider-neutral accepted routing result.

    Returns:
        The next Claim revision with claimant-safe routing and next-step projection.

    Raises:
        ValueError: The resulting Claim projection violates its schema.
    """

    assigned = result.routing_status is AssessorRoutingStatus.ASSIGNED
    return claim.model_copy(
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
            'updated_at': now_utc(),
        }
    )
