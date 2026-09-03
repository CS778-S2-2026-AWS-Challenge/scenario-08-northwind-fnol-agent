"""Provider-neutral audit event contract.

The event envelope is deliberately separate from Claim State.  It records an
immutable fact about an authorised, rejected, or completed action; it does not
serve as a second source of current claim truth.
"""

from datetime import datetime
from enum import Enum

from pydantic import Field, model_validator

from backend.domain.models import ActorReference, ContractModel


class AuditEventType(str, Enum):
    """Initial bounded event vocabulary for the Week 5 audit contract."""

    CONSENT_GRANTED = 'consent.granted'
    CONSENT_WITHDRAWN = 'consent.withdrawn'
    PERMISSION_AUTHORISED = 'permission.authorised'
    PERMISSION_REJECTED = 'permission.rejected'
    ACTION_PREPARED = 'action.prepared'
    ACTION_COMPLETED = 'action.completed'
    ACTION_FAILED = 'action.failed'
    ACTION_UNKNOWN_OUTCOME = 'action.unknown_outcome'
    ACCESS_DENIED = 'access.denied'


class AuditOutcome(str, Enum):
    """Observed outcome of the action represented by an audit event."""

    SUCCEEDED = 'succeeded'
    REJECTED = 'rejected'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class AuditSubjectType(str, Enum):
    """Logical subject categories that can be audited."""

    CLAIM = 'claim'
    CUSTOMER = 'customer'
    EXTERNAL_REQUEST = 'external_request'
    CONFIGURATION = 'configuration'
    ACCESS = 'access'


class AuditVisibility(str, Enum):
    """Projection boundary for an audit event."""

    CLAIMANT_VISIBLE = 'claimant_visible'
    SHARED = 'shared'
    INTERNAL_ONLY = 'internal_only'
    ADMINISTRATION_ONLY = 'administration_only'
    AUDIT_ONLY = 'audit_only'


class AuditPermissionOutcome(str, Enum):
    """Decision recorded for the permission relevant to an event."""

    AUTHORISED = 'authorised'
    REJECTED = 'rejected'
    REVIEW_REQUIRED = 'review_required'


class AuditSubject(ContractModel):
    """The logical object to which an audit event belongs."""

    subject_type: AuditSubjectType
    subject_id: str = Field(min_length=1, max_length=200)
    claim_id: str | None = Field(default=None, min_length=1, max_length=100)

    @model_validator(mode='after')
    def validate_claim_scope(self) -> 'AuditSubject':
        if self.subject_type is AuditSubjectType.CLAIM and self.claim_id != self.subject_id:
            raise ValueError('Claim subjects must repeat their subject_id as claim_id.')
        return self


class AuditActor(ActorReference):
    """Actor identity plus the authentication source used for the action."""

    auth_source: str = Field(min_length=1, max_length=100)


class AuditPermission(ContractModel):
    """Permission requirement and decision associated with an event."""

    required_permission: str = Field(min_length=1, max_length=150)
    outcome: AuditPermissionOutcome


class AuditEventEnvelope(ContractModel):
    """Immutable, append-only audit fact.

    Args:
        event_id: Stable identifier for idempotent append and replay checks.
        event_type: Controlled event vocabulary entry.
        outcome: The observed result, including rejected and unknown outcomes.
        subject: Audited logical object and optional claim scope.
        actor: Account or service identity that caused the event.
        reason: Human-readable bounded reason for the action.
        source_refs: References to messages, decisions, requests, or evidence.
        permission: Permission decision when the event is authority-related.
        consent_ref: Related consent identity when applicable.
        consent_state: Recorded consent state when applicable.
        visibility: Projection boundary for authorised readers.
        correlation_id: Request or operation correlation identity.
        idempotency_key: Client operation key when one exists.
        claim_revision: Resulting Claim revision for material claim mutations.
        created_at: Server-recorded event time.
    """

    event_id: str = Field(pattern=r'^aud_[A-Za-z0-9_-]{1,96}$')
    event_type: AuditEventType
    outcome: AuditOutcome
    subject: AuditSubject
    actor: AuditActor
    reason: str = Field(min_length=1, max_length=1000)
    source_refs: list[str] = Field(default_factory=list, max_length=100)
    permission: AuditPermission | None = None
    consent_ref: str | None = Field(default=None, min_length=1, max_length=100)
    consent_state: str | None = Field(default=None, min_length=1, max_length=50)
    visibility: AuditVisibility
    correlation_id: str | None = Field(default=None, min_length=1, max_length=100)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=200)
    claim_revision: int | None = Field(default=None, ge=1)
    created_at: datetime

    @model_validator(mode='after')
    def validate_event_requirements(self) -> 'AuditEventEnvelope':
        if (
            self.event_type
            in {
                AuditEventType.PERMISSION_AUTHORISED,
                AuditEventType.PERMISSION_REJECTED,
            }
            and self.permission is None
        ):
            raise ValueError('Permission events require a permission decision.')
        if self.event_type in {
            AuditEventType.CONSENT_GRANTED,
            AuditEventType.CONSENT_WITHDRAWN,
        } and (self.consent_ref is None or self.consent_state is None):
            raise ValueError('Consent events require a consent reference and state.')
        if self.subject.subject_type is AuditSubjectType.CLAIM and self.claim_revision is None:
            raise ValueError('Claim audit events require the resulting claim revision.')
        return self


__all__ = [
    'AuditActor',
    'AuditEventEnvelope',
    'AuditEventType',
    'AuditOutcome',
    'AuditPermission',
    'AuditPermissionOutcome',
    'AuditSubject',
    'AuditSubjectType',
    'AuditVisibility',
]
