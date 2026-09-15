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


def assessor_action() -> ClaimantExternalServiceAction:
    return ClaimantExternalServiceAction(
        service_identity='vehicle_damage_assessment_routing',
        registry_version='test-v1',
        lifecycle_status='consent_required',
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
        status=ClaimantExternalServiceStatus.CONSENT_REQUIRED,
        routing=AssessorRoutingResult(
            routing_status=AssessorRoutingStatus.NOT_REQUIRED,
            next_step='Request consent.',
        ),
        can_request=True,
    )


def test_external_service_is_the_authoritative_primary_action() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_1',
        claim_revision=7,
        next_step=next_step('ready_to_create'),
        external_service_action=assessor_action(),
    )

    assert projection.action_type == 'external_service'
    assert projection.action_code == 'external_service.request'
    assert projection.action_id == 'external-service:vehicle_damage_assessment_routing'
    assert projection.target_ref == 'vehicle_damage_assessment_routing'
    assert projection.available is True
    assert projection.required_inputs == ['claimant_consent']
    assert projection.claim_revision == 7
    assert projection.projection_version == 'v1'


def test_ready_to_create_projects_claim_creation_action() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_2',
        claim_revision=3,
        next_step=next_step('ready_to_create', ['claimant_confirmation']),
        external_service_action=None,
    )

    assert projection.action_type == 'claim_creation'
    assert projection.action_code == 'claim.create'
    assert projection.action_id == 'customer-next-step:ready_to_create'
    assert projection.target_ref == 'clm_2'
    assert projection.available is True
    assert projection.required_inputs == ['claimant_confirmation']
    assert projection.claim_revision == 3


def test_other_next_steps_are_non_actionable_conversation_projection() -> None:
    projection = project_claimant_primary_action(
        claim_id='clm_3',
        claim_revision=4,
        next_step=next_step('more_information_needed', ['property.address']),
        external_service_action=None,
    )

    assert projection.action_type == 'conversation'
    assert projection.action_code == 'conversation.next_step'
    assert projection.action_id == 'customer-next-step:more_information_needed'
    assert projection.target_ref == 'clm_3'
    assert projection.available is False
    assert projection.required_inputs == ['property.address']
    assert projection.claim_revision == 4
