"""Persistence port for account-owned policy summaries."""

from typing import Protocol

from backend.domain.audit import (
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import ActorType
from backend.domain.policies import PolicySummaryRecord
from backend.repositories.protocols import IdempotencyRecord


def policy_audit_matches(policy: PolicySummaryRecord, event: AuditEventEnvelope) -> bool:
    """Return whether an audit event belongs to this Policy Summary mutation."""

    return (
        event.event_type is AuditEventType.ACTION_COMPLETED
        and event.outcome is AuditOutcome.SUCCEEDED
        and event.subject.subject_type is AuditSubjectType.POLICY
        and event.subject.subject_id == policy.policy_id
        and event.subject.claim_id is None
        and event.actor.actor_type is ActorType.CLAIMANT
        and event.actor.actor_id == policy.customer_id
        and event.claim_revision is None
        and event.source_refs == [f'policy:{policy.policy_id}:revision:{policy.revision}']
        and event.visibility is AuditVisibility.AUDIT_ONLY
        and event.created_at == policy.updated_at
    )


class PolicySummaryRepository(Protocol):
    def create_policy_summary(
        self,
        policy: PolicySummaryRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None: ...

    def get_policy_summary(
        self, policy_id: str, customer_id: str
    ) -> PolicySummaryRecord | None: ...

    def list_policy_summaries(
        self,
        customer_id: str,
        *,
        include_inactive: bool = False,
        offset: int = 0,
        limit: int = 25,
    ) -> tuple[list[PolicySummaryRecord], bool]: ...

    def update_policy_summary(
        self,
        policy: PolicySummaryRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
    ) -> None: ...
