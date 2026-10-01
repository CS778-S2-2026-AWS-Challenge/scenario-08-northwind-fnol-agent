"""Audit fact builder for an authoritative Claim decision."""

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
from backend.domain.models import ActorType, ClaimDecisionRecord, WorkingClaim


def build_claim_decision_audit_event(
    *,
    principal: Principal,
    claim: WorkingClaim,
    decision: ClaimDecisionRecord,
    route: str,
    idempotency_key: str,
    required_permission: str,
    created_at: datetime,
) -> AuditEventEnvelope:
    """Build the stable append-only fact committed with one Claim decision."""

    identity = f'{principal.subject}:{route}:{idempotency_key}:{decision.decision_id}'
    return AuditEventEnvelope(
        event_id=f'aud_claim_decision_{sha256(identity.encode()).hexdigest()[:24]}',
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
        reason=f'Staff recorded the final Claim decision: {decision.decision.value}.',
        source_refs=[decision.decision_id],
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


__all__ = ['build_claim_decision_audit_event']
