from datetime import UTC, datetime

import pytest

from backend.domain.field_registry import REGISTERED_FIELD_CODES
from backend.domain.intake import (
    BRANCH_NON_BLOCKING_FIELDS,
    CURRENT_ACTION_REQUIREMENTS,
    infer_controlled_incident_type,
    next_controlled_intake_field,
    next_controlled_intake_step,
    resolve_controlled_intake_requirements,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    CustomerNextStep,
    FormSource,
    FormStatus,
    NeededFor,
    ResponsibleParty,
    StructuredFormField,
    WorkingClaim,
)


def _field(value: object, *, status: FormStatus = FormStatus.CONFIRMED) -> StructuredFormField:
    timestamp = datetime(2026, 8, 26, 4, 0, tzinfo=UTC)
    return StructuredFormField(
        value=value,
        source=FormSource.CLAIMANT,
        status=status,
        needed_for=NeededFor.CURRENT_ACTION,
        confidence=1.0 if status is FormStatus.CONFIRMED else 0.9,
        updated_at=timestamp,
        updated_by=ActorReference(actor_type=ActorType.CLAIMANT, actor_id='cus_dynamic'),
    )


def _claim(
    *,
    incident_type: str | None = None,
    form: dict[str, StructuredFormField] | None = None,
) -> WorkingClaim:
    timestamp = datetime(2026, 8, 26, 4, 0, tzinfo=UTC)
    return WorkingClaim(
        claim_id='clm_dynamic',
        customer_id='cus_dynamic',
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        incident_type=incident_type,
        form=form or {},
        customer_next_step=CustomerNextStep(
            status='describe_incident',
            summary='Describe the incident.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=timestamp,
        updated_at=timestamp,
    )


def _complete_core_form() -> dict[str, StructuredFormField]:
    return {
        'incident.description': _field('A bounded synthetic incident.'),
        'incident.location': _field('Auckland'),
        'loss.description': _field('Synthetic loss'),
    }


def test_requirement_projection_skips_out_of_order_confirmed_facts() -> None:
    claim = _claim(
        incident_type='motor',
        form={
            'incident.location': _field('Queen Street'),
            'loss.description': _field('Rear bumper damage'),
        },
    )

    projection = resolve_controlled_intake_requirements(claim)

    assert projection.claim_family == 'motor'
    assert projection.missing_required_now == ('incident.description',)
    assert set(projection.satisfied) == {
        'incident.location',
        'loss.description',
        'incident.type',
    }
    assert next_controlled_intake_field(claim).field_code == 'incident.description'

    updated_claim = claim.model_copy(
        update={
            'form': {
                **claim.form,
                'incident.description': _field('Another car hit mine from behind.'),
            }
        }
    )
    updated_projection = resolve_controlled_intake_requirements(updated_claim)

    assert updated_projection.missing_required_now == ()
    assert next_controlled_intake_field(updated_claim) is None


def test_proposed_fact_remains_missing_until_confirmation() -> None:
    claim = _claim(
        incident_type='motor',
        form={
            'incident.description': _field(
                'Another car hit mine from behind.',
                status=FormStatus.PROPOSED,
            ),
            'incident.location': _field('Queen Street'),
            'loss.description': _field('Rear bumper damage'),
        },
    )

    projection = resolve_controlled_intake_requirements(claim)

    assert projection.missing_required_now == ('incident.description',)
    assert 'incident.description' not in projection.satisfied


def test_confirmed_incident_type_field_supplies_branch_context_before_denormalised_type() -> None:
    claim = _claim(
        form={
            'incident.description': _field('Water entered my house.'),
            'incident.location': _field('Auckland'),
            'loss.description': _field('Ceiling damage'),
            'incident.type': _field('home'),
        }
    )

    projection = resolve_controlled_intake_requirements(claim)

    assert projection.claim_family == 'home'
    assert projection.missing_required_now == ()
    assert projection.non_blocking == ('property.address', 'property.affected_areas')


@pytest.mark.parametrize(
    ('claim_family', 'expected_non_blocking'),
    [
        (
            'motor',
            ('vehicle.registration', 'vehicle.damage_description', 'vehicle.drivable'),
        ),
        ('home', ('property.address', 'property.affected_areas')),
        ('contents', ()),
    ],
)
def test_branch_fields_are_active_context_but_not_invented_as_mandatory(
    claim_family: str,
    expected_non_blocking: tuple[str, ...],
) -> None:
    projection = resolve_controlled_intake_requirements(
        _claim(incident_type=claim_family, form=_complete_core_form())
    )

    assert projection.missing_required_now == ()
    assert projection.non_blocking == expected_non_blocking


def test_requirement_snapshot_references_only_registered_fields() -> None:
    requirement_codes = {requirement.field_code for requirement in CURRENT_ACTION_REQUIREMENTS}
    branch_codes = {
        field_code
        for field_codes in BRANCH_NON_BLOCKING_FIELDS.values()
        for field_code in field_codes
    }

    assert requirement_codes <= REGISTERED_FIELD_CODES
    assert branch_codes <= REGISTERED_FIELD_CODES


def test_non_motor_core_completion_does_not_claim_creation_readiness() -> None:
    for claim_family in ('home', 'contents'):
        next_step = next_controlled_intake_step(
            _claim(incident_type=claim_family, form=_complete_core_form())
        )

        assert next_step.status == 'core_details_confirmed'
        assert next_step.responsible_party is ResponsibleParty.NORTHWIND
        assert next_step.required_items == []


def test_motor_core_completion_preserves_existing_creation_readiness() -> None:
    next_step = next_controlled_intake_step(
        _claim(incident_type='motor', form=_complete_core_form())
    )

    assert next_step.status == 'ready_to_create'
    assert next_step.responsible_party is ResponsibleParty.CLAIMANT


def test_unsupported_claim_family_remains_a_missing_requirement() -> None:
    claim = _claim(incident_type='travel', form=_complete_core_form())

    projection = resolve_controlled_intake_requirements(claim)

    assert projection.claim_family is None
    assert projection.missing_required_now == ('incident.type',)
    assert projection.non_blocking == ()


def test_requirement_projection_is_deterministic_for_unchanged_claim_state() -> None:
    claim = _claim(
        incident_type='motor',
        form={'incident.description': _field('My car was hit.')},
    )

    assert resolve_controlled_intake_requirements(claim) == resolve_controlled_intake_requirements(
        claim
    )


@pytest.mark.parametrize(
    ('message', 'expected'),
    [
        ('My car was hit from behind.', 'motor'),
        ('There was water damage in my house.', 'home'),
        ('Some of my belongings were stolen.', 'contents'),
        ('My car and house were both damaged.', None),
        ('My car damaged someone else\'s property.', 'motor'),
    ],
)
def test_claim_family_inference_is_bounded_and_ambiguous_input_stays_unknown(
    message: str,
    expected: str | None,
) -> None:
    assert infer_controlled_incident_type(message) == expected
