"""Audit facts for material handoff lifecycle mutations."""

from collections.abc import Iterable
from datetime import datetime
from hashlib import sha256

from backend.core.auth import Principal
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditPermission,
    AuditPermissionOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import ActorType, HandoffRecord, WorkingClaim


def build_handoff_audit_event(
    *,
    principal: Principal,
    claim: WorkingClaim,
    handoff: HandoffRecord,
    route: str,
    idempotency_key: str,
    required_permission: str,
    reason: str,
    created_at: datetime,
    source_refs: Iterable[str] = (),
) -> AuditEventEnvelope:
    """Build one stable audit fact for a committed handoff mutation.

    Args:
        principal: Authenticated actor executing the mutation.
        claim: Resulting authoritative Claim State.
        handoff: Resulting handoff state.
        route: Authoritative operation route.
        idempotency_key: Client operation identity used for replay.
        required_permission: Permission or registered action checked before execution.
        reason: Bounded audit-safe description of the mutation.
        created_at: Server timestamp for the accepted operation.
        source_refs: Additional durable references relevant to the mutation.

    Returns:
        A deterministic Claim-scoped audit event suitable for atomic persistence.
    """

    identity = f'{principal.subject}:{route}:{idempotency_key}:{handoff.handoff_id}'
    refs = list(dict.fromkeys((handoff.handoff_id, *source_refs)))[:100]
    return AuditEventEnvelope(
        event_id=f'aud_handoff_{sha256(identity.encode()).hexdigest()[:24]}',
        event_type=AuditEventType.ACTION_COMPLETED,
        outcome=AuditOutcome.SUCCEEDED,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=claim.claim_id,
            claim_id=claim.claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType(principal.actor_type),
            actor_id=principal.subject,
            auth_source=principal.auth_source,
        ),
        reason=reason,
        source_refs=refs,
        permission=AuditPermission(
            required_permission=required_permission,
            outcome=AuditPermissionOutcome.AUTHORISED,
        ),
        visibility=AuditVisibility.INTERNAL_ONLY,
        correlation_id=idempotency_key,
        idempotency_key=idempotency_key,
        claim_revision=claim.revision,
        created_at=created_at,
    )


__all__ = ['build_handoff_audit_event']
