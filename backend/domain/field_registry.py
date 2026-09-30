import math
import re
from collections.abc import Sequence
from typing import Protocol

from backend.domain.models import FormSource, FormStatus, StructuredFormField

_AMOUNT_TEXT = re.compile(r'(?:nz)?\$?\s*(\d+(?:\.\d{1,2})?)', re.IGNORECASE)


def parse_registered_number(value: object) -> float | None:
    """Read a registered `number` value: a finite, non-negative amount.

    Numbers pass through; text such as "1850", "$1,850" or "NZ$1850.50" is read as
    the same amount. Anything else, including booleans, is not a number.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        number = float(value)
    elif isinstance(value, str):
        match = _AMOUNT_TEXT.fullmatch(value.strip().replace(',', ''))
        if match is None:
            return None
        number = float(match.group(1))
    else:
        return None
    return number if math.isfinite(number) and number >= 0 else None


AUTHORITY_SENSITIVE = frozenset(
    {'claim.product_family', 'incident.injury_or_danger', 'parties.other_parties', 'incident.type'}
)


class _SourcedAssertion(Protocol):
    assertion_id: str
    source_refs: list[str]
    reported_text: str | None


def trusted_origin_assertion(
    current_assertion_id: str | None,
    assertions: Sequence['_SourcedAssertion'],
) -> '_SourcedAssertion | None':
    """The current assertion behind a confirmed field or contents item, if it is a
    trustworthy source for deriving a second fact from it.

    A missing current assertion, or one recorded with no source refs of its own (a
    legacy record, for instance), is not: nothing supports the claim that a specific
    claimant message stated it. Shared by branch_registry (whether a derivable field
    still needs to be asked for) and turn_reducer (what to actually derive), so both
    agree on exactly the same origins.
    """
    origin = next((item for item in assertions if item.assertion_id == current_assertion_id), None)
    if origin is None or not origin.source_refs:
        return None
    return origin


def needs_confirmation(field: StructuredFormField, code: str) -> bool:
    """Identify inference, disputed, or non-claimant authority-sensitive facts.

    Args:
        field: The source-backed fact being considered for acceptance.
        code: The registered field code.

    Returns:
        Whether the fact needs explicit claimant confirmation. Normalisation
        alone never requires confirmation.
    """
    return (
        field.source is FormSource.INFERENCE
        or field.status is FormStatus.DISPUTED
        or (code in AUTHORITY_SENSITIVE and field.source is not FormSource.CLAIMANT)
    )


REGISTERED_FIELD_CODES = frozenset(
    {
        'policy.policy_number',
        'claimant.client_number',
        'claimant.role',
        'claimant.contact_preference',
        'claimant.relationship_to_policyholder',
        'policyholder.identity_ref',
        'policyholder.name',
        'claim.product_family',
        'incident.type',
        'incident.occurred_at',
        'incident.location',
        'incident.description',
        'incident.injury_or_danger',
        'incident.cause',
        'incident.liability_position',
        'loss.estimated_amount',
        'claim.cover_disagreement',
        'loss.description',
        'parties.other_parties',
        'authorities.police_report_reference',
        'authorities.emergency_services_notified',
        'vehicle.registration',
        'vehicle.damage_description',
        'vehicle.drivable',
        'vehicle.use',
        'vehicle.towing_required',
        'vehicle.towing_location',
        'driver.identity_ref',
        'driver.name',
        'driver.phone',
        'driver.email',
        'driver.relationship_to_policyholder',
        'driver.owner_permission',
        'driver.licence_number',
        'driver.licence_status',
        'other_party.insurer_name',
        'other_party.policy_number',
        'other_party.claim_reference',
        'witness.present',
        'witness.name',
        'witness.phone',
        'witness.email',
        'police.status',
        'property.address',
        'property.occupancy_relationship',
        'property.occupancy',
        'property.affected_areas',
        'property.ongoing_risk',
        'property.habitable',
        'injury.persons_affected',
        'injury.severity_reported',
        'injury.medical_attention',
        'incident.discovered_at',
        'theft.entry_context',
        'contents.police_reference',
    }
)

FIELD_REGISTRY_VERSION = '8'
