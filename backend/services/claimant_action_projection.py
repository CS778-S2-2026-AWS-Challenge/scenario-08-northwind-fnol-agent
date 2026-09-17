"""Build the single claimant primary-action projection from backend state."""

from backend.domain.claimant_action_registry import (
    CLAIMANT_ACTION_REGISTRY_VERSION,
    claimant_action_contract,
)
from backend.domain.models import (
    ClaimantExternalServiceAction,
    ClaimantExternalServiceStatus,
    ClaimantPrimaryAction,
    CustomerNextStep,
)

_EXTERNAL_ACTION_CODES = {
    ClaimantExternalServiceStatus.CONSENT_REQUIRED: 'claimant.request_assessment',
    ClaimantExternalServiceStatus.READY_TO_REQUEST: 'claimant.request_assessment',
    ClaimantExternalServiceStatus.RETRYABLE_FAILURE: 'claimant.retry_assessment',
    ClaimantExternalServiceStatus.QUEUED: 'claimant.track_assessment',
    ClaimantExternalServiceStatus.ASSIGNED: 'claimant.track_assessment',
    ClaimantExternalServiceStatus.TERMINAL_FAILURE: 'claimant.await_staff_review',
    ClaimantExternalServiceStatus.AWAITING_RECONCILIATION: ('claimant.await_reconciliation'),
}


def project_claimant_primary_action(
    *,
    claim_id: str,
    claim_revision: int,
    next_step: CustomerNextStep,
    external_service_action: ClaimantExternalServiceAction | None,
) -> ClaimantPrimaryAction:
    """Project one deterministic action without frontend precedence rules.

    External-service state is authoritative when it exists. Until the server-owned
    payout/contact and final-submission progression contracts are available, a
    ``ready_to_create`` intake state is deliberately fail-closed instead of exposing
    the legacy direct-creation browser action. All other states remain conversation
    actions carrying the backend-required inputs.
    """

    if external_service_action is not None:
        definition = claimant_action_contract(
            _EXTERNAL_ACTION_CODES[external_service_action.status]
        )
        service_identity = external_service_action.service_identity
        required_inputs = (
            list(definition.required_inputs)
            if external_service_action.status is ClaimantExternalServiceStatus.CONSENT_REQUIRED
            else []
        )
        return ClaimantPrimaryAction(
            action_type=definition.action_type,
            action_code=definition.action_code,
            action_id=f'external-service:{service_identity}',
            target_ref=service_identity,
            available=(
                definition.handler == 'request_assessment' and external_service_action.can_request
            ),
            required_inputs=required_inputs,
            claim_revision=claim_revision,
            registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
            execution_boundary=definition.execution_boundary,
        )

    if next_step.status == 'ready_to_create':
        definition = claimant_action_contract('claimant.continue_conversation')
        return ClaimantPrimaryAction(
            action_type=definition.action_type,
            action_code=definition.action_code,
            action_id=f'customer-next-step:{next_step.status}',
            target_ref=claim_id,
            available=False,
            required_inputs=list(next_step.required_items),
            claim_revision=claim_revision,
            registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
            execution_boundary=definition.execution_boundary,
        )

    if next_step.status == 'confirmation_required' and next_step.required_items:
        definition = claimant_action_contract('claimant.review_details')
        available = True
    else:
        definition = claimant_action_contract('claimant.continue_conversation')
        available = False
    return ClaimantPrimaryAction(
        action_type=definition.action_type,
        action_code=definition.action_code,
        action_id=f'customer-next-step:{next_step.status}',
        target_ref=claim_id,
        available=available,
        required_inputs=list(next_step.required_items),
        claim_revision=claim_revision,
        registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
        execution_boundary=definition.execution_boundary,
    )
