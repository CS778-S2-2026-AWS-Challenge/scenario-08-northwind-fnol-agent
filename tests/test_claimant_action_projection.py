import pytest

from backend.domain.claimant_action_registry import (
    CLAIMANT_ACTION_REGISTRY,
    CLAIMANT_ACTION_REGISTRY_VERSION,
    claimant_action_contract,
)
from backend.domain.models import (
    AssessorRoutingResult,
    AssessorRoutingStatus,
    ClaimantExternalServiceAction,
    ClaimantExternalServiceStatus,
    CustomerNextStep,
    ResponsibleParty,
)
from backend.services.claimant_action_projection import project_claimant_primary_action


def next_step(status: str, required_items: list[str] | None = None) -> CustomerNextStep:
    return CustomerNextStep(
        status=status,
        summary='Synthetic next step.',
        responsible_party=ResponsibleParty.CLAIMANT,
        required_items=required_items or [],
    )


def assessor_action(
    status: ClaimantExternalServiceStatus = ClaimantExternalServiceStatus.CONSENT_REQUIRED,
    *,
    can_request: bool = True,
) -> ClaimantExternalServiceAction:
    return ClaimantExternalServiceAction(
        service_identity='vehicle_damage_assessment_routing',
        registry_version='test-v1',
        lifecycle_status=status.value,
        capability_provenance='test',
        access_form='claimant_consent',
        status_label='Consent required',
        status_detail='Consent is required.',
        pending_owner='claimant',
        next_action='Give consent.',
        limitation='Synthetic test action.',
        service_name='Vehicle damage assessment',
        provider='Controlled assessment fixture',
        purpose='Request an assessor.',
        shared_data_summary=['confirmed incident region'],
        status=status,
        routing=AssessorRoutingResult(
            routing_status=AssessorRoutingStatus.NOT_REQUIRED,
            next_step='Request consent.',
        ),
        can_request=can_request,
    )


@pytest.mark.parametrize(
    ('status', 'can_request', 'action_code', 'available', 'required_inputs'),
    [
        (
            ClaimantExternalServiceStatus.CONSENT_REQUIRED,
            True,
            'claimant.request_assessment',
            True,
            ['claimant_consent'],
        ),
        (
            ClaimantExternalServiceStatus.READY_TO_REQUEST,
            True,
            'claimant.request_assessment',
            True,
            [],
        ),
        (
            ClaimantExternalServiceStatus.RETRYABLE_FAILURE,
            True,
            'claimant.retry_assessment',
            True,
            [],
        ),
        (
            ClaimantExternalServiceStatus.QUEUED,
            False,
            'claimant.track_assessment',
            False,
            [],
        ),
        (
            ClaimantExternalServiceStatus.ASSIGNED,
            False,
            'claimant.track_assessment',
            False,
            [],
        ),
        (
            ClaimantExternalServiceStatus.TERMINAL_FAILURE,
            False,
            'claimant.await_staff_review',
            False,
            [],
        ),
        (
            ClaimantExternalServiceStatus.AWAITING_RECONCILIATION,
            False,
            'claimant.await_reconciliation',
            False,
            [],
        ),
    ],
)
def test_external_service_is_the_authoritative_primary_action(
    status: ClaimantExternalServiceStatus,
    can_request: bool,
    action_code: str,
    available: bool,
    required_inputs: list[str],
) -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_1',
        claim_revision=7,
        next_step=next_step('ready_to_create'),
        external_service_action=assessor_action(status, can_request=can_request),
    )

    assert projection.action_type == 'external_service'
    assert projection.action_code == action_code
    assert projection.action_id == 'external-service:vehicle_damage_assessment_routing'
    assert projection.target_ref == 'vehicle_damage_assessment_routing'
    assert projection.available is available
    assert projection.required_inputs == required_inputs
    assert projection.claim_revision == 7
    assert projection.registry_version == CLAIMANT_ACTION_REGISTRY_VERSION
    assert projection.visibility == 'claimant'
    assert projection.execution_boundary == 'external_service'
    assert projection.projection_version == 'v1'
    assert claimant_action_contract(projection.action_code).action_code == projection.action_code


def test_ready_to_create_is_fail_closed_until_submission_progression_exists() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_2',
        claim_revision=3,
        next_step=next_step('ready_to_create', ['claimant_confirmation']),
        external_service_action=None,
    )

    assert projection.action_type == 'conversation'
    assert projection.action_code == 'claimant.continue_conversation'
    assert projection.action_id == 'customer-next-step:ready_to_create'
    assert projection.target_ref == 'clm_2'
    assert projection.available is False
    assert projection.required_inputs == ['claimant_confirmation']
    assert projection.claim_revision == 3
    assert projection.execution_boundary == 'conversation'


def test_confirmation_required_projects_review_details() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_3',
        claim_revision=4,
        next_step=next_step(
            'confirmation_required',
            ['incident.occurred_at', 'incident.location'],
        ),
        external_service_action=None,
    )

    assert projection.action_code == 'claimant.review_details'
    assert projection.available is True
    assert projection.required_inputs == ['incident.occurred_at', 'incident.location']


def test_other_next_steps_are_non_actionable_conversation_projection() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_3',
        claim_revision=4,
        next_step=next_step('more_information_needed', ['property.address']),
        external_service_action=None,
    )

    assert projection.action_type == 'conversation'
    assert projection.action_code == 'claimant.continue_conversation'
    assert projection.action_id == 'customer-next-step:more_information_needed'
    assert projection.target_ref == 'clm_3'
    assert projection.available is False
    assert projection.required_inputs == ['property.address']
    assert projection.claim_revision == 4
    assert projection.execution_boundary == 'conversation'


def test_every_claimant_projection_action_resolves_in_authoritative_registry() -> None:
    for action_code, contract in CLAIMANT_ACTION_REGISTRY.items():
        assert action_code.startswith('claimant.')
        assert claimant_action_contract(action_code) is contract
