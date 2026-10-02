"""Audit facts for claimant-visible messages sent by staff."""

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
from backend.domain.models import ActorType, MessageRecord, WorkingClaim


def build_staff_message_audit_event(
    *,
    principal: Principal,
    claim: WorkingClaim,
    message: MessageRecord,
    route: str,
    idempotency_key: str,
    required_permission: str,
    created_at: datetime,
    source_refs: Iterable[str] = (),
) -> AuditEventEnvelope:
    """Build one stable audit fact for an authorised staff-to-claimant message."""

    identity = f'{principal.subject}:{route}:{idempotency_key}:{message.message_id}'
    refs = list(dict.fromkeys((message.message_id, *source_refs)))[:100]
    return AuditEventEnvelope(
        event_id=f'aud_staff_message_{sha256(identity.encode()).hexdigest()[:24]}',
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
        reason='Staff sent a claimant-visible message.',
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


__all__ = ['build_staff_message_audit_event']
