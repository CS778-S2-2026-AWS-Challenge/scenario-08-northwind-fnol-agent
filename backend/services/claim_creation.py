from hashlib import sha256

from backend.adapters.claims_service import ClaimsServiceAdapter
from backend.core.auth import Principal
from backend.core.errors import ApiError, ErrorDetail
from backend.domain.branch_registry import BranchRuleEvaluator
from backend.domain.models import (
    ActorType,
    AgentAction,
    AgentAuthority,
    AgentDecisionRecord,
    AuthorityOutcome,
    ClaimantDecision,
    ClaimCreationResponse,
    CreateExternalClaimRequest,
    EvidenceStatus,
    FormStatus,
    PendingEvidenceReference,
    StateChange,
    WorkflowState,
)
from backend.repositories.protocols import IdempotencyRecord, PersistenceRepository
from backend.services.external_services import claimant_assessor_action
from backend.services.integrations import create_external_claim
from backend.services.support import (
    now_utc,
    parse_if_match,
    request_fingerprint,
    require_idempotency_key,
)


def _invalid_state(message: str, details: list[ErrorDetail] | None = None) -> ApiError:
    return ApiError(
        status_code=409,
        code='INVALID_STATE_TRANSITION',
        message=message,
        details=details or [],
    )


def create_claim_from_confirmed_report(
    repository: PersistenceRepository,
    adapter: ClaimsServiceAdapter,
    principal: Principal,
    claim_id: str,
    idempotency_key: str | None,
    if_match: str | None,
) -> ClaimCreationResponse:
    key = require_idempotency_key(idempotency_key)
    expected_revision = parse_if_match(if_match)
    route = f'/api/v1/claims/{claim_id}/creation'
    fingerprint = request_fingerprint({'claim_id': claim_id, 'revision': expected_revision})
    decision_key = f'{claim_id}:{principal.subject}:{key}'.encode()
    decision_id = f'dec_{sha256(decision_key).hexdigest()[:20]}'
    existing = repository.find_idempotency(principal.subject, route, key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise ApiError(
                status_code=409,
                code='IDEMPOTENCY_CONFLICT',
                message='The idempotency key was reused for a different claim revision.',
            )
        if existing.response_payload is None:
            raise ApiError(
                status_code=500,
                code='INTERNAL_ERROR',
                message='The idempotent claim creation result could not be restored.',
                retryable=True,
            )
        return ClaimCreationResponse.model_validate(existing.response_payload)

    claim = repository.get_claim(claim_id, principal.subject)
    if claim is None:
        raise ApiError(
            status_code=404,
            code='RESOURCE_NOT_FOUND',
            message='The claim was not found.',
        )
    if (
        claim.external_claim is not None
        and claim.external_claim_source_revision == expected_revision
    ):
        recovered_decision = repository.get_agent_decision(
            claim_id,
            decision_id,
            principal.subject,
        )
        if (
            recovered_decision is not None
            and recovered_decision.action is AgentAction.CREATE_CLAIM
            and recovered_decision.authority.outcome is AuthorityOutcome.AUTHORISED
        ):
            response = ClaimCreationResponse(
                claim_id=claim_id,
                revision=claim.revision,
                decision=ClaimantDecision(
                    decision_id=recovered_decision.decision_id,
                    action=recovered_decision.action,
                    reason_codes=recovered_decision.reason_codes,
                    customer_reason=recovered_decision.customer_reason,
                    customer_next_step=claim.customer_next_step,
                ),
                external_claim=claim.external_claim,
                external_service_action=claimant_assessor_action(repository, claim),
                customer_next_step=claim.customer_next_step,
            )
            repository.save_idempotency(
                IdempotencyRecord(
                    actor_id=principal.subject,
                    route=route,
                    key=key,
                    request_fingerprint=fingerprint,
                    claim_id=claim_id,
                    session_id=claim.active_session_id or '',
                    decision_id=recovered_decision.decision_id,
                    response_payload=response.model_dump(mode='json'),
                )
            )
            return response
    if claim.revision != expected_revision:
        raise ApiError(
            status_code=409,
            code='REVISION_CONFLICT',
            message='The claim changed after this page was loaded.',
            retryable=True,
            current_revision=claim.revision,
        )
    if claim.external_claim is not None:
        raise _invalid_state('This working claim has already been created in the claims service.')
    if claim.incident_type not in {'motor', 'home', 'contents'}:
        raise _invalid_state('A supported claim family must be confirmed before claim creation.')
    if claim.claim_state.workflow_state is WorkflowState.PROFESSIONAL_REVIEW:
        raise _invalid_state('This report is not ready for controlled claim creation.')

    requirements = (
        BranchRuleEvaluator()
        .evaluate(
            claim,
            current_action=AgentAction.CREATE_CLAIM,
            recomputation_reason='claim_creation_validation',
        )
        .requirements
    )
    missing_or_unconfirmed = requirements.missing_required_now
    if missing_or_unconfirmed:
        raise _invalid_state(
            'Required claim facts must be confirmed before claim creation.',
            [
                ErrorDetail(field=field_code, reason='Confirm this field before claim creation.')
                for field_code in missing_or_unconfirmed
            ],
        )
    open_handoffs = [
        handoff
        for handoff in repository.list_handoffs(claim_id, principal.subject)
        if handoff.status.value not in {'resolved', 'cancelled'}
    ]
    if open_handoffs:
        raise _invalid_state('Resolve the open human handoff before claim creation.')

    session_id = claim.active_session_id
    if session_id is None:
        raise _invalid_state('An active claim session is required for claim creation.')
    claimant_messages = [
        message
        for message in repository.list_messages(claim_id, session_id, principal.subject)
        if message.actor is ActorType.CLAIMANT
    ]
    if not claimant_messages:
        raise _invalid_state('A claimant message is required before claim creation.')

    timestamp = now_utc()
    decision = AgentDecisionRecord(
        decision_id=decision_id,
        claim_id=claim_id,
        session_id=session_id,
        trigger_message_id=claimant_messages[-1].message_id,
        action=AgentAction.CREATE_CLAIM,
        reason_codes=['CLAIM_CREATION_AUTHORISED'],
        customer_reason=(
            'The registered current-action requirements are satisfied and no open handoff '
            'blocks creation.'
        ),
        customer_response=(
            'Your confirmed report is being created through the configured claims service.'
        ),
        state_changes=[StateChange(path='claim_state.next_action', to='CREATE_CLAIM')],
        proposed_signals=[],
        required_tools=[{'tool': 'claims_service', 'operation': 'create_claim'}],
        next_action_requirements=[],
        customer_next_step=claim.customer_next_step,
        authority=AgentAuthority(
            proposed_by='controlled_claim_creation_rule',
            validated_by='deterministic_rule_engine',
            outcome=AuthorityOutcome.AUTHORISED,
        ),
        form_changes={},
        resulting_revision=claim.revision,
        created_at=timestamp,
    )
    repository.save_agent_decision(decision, principal.subject)

    evidence = repository.list_evidence(claim_id, principal.subject)
    confirmed_form = {
        field_code: field
        for field_code, field in claim.form.items()
        if field.status is FormStatus.CONFIRMED
    }
    result, _replayed = create_external_claim(
        repository,
        adapter,
        CreateExternalClaimRequest(
            working_claim_id=claim_id,
            claim_revision=claim.revision,
            authorised_decision_id=decision.decision_id,
            confirmed_form=confirmed_form,
            evidence_refs=[item.evidence_id for item in evidence],
            pending_evidence=[
                PendingEvidenceReference(
                    evidence_id=item.evidence_id,
                    kind=item.kind,
                    needed_for=item.needed_for,
                )
                for item in evidence
                if item.status is EvidenceStatus.PENDING
            ],
            route=f'standard_{claim.incident_type}_intake',
        ),
    )
    updated = repository.get_claim(claim_id, principal.subject)
    if updated is None:
        raise ApiError(
            status_code=500,
            code='INTERNAL_ERROR',
            message='The created claim could not be restored.',
            retryable=True,
        )
    claimant_decision = ClaimantDecision(
        decision_id=decision.decision_id,
        action=decision.action,
        reason_codes=decision.reason_codes,
        customer_reason=decision.customer_reason,
        customer_next_step=updated.customer_next_step,
    )
    response = ClaimCreationResponse(
        claim_id=claim_id,
        revision=updated.revision,
        decision=claimant_decision,
        external_claim=result,
        external_service_action=claimant_assessor_action(repository, updated),
        customer_next_step=updated.customer_next_step,
    )
    repository.save_idempotency(
        IdempotencyRecord(
            actor_id=principal.subject,
            route=route,
            key=key,
            request_fingerprint=fingerprint,
            claim_id=claim_id,
            session_id=session_id,
            decision_id=decision.decision_id,
            response_payload=response.model_dump(mode='json'),
        )
    )
    return response
