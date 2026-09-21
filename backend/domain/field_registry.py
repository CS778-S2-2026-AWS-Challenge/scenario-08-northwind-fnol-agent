from backend.domain.models import FormSource, FormStatus, StructuredFormField

AUTHORITY_SENSITIVE = frozenset(
    {'claim.product_family', 'incident.injury_or_danger', 'parties.other_parties', 'incident.type'}
)


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
        'claim.product_family',
        'incident.type',
        'incident.occurred_at',
        'incident.location',
        'incident.description',
        'incident.injury_or_danger',
        'incident.cause',
        'loss.description',
        'parties.other_parties',
        'authorities.police_report_reference',
        'authorities.emergency_services_notified',
        'vehicle.registration',
        'vehicle.damage_description',
        'vehicle.drivable',
        'property.address',
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

FIELD_REGISTRY_VERSION = '6'
