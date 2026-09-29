"""Synchronize confirmed participant facts inside the caller's Claim transaction."""

from collections.abc import Iterable, Mapping
from typing import Any

from pydantic import ValidationError

from backend.core.errors import ApiError
from backend.domain.ids import new_id
from backend.domain.models import (
    DriverRecord,
    FormStatus,
    PolicyholderRecord,
    StructuredFormField,
    WitnessRecord,
    WorkingClaim,
)

PROTECTED_PARTICIPANT_FIELDS = frozenset({'driver.licence_number', 'other_party.policy_number'})


def reject_unprotected_participant_fields(codes: Iterable[str]) -> None:
    """Reject protected facts outside the protected form/participant write path.

    Args:
        codes: Field-code collection supplied by a mutation.
    Raises:
        ApiError: The mutation attempts a protected participant write.
    """
    if PROTECTED_PARTICIPANT_FIELDS.intersection(codes):
        raise ApiError(
            status_code=422,
            code='PROTECTED_DATA_REQUIRES_DEDICATED_ROUTE',
            message='Protected participant values require the protected write path.',
        )


def synchronize_participants(
    claim: WorkingClaim, changes: Mapping[str, StructuredFormField]
) -> WorkingClaim:
    """Apply accepted participant changes without inventing independent fact authority.

    Args:
        claim: Candidate Claim saved by the caller's existing transaction.
        changes: Resolved form changes, retaining source/assertion history in Claim.form.
    Returns:
        Claim with typed records reflecting only confirmed changed facts. Proposed or
        disputed facts remain in the form and are not projected as settled participants.
    """

    try:
        return _synchronize(claim, changes)
    except ValidationError as error:
        raise ApiError(
            status_code=422,
            code='VALIDATION_ERROR',
            message='Participant facts do not satisfy the participant record contract.',
        ) from error


def _synchronize(claim: WorkingClaim, changes: Mapping[str, StructuredFormField]) -> WorkingClaim:
    def updates(prefix: str, attributes: tuple[str, ...]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for attribute in attributes:
            field = changes.get(f'{prefix}.{attribute}')
            if field is not None:
                result[attribute] = field.value if field.status is FormStatus.CONFIRMED else None
        return result

    policyholder = claim.policyholder
    policy_updates = updates('policyholder', ('identity_ref', 'name'))
    if policy_updates:
        policyholder = PolicyholderRecord.model_validate(
            {**(policyholder.model_dump() if policyholder else {}), **policy_updates}
        )
        if not any(policyholder.model_dump().values()):
            policyholder = None

    driver = claim.driver
    driver_updates = updates(
        'driver',
        (
            'identity_ref',
            'name',
            'phone',
            'email',
            'relationship_to_policyholder',
            'owner_permission',
            'licence_status',
        ),
    )
    if driver_updates:
        driver = DriverRecord.model_validate(
            {**(driver.model_dump() if driver else {}), **driver_updates}
        )
        if not any(driver.model_dump().values()):
            driver = None

    witnesses = list(claim.witnesses)
    presence = claim.form.get('witness.present')
    contacts = updates('witness', ('name', 'phone', 'email'))
    if (
        presence is not None
        and presence.status is FormStatus.CONFIRMED
        and str(presence.value).strip().lower() == 'no'
    ):
        witnesses = []
    elif contacts:
        # Only changed contacts may create a record: a later presence=yes must
        # not resurrect contacts belonging to a previously cleared witness.
        current = witnesses[0] if witnesses else None
        values = {**(current.model_dump() if current else {}), **contacts}
        if any(values.get(key) is not None for key in ('name', 'phone', 'email')):
            values['witness_id'] = current.witness_id if current else new_id('wit')
            witnesses = [WitnessRecord.model_validate(values), *witnesses[1:]]
        elif current is not None:
            # A disputed contact is not a new person. Keep its stable identity
            # while the form retains the unresolved assertion and provenance.
            witnesses = [WitnessRecord.model_validate(values), *witnesses[1:]]

    return claim.model_copy(
        update={
            'policyholder': policyholder,
            'driver': driver,
            'witnesses': witnesses,
        }
    )
