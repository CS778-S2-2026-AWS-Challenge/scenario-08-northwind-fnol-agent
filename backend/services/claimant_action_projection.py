"""Build the single claimant primary-action projection from backend state."""

from dataclasses import dataclass
from types import MappingProxyType

from backend.domain.agent_action_registry import action_contract
from backend.domain.models import (
    ClaimantExternalServiceAction,
    ClaimantExternalServiceStatus,
    ClaimantPrimaryAction,
    CustomerNextStep,
)

CLAIMANT_ACTION_REGISTRY_VERSION = '2026-09-15.1'


@dataclass(frozen=True)
class ClaimantActionDefinition:
    action_code: str
    execution_boundary: str
    required_inputs: tuple[str, ...] = ()


CLAIMANT_ACTION_REGISTRY = MappingProxyType(
    {
        'claim_creation': ClaimantActionDefinition('claim.create', 'claimant_api'),
        'conversation': ClaimantActionDefinition(
            'conversation.present_options', 'conversation'
        ),
        ClaimantExternalServiceStatus.CONSENT_REQUIRED: ClaimantActionDefinition(
            'external.prepare_request', 'external_service', ('claimant_consent',)
        ),
        ClaimantExternalServiceStatus.READY_TO_REQUEST: ClaimantActionDefinition(
            'external.submit_request', 'external_service'
        ),
        ClaimantExternalServiceStatus.RETRYABLE_FAILURE: ClaimantActionDefinition(
            'external.retry_request', 'external_service'
        ),
        ClaimantExternalServiceStatus.QUEUED: ClaimantActionDefinition(
            'external.track_request', 'external_service'
        ),
        ClaimantExternalServiceStatus.ASSIGNED: ClaimantActionDefinition(
            'external.track_request', 'external_service'
        ),
        ClaimantExternalServiceStatus.TERMINAL_FAILURE: ClaimantActionDefinition(
            'external.reconcile_response', 'external_service'
        ),
        ClaimantExternalServiceStatus.AWAITING_RECONCILIATION: ClaimantActionDefinition(
            'external.reconcile_response', 'external_service'
        ),
    }
)

for _definition in CLAIMANT_ACTION_REGISTRY.values():
    action_contract(_definition.action_code)


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
        definition = CLAIMANT_ACTION_REGISTRY[external_service_action.status]
        service_identity = external_service_action.service_identity
        return ClaimantPrimaryAction(
            action_type='external_service',
            action_code=definition.action_code,
            action_id=f'external-service:{service_identity}',
            target_ref=service_identity,
            available=external_service_action.can_request,
            required_inputs=list(definition.required_inputs),
            claim_revision=claim_revision,
            registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
            execution_boundary=definition.execution_boundary,
        )

    if next_step.status == 'ready_to_create':
        definition = CLAIMANT_ACTION_REGISTRY['claim_creation']
        return ClaimantPrimaryAction(
            action_type='claim_creation',
            action_code=definition.action_code,
            action_id=f'customer-next-step:{next_step.status}',
            target_ref=claim_id,
            available=True,
            required_inputs=list(next_step.required_items),
            claim_revision=claim_revision,
            registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
            execution_boundary=definition.execution_boundary,
        )

    definition = CLAIMANT_ACTION_REGISTRY['conversation']
    return ClaimantPrimaryAction(
        action_type='conversation',
        action_code=definition.action_code,
        action_id=f'customer-next-step:{next_step.status}',
        target_ref=claim_id,
        available=False,
        required_inputs=list(next_step.required_items),
        claim_revision=claim_revision,
        registry_version=CLAIMANT_ACTION_REGISTRY_VERSION,
        execution_boundary=definition.execution_boundary,
    )
