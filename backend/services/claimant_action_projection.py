"""Build the single claimant primary-action projection from backend state."""

from backend.domain.models import (
    ClaimantExternalServiceAction,
    ClaimantPrimaryAction,
    CustomerNextStep,
)


def project_claimant_primary_action(
    *,
    claim_id: str,
    claim_revision: int,
    next_step: CustomerNextStep,
    external_service_action: ClaimantExternalServiceAction | None,
) -> ClaimantPrimaryAction:
    """Project one deterministic action without frontend precedence rules.

    External-service state is authoritative when it exists. Claim creation is
    represented by the existing ready-to-create next-step status. All other
    states remain a conversation action carrying the backend-required inputs.
    """

    if external_service_action is not None:
        service_identity = external_service_action.service_identity
        return ClaimantPrimaryAction(
            action_type='external_service',
            action_code='external_service.request',
            action_id=f'external-service:{service_identity}',
            target_ref=service_identity,
            available=external_service_action.can_request,
            required_inputs=(
                ['claimant_consent']
                if external_service_action.status.value == 'consent_required'
                else []
            ),
            claim_revision=claim_revision,
        )

    if next_step.status == 'ready_to_create':
        return ClaimantPrimaryAction(
            action_type='claim_creation',
            action_code='claim.create',
            action_id=f'customer-next-step:{next_step.status}',
            target_ref=claim_id,
            available=True,
            required_inputs=list(next_step.required_items),
            claim_revision=claim_revision,
        )

    return ClaimantPrimaryAction(
        action_type='conversation',
        action_code='conversation.next_step',
        action_id=f'customer-next-step:{next_step.status}',
        target_ref=claim_id,
        available=False,
        required_inputs=list(next_step.required_items),
        claim_revision=claim_revision,
    )
