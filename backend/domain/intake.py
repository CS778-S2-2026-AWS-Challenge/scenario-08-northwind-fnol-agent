import re
from dataclasses import dataclass

from backend.domain.models import CustomerNextStep, FormStatus, ResponsibleParty, WorkingClaim


@dataclass(frozen=True, slots=True)
class ControlledIntakeField:
    field_code: str
    prompt: str
    confirmation_prompt: str
    status: str


# This bounded sequence keeps the prototype repeatable until Northwind supplies
# claim-type requirements and approved routing rules.
CONTROLLED_INTAKE_FIELDS = (
    ControlledIntakeField(
        field_code='incident.description',
        prompt='Tell me what happened in your own words.',
        confirmation_prompt='Please check the incident description before I continue.',
        status='describe_incident',
    ),
    ControlledIntakeField(
        field_code='incident.location',
        prompt='Where did the incident happen?',
        confirmation_prompt='Please check the incident location before I continue.',
        status='provide_incident_location',
    ),
    ControlledIntakeField(
        field_code='loss.description',
        prompt='What was damaged or lost?',
        confirmation_prompt='Please check the damage or loss description before I continue.',
        status='describe_loss',
    ),
)

PRODUCT_FAMILY_INTAKE_FIELD = ControlledIntakeField(
    field_code='claim.product_family',
    prompt='Is this a motor, home, or contents claim?',
    confirmation_prompt='Please check the claim type before I continue.',
    status='identify_product_family',
)

MOTOR_INCIDENT_PATTERN = re.compile(
    r'\b(?:car|vehicle|motorcycle|motorbike|truck|van|ute|bumper|windscreen)\b',
    re.IGNORECASE,
)


def infer_controlled_product_family(message_text: str) -> str | None:
    """Classify only the explicit motor vocabulary supported by the prototype."""
    if MOTOR_INCIDENT_PATTERN.search(message_text) is not None:
        return 'motor'
    return None


def next_controlled_intake_field(claim: WorkingClaim) -> ControlledIntakeField | None:
    for intake_field in CONTROLLED_INTAKE_FIELDS:
        field = claim.form.get(intake_field.field_code)
        if field is None or field.status is not FormStatus.CONFIRMED:
            return intake_field
    product_family_field = claim.form.get(PRODUCT_FAMILY_INTAKE_FIELD.field_code)
    if claim.incident_type is None and (
        product_family_field is None or product_family_field.status is not FormStatus.CONFIRMED
    ):
        return PRODUCT_FAMILY_INTAKE_FIELD
    return None


def next_controlled_intake_step(claim: WorkingClaim) -> CustomerNextStep:
    intake_field = next_controlled_intake_field(claim)
    if intake_field is not None:
        return CustomerNextStep(
            status=intake_field.status,
            summary=intake_field.prompt,
            responsible_party=ResponsibleParty.CLAIMANT,
            required_items=[intake_field.field_code],
        )
    return CustomerNextStep(
        status='ready_to_create',
        summary='Your confirmed report is ready for controlled claim creation.',
        responsible_party=ResponsibleParty.CLAIMANT,
    )
