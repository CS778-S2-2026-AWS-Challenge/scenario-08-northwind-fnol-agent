"""Shared ownership checks for staff-side Claim mutations."""

from enum import StrEnum

from backend.core.auth import Principal
from backend.core.errors import ApiError
from backend.domain.models import HandoffStatus, WorkingClaim
from backend.repositories.protocols import PersistenceRepository


class ClaimStaffAccess(StrEnum):
    READ_ONLY = 'read_only'
    PRIMARY = 'primary'
    COWORKER = 'coworker'


def claim_staff_access(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    principal: Principal,
) -> ClaimStaffAccess:
    active_handoff = next(
        (
            item
            for item in reversed(repository.list_handoffs(claim.claim_id, claim.customer_id))
            if item.status not in {HandoffStatus.RESOLVED, HandoffStatus.CANCELLED}
        ),
        None,
    )
    owner_id = claim.assignee_id or (
        active_handoff.assigned_to if active_handoff is not None else None
    )
    if owner_id == principal.subject:
        return ClaimStaffAccess.PRIMARY
    if any(
        coworker.staff_id == principal.subject
        for coworker in repository.list_claim_coworkers(claim.claim_id)
    ):
        return ClaimStaffAccess.COWORKER
    return ClaimStaffAccess.READ_ONLY


def require_claim_collaborator(
    repository: PersistenceRepository,
    claim: WorkingClaim,
    principal: Principal,
) -> ClaimStaffAccess:
    access = claim_staff_access(repository, claim, principal)
    if access is ClaimStaffAccess.READ_ONLY:
        raise ApiError(
            status_code=403,
            code='ACCESS_DENIED',
            message='Accept the Claim or obtain cowork access before changing it.',
        )
    return access
