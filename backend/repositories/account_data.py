"""Persistence port for bounded account-owned policy and protected records."""

from datetime import datetime
from typing import Protocol

from backend.domain.account_data import (
    IdentityDocumentRecord,
    PaymentDestinationRecord,
    PolicyNumberRecord,
)
from backend.domain.audit import (
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.models import ActorType, BranchEvaluationRecord, WorkingClaim
from backend.repositories.protocols import IdempotencyRecord, RepositoryConflict

AccountRecord = PolicyNumberRecord | PaymentDestinationRecord | IdentityDocumentRecord
AccountCursorKey = tuple[datetime, str]


class PolicySelectionConflict(RepositoryConflict):
    """The selected account Policy changed or became unavailable during selection."""

    def __init__(
        self,
        policy_id: str,
        *,
        reason: str,
        current_revision: int | None = None,
    ) -> None:
        super().__init__(f'Policy {policy_id} is {reason}.')
        self.policy_id = policy_id
        self.reason = reason
        self.current_revision = current_revision


def account_record_identity(record: AccountRecord) -> tuple[str, str, AuditSubjectType]:
    if isinstance(record, PolicyNumberRecord):
        return 'policy', record.policy_id, AuditSubjectType.POLICY
    if isinstance(record, PaymentDestinationRecord):
        return (
            'payment_destination',
            record.payment_destination_id,
            AuditSubjectType.PAYMENT_DESTINATION,
        )
    return 'identity_document', record.identity_id, AuditSubjectType.IDENTITY


def account_record_audit_matches(
    record: AccountRecord, event: AuditEventEnvelope, *, idempotency_key: str | None
) -> bool:
    kind, identifier, subject_type = account_record_identity(record)
    return (
        event.event_type is AuditEventType.ACTION_COMPLETED
        and event.outcome is AuditOutcome.SUCCEEDED
        and event.subject.subject_type is subject_type
        and event.subject.subject_id == identifier
        and event.subject.claim_id is None
        and event.actor.actor_type is ActorType.CLAIMANT
        and event.actor.actor_id == record.customer_id
        and event.idempotency_key == idempotency_key
        and event.claim_revision is None
        and event.source_refs == [f'{kind}:{identifier}:revision:{record.revision}']
        and event.visibility is AuditVisibility.AUDIT_ONLY
        and event.created_at == record.updated_at
    )


def policy_selection_audit_matches(
    claim: WorkingClaim,
    policy_id: str,
    policy_revision: int,
    idempotency: IdempotencyRecord,
    event: AuditEventEnvelope,
) -> bool:
    return (
        event.event_type is AuditEventType.ACTION_COMPLETED
        and event.outcome is AuditOutcome.SUCCEEDED
        and event.subject.subject_type is AuditSubjectType.CLAIM
        and event.subject.subject_id == claim.claim_id
        and event.subject.claim_id == claim.claim_id
        and event.actor.actor_type is ActorType.CLAIMANT
        and event.actor.actor_id == claim.customer_id
        and event.idempotency_key == idempotency.key
        and event.claim_revision == claim.revision
        and event.source_refs == [f'policy:{policy_id}:revision:{policy_revision}']
        and event.visibility is AuditVisibility.AUDIT_ONLY
    )


class AccountDataRepository(Protocol):
    def create_account_record(
        self,
        record: PolicyNumberRecord | PaymentDestinationRecord | IdentityDocumentRecord,
        idempotency: IdempotencyRecord,
        audit_event: AuditEventEnvelope,
    ) -> None: ...

    def get_policy(self, policy_id: str, customer_id: str) -> PolicyNumberRecord | None: ...

    def get_payment_destination(
        self, payment_destination_id: str, customer_id: str
    ) -> PaymentDestinationRecord | None: ...

    def get_identity_document(
        self, identity_id: str, customer_id: str
    ) -> IdentityDocumentRecord | None: ...

    def list_policies(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PolicyNumberRecord], bool]: ...

    def list_payment_destinations(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[PaymentDestinationRecord], bool]: ...

    def list_identity_documents(
        self,
        customer_id: str,
        *,
        include_inactive: bool,
        after: AccountCursorKey | None,
        limit: int,
    ) -> tuple[list[IdentityDocumentRecord], bool]: ...

    def update_account_record(
        self,
        record: PolicyNumberRecord | PaymentDestinationRecord | IdentityDocumentRecord,
        expected_revision: int,
        audit_event: AuditEventEnvelope,
    ) -> None: ...

    def save_policy_selection(
        self,
        claim: WorkingClaim,
        expected_revision: int,
        policy_id: str,
        policy_revision: int,
        idempotency: IdempotencyRecord,
        branch_evaluation: BranchEvaluationRecord,
        audit_event: AuditEventEnvelope,
    ) -> None: ...
