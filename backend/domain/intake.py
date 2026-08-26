import re
from dataclasses import dataclass

from backend.domain.models import CustomerNextStep, FormStatus, ResponsibleParty, WorkingClaim


@dataclass(frozen=True, slots=True)
class ControlledIntakeField:
    field_code: str
    prompt: str
    confirmation_prompt: str
    status: str


@dataclass(frozen=True, slots=True)
class IntakeRequirementProjection:
    claim_family: str | None
    satisfied: tuple[str, ...]
    missing_required_now: tuple[str, ...]
    non_blocking: tuple[str, ...]


INCIDENT_DESCRIPTION_FIELD = ControlledIntakeField(
    field_code='incident.description',
    prompt='Tell me what happened in your own words.',
    confirmation_prompt='Please check the incident description before I continue.',
    status='describe_incident',
)
INCIDENT_LOCATION_FIELD = ControlledIntakeField(
    field_code='incident.location',
    prompt='Where did the incident happen?',
    confirmation_prompt='Please check the incident location before I continue.',
    status='provide_incident_location',
)
LOSS_DESCRIPTION_FIELD = ControlledIntakeField(
    field_code='loss.description',
    prompt='What was damaged or lost?',
    confirmation_prompt='Please check the damage or loss description before I continue.',
    status='describe_loss',
)
INCIDENT_TYPE_INTAKE_FIELD = ControlledIntakeField(
    field_code='incident.type',
    prompt='What type of incident is this: motor, home, or contents?',
    confirmation_prompt='Please check the incident type before I continue.',
    status='identify_incident_type',
)

# This is a bounded MVP requirement snapshot, not a Northwind production rule set.
# It preserves the currently implemented creation prerequisites while calculating
# what is missing from the authoritative Claim State instead of advancing through
# a questionnaire cursor.
CURRENT_ACTION_REQUIREMENTS = (
    INCIDENT_DESCRIPTION_FIELD,
    INCIDENT_LOCATION_FIELD,
    LOSS_DESCRIPTION_FIELD,
    INCIDENT_TYPE_INTAKE_FIELD,
)

# Compatibility export for the existing controlled motor claim-creation boundary.
# Claim creation uses this as a prerequisite set, not as the claimant question order.
CONTROLLED_INTAKE_FIELDS = CURRENT_ACTION_REQUIREMENTS[:-1]

# Registered branch-specific fields are active context for the supported claim family,
# but are not made mandatory for the current action without approved Northwind rules.
BRANCH_NON_BLOCKING_FIELDS: dict[str, tuple[str, ...]] = {
    'motor': (
        'vehicle.registration',
        'vehicle.damage_description',
        'vehicle.drivable',
    ),
    'home': (
        'property.address',
        'property.affected_areas',
    ),
    'contents': (),
}

SUPPORTED_CLAIM_FAMILIES = frozenset(BRANCH_NON_BLOCKING_FIELDS)

MOTOR_INCIDENT_PATTERN = re.compile(
    r'\b(?:car|vehicle|motorcycle|motorbike|truck|van|ute|bumper|windscreen)\b',
    re.IGNORECASE,
)
HOME_INCIDENT_PATTERN = re.compile(
    r'\b(?:home|house|building)\b',
    re.IGNORECASE,
)
CONTENTS_INCIDENT_PATTERN = re.compile(
    r'\b(?:contents|belongings|possessions)\b',
    re.IGNORECASE,
)


def infer_controlled_incident_type(message_text: str) -> str | None:
    """Classify only explicit claim-family vocabulary supported by the MVP."""
    matches = [
        claim_family
        for claim_family, pattern in (
            ('motor', MOTOR_INCIDENT_PATTERN),
            ('home', HOME_INCIDENT_PATTERN),
            ('contents', CONTENTS_INCIDENT_PATTERN),
        )
        if pattern.search(message_text) is not None
    ]
    return matches[0] if len(matches) == 1 else None


def _confirmed(claim: WorkingClaim, field_code: str) -> bool:
    field = claim.form.get(field_code)
    return field is not None and field.status is FormStatus.CONFIRMED


def _claim_family(claim: WorkingClaim) -> str | None:
    if claim.incident_type in SUPPORTED_CLAIM_FAMILIES:
        return claim.incident_type
    incident_type_field = claim.form.get(INCIDENT_TYPE_INTAKE_FIELD.field_code)
    if (
        incident_type_field is not None
        and incident_type_field.status is FormStatus.CONFIRMED
        and isinstance(incident_type_field.value, str)
    ):
        candidate = incident_type_field.value.strip().lower()
        if candidate in SUPPORTED_CLAIM_FAMILIES:
            return candidate
    return None


def _requirement_is_satisfied(claim: WorkingClaim, field: ControlledIntakeField) -> bool:
    if field.field_code == INCIDENT_TYPE_INTAKE_FIELD.field_code:
        return _claim_family(claim) is not None
    return _confirmed(claim, field.field_code)


def resolve_controlled_intake_requirements(claim: WorkingClaim) -> IntakeRequirementProjection:
    """Project the current bounded FNOL requirements from authoritative Claim State."""
    claim_family = _claim_family(claim)
    satisfied: list[str] = []
    missing_required_now: list[str] = []

    for requirement in CURRENT_ACTION_REQUIREMENTS:
        if _requirement_is_satisfied(claim, requirement):
            satisfied.append(requirement.field_code)
        else:
            missing_required_now.append(requirement.field_code)

    non_blocking = BRANCH_NON_BLOCKING_FIELDS.get(claim_family, ())
    return IntakeRequirementProjection(
        claim_family=claim_family,
        satisfied=tuple(satisfied),
        missing_required_now=tuple(missing_required_now),
        non_blocking=tuple(non_blocking),
    )


def next_controlled_intake_field(claim: WorkingClaim) -> ControlledIntakeField | None:
    projection = resolve_controlled_intake_requirements(claim)
    if not projection.missing_required_now:
        return None
    next_code = projection.missing_required_now[0]
    for requirement in CURRENT_ACTION_REQUIREMENTS:
        if requirement.field_code == next_code:
            return requirement
    raise RuntimeError(f'Unknown controlled intake requirement: {next_code}.')


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
