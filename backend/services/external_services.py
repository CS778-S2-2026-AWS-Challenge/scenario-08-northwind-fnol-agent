from hashlib import sha256
from typing import Any, NoReturn

from backend.adapters.claims_service import AssessorServiceAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.external_services import (
    ASSESSOR_CONSENT_FIELDS,
    ASSESSOR_REQUESTED_ACTION,
    ASSESSOR_SERVICE_IDENTITY,
    ASSESSOR_SHARED_DATA_SUMMARY,
    ExternalTaskContinuation,
    ExternalTaskContinuationOutcome,
    ExternalTaskRecord,
    continuation_for_failed_task,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AssessorRoutingFailureCode,
    AssessorRoutingOperationStatus,
    AssessorRoutingStatus,
    AuthorityOutcome,
    ClaimantExternalServiceAction,
    ClaimantExternalServiceResponse,
    ClaimantExternalServiceStatus,
    ClaimCreationStatus,
    CustomerNextStep,
    ExternalServiceConsent,
    ExternalServiceConsentStatus,
    FormStatus,
    GrantAssessorConsentRequest,
    ResponsibleParty,
    RouteAssessorRequest,
    WorkflowState,
    WorkingClaim,
)
from backend.repositories.protocols import (
    IdempotencyConflict,
    IdempotencyRecord,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.branching import build_applied_branch_evaluation
from backend.services.external_service_entry import ExternalServiceEntryDecision
from backend.services.integrations import (
    assessor_operation_id,
    route_assessor,
    unreconciled_assessor_task,
    unreconciled_outcome_error,
)
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)

_ACTION_SERVICE_NAME = 'Vehicle damage assessment'
_ACTION_PROVIDER = 'Controlled assessment fixture'
_ACTION_PURPOSE = (
    'Request an assessor for the vehicle damage recorded in this claim. '
    'This does not decide coverage or approve repairs.'
)
_ELIGIBLE_NEXT_STEPS = {'claim_created', 'assessor_request_ready'}


def _audit_event_id(kind: str, identity: str) -> str:
    seed = f'{kind}:{identity}'.encode()
    return f'aud_{sha256(seed).hexdigest()[:24]}'


def _not_found() -> ApiError:
    return ApiError(
        status_code=404,
        code='RESOURCE_NOT_FOUND',
        message='The claim was not found.',
    )


def _invalid_state(message: str) -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=message,
    )


def _idempotency_conflict() -> ApiError:
    return ApiError(
        status_code=409,
        code='IDEMPOTENCY_CONFLICT',
        message='The idempotency key was reused for a different assessment request.',
    )


def _active_assessor_consent(claim: WorkingClaim) -> ExternalServiceConsent | None:
    return next(
        (
            consent
            for consent in reversed(claim.external_service_consents)
            if consent.service_identity == ASSESSOR_SERVICE_IDENTITY
            and consent.requested_action == ASSESSOR_REQUESTED_ACTION
            and consent.status is ExternalServiceConsentStatus.GRANTED
            and ASSESSOR_CONSENT_FIELDS.issubset(consent.permitted_fields)
        ),
        None,
    )


def _has_open_handoff(repository: PersistenceRepository, claim: WorkingClaim) -> bool:
    return any(
        handoff.status.value not in {'resolved', 'cancelled'}
        for handoff in repository.list_handoffs(claim.claim_id, claim.customer_id)
    )


# The provider-neutral failure vocabulary is wider than the claimant one:
# `ExternalTaskFailureCode` also carries `conflicting`, which the recovery matrix
# settles as a terminal failure, and `partial`, which it settles as an unresolved
# outcome. AT-10 approves claimant wording for these four only, so a task carrying
# any other code keeps the ordinary safe action rather than being shown with
# invented wording or crashing the projection on an enum it cannot express.
_CLAIMANT_FAILURE_CODES = frozenset(code.value for code in AssessorRoutingFailureCode)

# What a failed task means for whoever is waiting on it is decided once, by
# `continuation_for_failed_task`, from the recovery the matrix settled. This maps
# that answer onto the claimant vocabulary rather than deriving it a second time
# from the operation status, which would be the same rule written twice and free
# to drift.
#
# `AWAITING_RECONCILIATION` used to have no entry, on the ground that an unresolved
# outcome had no approved claimant wording. Leaving it out is not the neutral choice
# it reads as: a failed attempt writes nothing to the claim, so with no routing
# recorded the projection falls back to `READY_TO_REQUEST` with `can_request` true,
# and the claimant is invited to send again a request that may already be with the
# assessor. Saying nothing is the one answer this state cannot afford.
_CLAIMANT_CONTINUATION_STATUS = {
    ExternalTaskContinuation.RETRY_PERMITTED_BY_THE_FAILURE: (
        ClaimantExternalServiceStatus.RETRYABLE_FAILURE
    ),
    ExternalTaskContinuation.AWAITING_REVIEW: (ClaimantExternalServiceStatus.TERMINAL_FAILURE),
    ExternalTaskContinuation.AWAITING_RECONCILIATION: (
        ClaimantExternalServiceStatus.AWAITING_RECONCILIATION
    ),
}


def _latest_failed_assessor_task(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ExternalTaskRecord | None:
    """Find the most recent assessor task that ended in a failure the claimant may see.

    AT-10 requires the claimant to receive an honest state and next step. The
    failure is read from the task rather than stored on the claim, because that
    scenario's `claim_state_effects.failure_may_change` is empty: a failed attempt
    must leave the claim exactly as it was. Deriving the state here honours both,
    the claim is untouched and the claimant is still told what happened.

    A failure whose code has no approved claimant wording is still not mapped. AT-10
    approves wording for four codes only, and inventing a claimant meaning for the
    others is the kind of claim this boundary exists to prevent. An `unknown_outcome`
    task carrying one of those four codes is now mapped, because the alternative is
    not silence but a fallback to "ready to request".

    Args:
        repository: Persistence boundary for the claim.
        claim: Working Claim whose assessor action is being projected.

    Returns:
        The latest failed assessor task, or None when no attempt has failed.
    """
    failed = [
        task
        for task in repository.list_external_tasks_internal(claim.claim_id)
        if task.service_identity == ASSESSOR_SERVICE_IDENTITY
        and task.failure_code is not None
        and task.failure_code.value in _CLAIMANT_FAILURE_CODES
        and continuation_for_failed_task(task).continuation in _CLAIMANT_CONTINUATION_STATUS
    ]
    if not failed:
        return None
    return max(failed, key=lambda task: (task.updated_at, task.task_id))


def claimant_assessor_action(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimantExternalServiceAction | None:
    routing = claim.assessor_routing
    failed_task = None
    continuation: ExternalTaskContinuationOutcome | None = None
    if routing is None:
        failed_task = _latest_failed_assessor_task(repository, claim)
        created_claim = claim.external_claim
        eligible = (
            claim.incident_type == 'motor'
            and claim.claim_state.workflow_state is WorkflowState.CREATED
            and created_claim is not None
            and created_claim.creation_status is ClaimCreationStatus.CREATED
            and created_claim.external_claim_id is not None
            and created_claim.route == 'standard_motor_intake'
            and claim.customer_next_step.status in _ELIGIBLE_NEXT_STEPS
            and not _has_open_handoff(repository, claim)
        )
        if not eligible:
            return None

    consent = _active_assessor_consent(claim)
    if routing is not None:
        if routing.routing_status is AssessorRoutingStatus.ASSIGNED:
            status = ClaimantExternalServiceStatus.ASSIGNED
        elif routing.routing_status is AssessorRoutingStatus.QUEUED:
            status = ClaimantExternalServiceStatus.QUEUED
        else:
            return None
    elif failed_task is not None:
        continuation = continuation_for_failed_task(failed_task)
        status = _CLAIMANT_CONTINUATION_STATUS[continuation.continuation]
    elif consent is not None:
        status = ClaimantExternalServiceStatus.READY_TO_REQUEST
    else:
        status = ClaimantExternalServiceStatus.CONSENT_REQUIRED

    return ClaimantExternalServiceAction(
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        service_name=_ACTION_SERVICE_NAME,
        provider=_ACTION_PROVIDER,
        purpose=_ACTION_PURPOSE,
        shared_data_summary=list(ASSESSOR_SHARED_DATA_SUMMARY),
        status=status,
        consent_status=consent.status if consent is not None else None,
        routing=routing,
        failure_code=(
            AssessorRoutingFailureCode(failed_task.failure_code.value)
            if failed_task is not None and failed_task.failure_code is not None
            else None
        ),
        # After a failure the domain has already answered whether the failure
        # itself permits another attempt, so this reads that answer instead of
        # inferring it from the status a moment after deriving that status from the
        # same place. It is not permission to send: the routing endpoint still
        # checks the claim, consent, and revision.
        can_request=(
            continuation.failure_permits_another_attempt
            if continuation is not None
            else status
            in {
                ClaimantExternalServiceStatus.CONSENT_REQUIRED,
                ClaimantExternalServiceStatus.READY_TO_REQUEST,
            }
        ),
    )


# What the claimant is told to do next, for the two external-service states in which
# they are told to do nothing. `customer_next_step` is a stored field written when
# permission is recorded, and a failed attempt deliberately changes no claim field, so
# it keeps saying that Northwind can now send the request. Beside an action that has
# just withdrawn `can_request`, that is not merely stale: the two halves of the same
# response contradict each other, and the half the claimant is likelier to act on is
# the wrong one.
#
# Both sentences restate approved text rather than adding claimant meaning. AT-10
# records the terminal case as "the current claim is preserved and Northwind must
# review the request before another attempt", which `docs/api.md` repeats, and the
# unresolved case keeps the wording delivered with #759.
_WITHDRAWN_ACTION_NEXT_STEPS = {
    ClaimantExternalServiceStatus.TERMINAL_FAILURE: (
        'assessor_request_under_review',
        'Your claim is saved. Northwind must review the assessment request before another '
        'attempt, so there is nothing for you to do now.',
    ),
    ClaimantExternalServiceStatus.AWAITING_RECONCILIATION: (
        'assessor_request_being_checked',
        'Your claim is saved. Northwind is checking with the assessor whether the request '
        'arrived, so there is nothing for you to do now.',
    ),
}


def claimant_next_step(
    claim: WorkingClaim,
    action: ClaimantExternalServiceAction | None,
) -> CustomerNextStep:
    """Say what the claimant does next, without contradicting the action beside it.

    A retryable failure is left alone: the stored next step already says Northwind can
    send the request, and `can_request` agrees. Only the states that withdraw the action
    are corrected, and the correction is derived here rather than written to the claim,
    so AT-10's empty `claim_state_effects.failure_may_change` still holds.

    Args:
        claim: Working Claim whose stored next step is being projected.
        action: The claimant external-service action derived for the same read.

    Returns:
        The stored next step, or the derived one for a withdrawn action.
    """

    if action is None:
        return claim.customer_next_step
    replacement = _WITHDRAWN_ACTION_NEXT_STEPS.get(action.status)
    if replacement is None:
        return claim.customer_next_step
    status, summary = replacement
    return claim.customer_next_step.model_copy(
        update={
            'status': status,
            'summary': summary,
            'responsible_party': ResponsibleParty.CLAIMS_PROFESSIONAL,
            'expected_by': None,
            'required_items': [],
        }
    )


def _response(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> ClaimantExternalServiceResponse:
    action = claimant_assessor_action(repository, claim)
    if action is None:
        raise _invalid_state('A vehicle damage assessment is not a relevant next step.')
    return ClaimantExternalServiceResponse(
        claim_id=claim.claim_id,
        revision=claim.revision,
        action=action,
        customer_next_step=claimant_next_step(claim, action),
    )


def _save_idempotency(
    repository: PersistenceRepository,
    *,
    actor_id: str,
    route: str,
    key: str,
    fingerprint: str,
    claim: WorkingClaim,
    response: ClaimantExternalServiceResponse,
    decision_id: str | None = None,
) -> None:
    try:
        repository.save_idempotency(
            IdempotencyRecord(
                actor_id=actor_id,
                route=route,
                key=key,
                request_fingerprint=fingerprint,
                claim_id=claim.claim_id,
                session_id=claim.active_session_id or '',
                decision_id=decision_id,
                response_payload=response.model_dump(mode='json'),
            )
        )
    except IdempotencyConflict as conflict:
        raise _idempotency_conflict() from conflict


def grant_assessor_consent(
    repository: PersistenceRepository,
    principal: Principal,
    claim_id: str,
    payload: GrantAssessorConsentRequest,
    idempotency_key: str | None,
    if_match: str | None,
) -> tuple[ClaimantExternalServiceResponse, bool]:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/assessor-routing/consent'
    fingerprint = request_fingerprint(
        {
            'claim_id': claim_id,
            'revision': expected_revision,
            **payload.model_dump(mode='json'),
        }
    )
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise _idempotency_conflict()
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The saved permission response could not be restored.',
                retryable=True,
            )
        return ClaimantExternalServiceResponse.model_validate(existing.response_payload), True

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found()
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    action = claimant_assessor_action(repository, claim)
    if action is None or not action.can_request:
        raise _invalid_state('A vehicle damage assessment is not available for this claim.')

    active_consent = _active_assessor_consent(claim)
    if active_consent is not None:
        response = _response(repository, claim)
        _save_idempotency(
            repository,
            actor_id=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            claim=claim,
            response=response,
        )
        return response, True

    consent_seed = f'{claim_id}:{principal.subject}:{key}'.encode()
    consent = ExternalServiceConsent(
        consent_ref=f'cns_{sha256(consent_seed).hexdigest()[:20]}',
        service_identity=ASSESSOR_SERVICE_IDENTITY,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        permitted_fields=sorted(ASSESSOR_CONSENT_FIELDS),
        status=ExternalServiceConsentStatus.GRANTED,
        granted_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id=principal.subject),
        granted_at=now_utc(),
    )
    updated = claim.model_copy(
        update={
            'external_service_consents': [*claim.external_service_consents, consent],
            'customer_next_step': CustomerNextStep(
                status='assessor_request_ready',
                summary=(
                    'Your permission is recorded. Northwind can now send the vehicle '
                    'assessment request.'
                ),
                responsible_party=ResponsibleParty.CLAIMANT,
            ),
            'revision': claim.revision + 1,
            'updated_at': now_utc(),
        }
    )
    response = _response(repository, updated)
    idempotency = IdempotencyRecord(
        actor_id=principal.subject,
        route=route,
        key=key,
        request_fingerprint=fingerprint,
        claim_id=updated.claim_id,
        session_id=updated.active_session_id or '',
        response_payload=response.model_dump(mode='json'),
    )
    audit_event = AuditEventEnvelope(
        event_id=_audit_event_id('consent-granted', consent.consent_ref),
        event_type=AuditEventType.CONSENT_GRANTED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=updated.claim_id,
            claim_id=updated.claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.CLAIMANT,
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason='Claimant granted task-specific consent for vehicle damage assessment routing.',
        source_refs=[consent.consent_ref],
        consent_ref=consent.consent_ref,
        consent_state=consent.status.value,
        visibility=AuditVisibility.AUDIT_ONLY,
        idempotency_key=key,
        claim_revision=updated.revision,
        created_at=consent.granted_at,
    )
    branch_evaluation = build_applied_branch_evaluation(
        updated,
        repository=repository,
        recomputation_reason='external_consent_granted',
        trigger_source_refs=[consent.consent_ref],
    )
    try:
        repository.save_claim_mutation_with_audit(
            updated,
            expected_revision=claim.revision,
            idempotency=idempotency,
            audit_events=(audit_event,),
            branch_evaluation=branch_evaluation,
        )
    except RevisionConflict as conflict:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed while permission was being recorded.',
            retryable=True,
            current_revision=conflict.current_revision,
        ) from conflict
    except IdempotencyConflict as conflict:
        raise _idempotency_conflict() from conflict
    return response, False


def _confirmed_region(claim: WorkingClaim) -> str:
    field = claim.form.get('incident.location')
    if field is None or field.status is not FormStatus.CONFIRMED:
        raise _invalid_state('Confirm the incident location before requesting an assessor.')
    value: Any = field.value
    if isinstance(value, str) and value.strip():
        return value.strip()[:100]
    if isinstance(value, dict):
        for key in ('region', 'city', 'suburb', 'description'):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate.strip()[:100]
    raise _invalid_state('The confirmed incident location does not include a routable region.')


def _assessor_route_request(
    claim: WorkingClaim,
    consent: ExternalServiceConsent,
    decision_id: str,
) -> RouteAssessorRequest:
    if claim.external_claim is None or claim.external_claim.external_claim_id is None:
        raise _invalid_state('Create the external claim before requesting an assessor.')
    return RouteAssessorRequest(
        claim_id=claim.claim_id,
        external_claim_id=claim.external_claim.external_claim_id,
        authorisation_ref=decision_id,
        claimant_consent_ref=consent.consent_ref,
        requested_action=ASSESSOR_REQUESTED_ACTION,
        location={'region': _confirmed_region(claim)},
    )


def _raise_revision_conflict(claim: WorkingClaim) -> NoReturn:
    raise ApiError(
        status_code=409,
        code='REVISION_CONFLICT',
        message='The claim changed after this page was loaded.',
        retryable=True,
        current_revision=claim.revision,
    )


def request_assessor_routing(
    repository: PersistenceRepository,
    adapter: AssessorServiceAdapter,
    entry_decision: ExternalServiceEntryDecision,
    principal: Principal,
    claim_id: str,
    idempotency_key: str | None,
    if_match: str | None,
) -> tuple[ClaimantExternalServiceResponse, bool]:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/assessor-routing'
    fingerprint = request_fingerprint({'claim_id': claim_id, 'revision': expected_revision})
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise _idempotency_conflict()
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The saved assessment response could not be restored.',
                retryable=True,
            )
        return ClaimantExternalServiceResponse.model_validate(existing.response_payload), True

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise _not_found()
    # The Northwind authority for this routing is one decision about one claim under one
    # permission, so it is derived from those and not from the caller's idempotency key.
    #
    # Derived from the key, a retry that presented a new key minted a new decision, and
    # with it a new operation identity, a new task, and a second provider call: three
    # timeouts on one claim left three tasks and three operations. `docs/api.md` and
    # #612 both require the opposite — a permitted retry keeps the original task,
    # request fingerprint, and operation identity — and the claimant client already
    # holds one key per claim for exactly that reason. Deriving it here makes the
    # server enforce what the contract states rather than depend on the client for it.
    #
    # A retry that changed the request is still refused: the operation holds the first
    # attempt's fingerprint, and `route_assessor` compares it before anything else.
    active_consent = _active_assessor_consent(claim)
    decision_seed = (
        f'{claim_id}:{principal.subject}:'
        f'{active_consent.consent_ref if active_consent is not None else key}:'
        f'{ASSESSOR_REQUESTED_ACTION}'
    ).encode()
    decision_id = f'dec_{sha256(decision_seed).hexdigest()[:20]}'
    if claim.revision != expected_revision:
        consent = _active_assessor_consent(claim)
        decision = repository.get_agent_decision(claim_id, decision_id, principal.subject)
        if consent is None or decision is None:
            _raise_revision_conflict(claim)
        if decision.resulting_revision != expected_revision:
            _raise_revision_conflict(claim)
        route_request = _assessor_route_request(claim, consent, decision_id)
        if claim.assessor_routing is None:
            operation = repository.get_assessor_routing_operation(
                assessor_operation_id(route_request)
            )
            if operation is None or operation.status is not AssessorRoutingOperationStatus.ACCEPTED:
                _raise_revision_conflict(claim)
        route_assessor(
            repository,
            adapter,
            entry_decision,
            route_request,
        )
        restored = repository.get_claim(claim_id, principal.subject)
        if restored is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The assessment result could not be restored.',
                retryable=True,
            )
        response = _response(repository, restored)
        _save_idempotency(
            repository,
            actor_id=principal.subject,
            route=route,
            key=key,
            fingerprint=fingerprint,
            claim=restored,
            response=response,
            decision_id=decision_id,
        )
        return response, True
    action = claimant_assessor_action(repository, claim)
    consent = _active_assessor_consent(claim)
    # An unresolved outcome also fails the `can_request` gate below, but it would fail
    # it as a missing permission, which is both untrue and the wrong instruction. This
    # is the reason rather than a second rule: it reads the claim's external tasks,
    # which is the same source the gate inside `route_assessor` reads.
    if unreconciled_assessor_task(repository, claim_id) is not None:
        raise unreconciled_outcome_error()
    # `can_request` is the single answer to whether this claimant may send the
    # request now. It admits a retryable failure, which AT-10 permits to be retried
    # with the same unchanged operation, and refuses a terminal one, which that
    # scenario requires Northwind to review first.
    if action is None or not action.can_request or consent is None:
        raise _invalid_state('Record claimant permission before requesting an assessor.')
    if claim.active_session_id is None:
        raise _invalid_state('An active claim session is required for assessor routing.')
    claimant_messages = [
        message
        for message in repository.list_messages(
            claim_id,
            claim.active_session_id,
            principal.subject,
        )
        if message.actor is ActorType.CLAIMANT
    ]
    if not claimant_messages:
        raise _invalid_state('A claimant message is required before assessor routing.')

    timestamp = now_utc()
    decision = AgentDecisionRecord(
        decision_id=decision_id,
        claim_id=claim_id,
        session_id=claim.active_session_id,
        trigger_message_id=claimant_messages[-1].message_id,
        action=AgentAction.PROCEED,
        reason_codes=['ASSESSOR_RULE_AUTHORISED'],
        customer_reason=(
            'The controlled motor claim is created, the location is confirmed, and '
            'task-specific claimant permission is active.'
        ),
        customer_response='Northwind is sending the vehicle assessment request.',
        state_changes=[],
        proposed_signals=[],
        required_tools=[{'tool': 'assessor_service', 'operation': 'route_assessor'}],
        next_action_requirements=[],
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='controlled_assessor_routing_rule',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        form_changes={},
        resulting_revision=claim.revision,
        created_at=timestamp,
    )
    route_assessor(
        repository,
        adapter,
        entry_decision,
        _assessor_route_request(claim, consent, decision.decision_id),
        authorisation_decision=decision,
    )
    updated = repository.get_claim(claim_id, principal.subject)
    if updated is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The assessment result could not be restored.',
            retryable=True,
        )
    response = _response(repository, updated)
    _save_idempotency(
        repository,
        actor_id=principal.subject,
        route=route,
        key=key,
        fingerprint=fingerprint,
        claim=updated,
        response=response,
        decision_id=decision.decision_id,
    )
    return response, False
