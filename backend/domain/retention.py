"""Authoritative P17 retention execution contracts.

Retention owns destructive cleanup execution only.  It does not own Claim
terminal state, recovery expiry, Session business state, ExternalTask result,
or authentication state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from hashlib import sha256
from types import MappingProxyType
from typing import Any

from pydantic import Field, model_validator

from backend.domain.models import (
    ContractModel,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)

INCOMPLETE_CLAIM_RETENTION_POLICY_ID = 'incomplete_claim_retention'
INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION = 'v1'


class ResourceAccessClosed(KeyError):
    """A retained resource still exists internally but claimant access is closed.

    This internal signal must always be projected using the same concealed-
    absence contract as a resource that does not exist.
    """

    def __init__(self, claim_id: str) -> None:
        super().__init__(claim_id)
        self.claim_id = claim_id


class RetentionClassification(str, Enum):
    DELETE = 'delete'
    ANONYMISE = 'anonymise'
    RETAIN = 'retain'
    TOMBSTONE = 'tombstone'


class RetentionOperationStatus(str, Enum):
    RESERVED = 'reserved'
    HELD = 'held'
    RECONCILIATION_REQUIRED = 'reconciliation_required'
    COMPLETED = 'completed'


class RetentionTargetKind(str, Enum):
    OBJECT_BYTES = 'object_bytes'
    MONGO_RECORD = 'mongo_record'
    TOMBSTONE = 'tombstone'


class RetentionStepStatus(str, Enum):
    PENDING = 'pending'
    SATISFIED = 'satisfied'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class ObjectDeletionOutcome(str, Enum):
    DELETED = 'deleted'
    ALREADY_ABSENT = 'already_absent'
    FAILED = 'failed'
    UNKNOWN = 'unknown'


class RetentionHoldReason(str, Enum):
    LEGAL_HOLD = 'legal_hold'
    DISPUTE = 'dispute'
    INVESTIGATION = 'investigation'
    AUTHORISED_STAFF_REVIEW = 'authorised_staff_review'


# This is the approved prototype classification direction, not a statement of
# production legal-retention obligations.  Multiple classifications mean the
# final cleanup step may need to preserve a tombstone/minimal authority while
# removing or anonymising claimant-sensitive content.
RETENTION_CLASSIFICATION_BASELINE: Mapping[
    str,
    tuple[RetentionClassification, ...],
] = MappingProxyType(
    {
        'WorkingClaim': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.TOMBSTONE,
        ),
        'SessionRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.TOMBSTONE,
        ),
        'MessageRecord': (
            RetentionClassification.DELETE,
            RetentionClassification.ANONYMISE,
        ),
        'FollowUpRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.TOMBSTONE,
        ),
        'FollowUpOperation': (
            RetentionClassification.RETAIN,
        ),
        'RuntimeWorkItemRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'HandoffRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'EvidenceObjectBytes': (
            RetentionClassification.DELETE,
        ),
        'EvidenceRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.TOMBSTONE,
        ),
        'ExternalTaskRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'IdempotencyRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'AuditEventEnvelope': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'RetentionOperation': (
            RetentionClassification.RETAIN,
        ),
    }
)


class RetentionHoldRecord(ContractModel):
    """Source-linked authority that blocks destructive retention work."""

    hold_id: str = Field(min_length=1, max_length=160)
    claim_id: str = Field(min_length=1, max_length=160)
    reason: RetentionHoldReason
    authority_ref: str = Field(min_length=1, max_length=240)
    source_refs: list[str] = Field(min_length=1, max_length=30)
    applied_at: datetime
    released_at: datetime | None = None

    @model_validator(mode='after')
    def validate_hold(self) -> RetentionHoldRecord:
        if self.applied_at.utcoffset() is None:
            raise ValueError('Retention hold applied_at must be timezone-aware.')

        if self.released_at is not None:
            if self.released_at.utcoffset() is None:
                raise ValueError(
                    'Retention hold released_at must be timezone-aware.'
                )
            if self.released_at < self.applied_at:
                raise ValueError(
                    'Retention hold cannot be released before it is applied.'
                )

        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError(
                'Retention hold source references must be unique.'
            )

        return self

    @property
    def active(self) -> bool:
        return self.released_at is None


class RetentionCleanupTarget(ContractModel):
    """One frozen cleanup target selected before destructive execution."""

    target_id: str = Field(min_length=1, max_length=200)
    kind: RetentionTargetKind
    record_type: str = Field(min_length=1, max_length=120)
    record_id: str = Field(min_length=1, max_length=240)
    classification: RetentionClassification
    storage_key: str | None = Field(default=None, max_length=1000)
    source_refs: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode='after')
    def validate_target(self) -> RetentionCleanupTarget:
        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError(
                'Retention cleanup target source references must be unique.'
            )

        if self.kind is RetentionTargetKind.OBJECT_BYTES:
            if self.classification is not RetentionClassification.DELETE:
                raise ValueError(
                    'Object-byte retention targets must use DELETE.'
                )
            if self.storage_key is None:
                raise ValueError(
                    'Object-byte retention targets require a storage key.'
                )
        elif self.storage_key is not None:
            raise ValueError(
                'Only object-byte targets may carry a storage key.'
            )

        if (
            self.kind is RetentionTargetKind.TOMBSTONE
            and self.classification is not RetentionClassification.TOMBSTONE
        ):
            raise ValueError(
                'Tombstone targets must use TOMBSTONE classification.'
            )

        return self


class RetentionStepEvidence(ContractModel):
    """Immutable evidence for one execution attempt against one target."""

    evidence_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    attempt: int = Field(ge=1)
    status: RetentionStepStatus
    object_outcome: ObjectDeletionOutcome | None = None
    diagnostic_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )
    source_refs: list[str] = Field(default_factory=list, max_length=30)
    recorded_at: datetime

    @model_validator(mode='after')
    def validate_step_evidence(self) -> RetentionStepEvidence:
        if self.recorded_at.utcoffset() is None:
            raise ValueError(
                'Retention step evidence time must be timezone-aware.'
            )

        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError(
                'Retention step source references must be unique.'
            )

        if self.object_outcome is not None:
            expected = {
                ObjectDeletionOutcome.DELETED:
                    RetentionStepStatus.SATISFIED,
                ObjectDeletionOutcome.ALREADY_ABSENT:
                    RetentionStepStatus.SATISFIED,
                ObjectDeletionOutcome.FAILED:
                    RetentionStepStatus.FAILED,
                ObjectDeletionOutcome.UNKNOWN:
                    RetentionStepStatus.UNKNOWN,
            }[self.object_outcome]

            if self.status is not expected:
                raise ValueError(
                    'Object deletion outcome and retention step status disagree.'
                )

        if self.status in {
            RetentionStepStatus.FAILED,
            RetentionStepStatus.UNKNOWN,
        } and self.diagnostic_code is None:
            raise ValueError(
                'Failed or unknown retention evidence requires a safe '
                'diagnostic code.'
            )

        return self


class RetentionOperation(ContractModel):
    """Durable authority for one logical destructive cleanup execution."""

    operation_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=160)

    # Reference to the existing Claim terminal/recovery authority.  Retention
    # consumes this fact; it does not replace it.
    source_terminal_ref: str = Field(min_length=1, max_length=240)
    source_claim_revision: int = Field(ge=1)

    policy_id: str = Field(min_length=1, max_length=120)
    policy_version: str = Field(min_length=1, max_length=80)

    # CAS coordinate for the RetentionOperation itself.
    revision: int = Field(default=1, ge=1)

    status: RetentionOperationStatus

    # Once this is committed, claimant resource access remains closed even when
    # a hold pauses destructive cleanup or cleanup requires reconciliation.
    access_closed_at: datetime

    targets_frozen_at: datetime | None = None
    targets: list[RetentionCleanupTarget] = Field(
        default_factory=list,
        max_length=500,
    )
    step_evidence: list[RetentionStepEvidence] = Field(
        default_factory=list,
        max_length=2000,
    )

    hold_refs: list[str] = Field(default_factory=list, max_length=50)
    diagnostic_code: str | None = Field(
        default=None,
        min_length=1,
        max_length=160,
    )

    source_refs: list[str] = Field(min_length=1, max_length=50)

    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    @model_validator(mode='after')
    def validate_operation(self) -> RetentionOperation:
        for name, value in (
            ('access_closed_at', self.access_closed_at),
            ('created_at', self.created_at),
            ('updated_at', self.updated_at),
        ):
            if value.utcoffset() is None:
                raise ValueError(
                    f'Retention operation {name} must be timezone-aware.'
                )

        if self.updated_at < self.created_at:
            raise ValueError(
                'Retention operation updated_at cannot precede created_at.'
            )

        if self.access_closed_at < self.created_at:
            raise ValueError(
                'Resource-access closure cannot precede operation creation.'
            )

        if self.targets_frozen_at is not None:
            if self.targets_frozen_at.utcoffset() is None:
                raise ValueError(
                    'Retention target freeze time must be timezone-aware.'
                )
            if self.targets_frozen_at < self.created_at:
                raise ValueError(
                    'Retention targets cannot be frozen before creation.'
                )

        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError(
                'Retention operation source references must be unique.'
            )

        if len(self.hold_refs) != len(set(self.hold_refs)):
            raise ValueError(
                'Retention operation hold references must be unique.'
            )

        target_ids = [target.target_id for target in self.targets]

        if len(target_ids) != len(set(target_ids)):
            raise ValueError(
                'Retention cleanup target identities must be unique.'
            )

        target_id_set = set(target_ids)
        evidence_keys: set[tuple[str, int]] = set()
        evidence_ids: set[str] = set()

        for evidence in self.step_evidence:
            if evidence.target_id not in target_id_set:
                raise ValueError(
                    'Retention step evidence references an unknown target.'
                )

            if evidence.evidence_id in evidence_ids:
                raise ValueError(
                    'Retention step evidence identities must be unique.'
                )

            evidence_ids.add(evidence.evidence_id)

            key = (evidence.target_id, evidence.attempt)

            if key in evidence_keys:
                raise ValueError(
                    'A retention target attempt may have only one evidence '
                    'record.'
                )

            evidence_keys.add(key)

        current = retention_target_statuses(
            self.targets,
            self.step_evidence,
        )

        all_satisfied = (
            bool(self.targets)
            and self.targets_frozen_at is not None
            and all(
                status is RetentionStepStatus.SATISFIED
                for status in current.values()
            )
        )

        needs_reconciliation = any(
            status in {
                RetentionStepStatus.FAILED,
                RetentionStepStatus.UNKNOWN,
            }
            for status in current.values()
        )

        if self.status is RetentionOperationStatus.COMPLETED:
            if not all_satisfied:
                raise ValueError(
                    'Retention cannot complete until every frozen target is '
                    'satisfied.'
                )
            if self.completed_at is None:
                raise ValueError(
                    'Completed retention requires completed_at.'
                )
        elif self.completed_at is not None:
            raise ValueError(
                'Only completed retention may carry completed_at.'
            )

        if self.completed_at is not None:
            if self.completed_at.utcoffset() is None:
                raise ValueError(
                    'Retention completed_at must be timezone-aware.'
                )
            if self.completed_at < self.created_at:
                raise ValueError(
                    'Retention cannot complete before creation.'
                )

        if (
            self.status
            is RetentionOperationStatus.RECONCILIATION_REQUIRED
            and not needs_reconciliation
        ):
            raise ValueError(
                'Reconciliation-required retention needs failed or unknown '
                'current step evidence.'
            )

        if (
            needs_reconciliation
            and self.status is RetentionOperationStatus.COMPLETED
        ):
            raise ValueError(
                'Failed or unknown cleanup cannot be reported as completed.'
            )

        return self


def retention_target_statuses(
    targets: Sequence[RetentionCleanupTarget],
    evidence: Sequence[RetentionStepEvidence],
) -> dict[str, RetentionStepStatus]:
    """Return each target's current status from its latest immutable attempt."""

    current = {
        target.target_id: RetentionStepStatus.PENDING
        for target in targets
    }
    latest_attempt = {
        target.target_id: 0
        for target in targets
    }

    for item in evidence:
        if item.target_id not in current:
            continue

        if item.attempt > latest_attempt[item.target_id]:
            latest_attempt[item.target_id] = item.attempt
            current[item.target_id] = item.status

    return current


def retention_next_status(
    operation: RetentionOperation,
    *,
    active_hold: bool,
) -> RetentionOperationStatus:
    """Purely derive the next retention execution status."""

    if operation.status is RetentionOperationStatus.COMPLETED:
        return RetentionOperationStatus.COMPLETED

    if active_hold:
        return RetentionOperationStatus.HELD

    current = retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    )

    if any(
        status in {
            RetentionStepStatus.FAILED,
            RetentionStepStatus.UNKNOWN,
        }
        for status in current.values()
    ):
        return RetentionOperationStatus.RECONCILIATION_REQUIRED

    if (
        operation.targets_frozen_at is not None
        and operation.targets
        and all(
            status is RetentionStepStatus.SATISFIED
            for status in current.values()
        )
    ):
        return RetentionOperationStatus.COMPLETED

    return RetentionOperationStatus.RESERVED


def retention_access_closed(
    operation: RetentionOperation | None,
) -> bool:
    """Access closure is monotonic once a retention operation is reserved."""

    return operation is not None and operation.access_closed_at is not None



def validate_retention_operation_transition(
    current: RetentionOperation,
    candidate: RetentionOperation,
) -> None:
    """Validate one CAS-backed append-only retention transition."""

    immutable_equal = (
        current.operation_id == candidate.operation_id
        and current.claim_id == candidate.claim_id
        and current.source_terminal_ref == candidate.source_terminal_ref
        and current.source_claim_revision == candidate.source_claim_revision
        and current.policy_id == candidate.policy_id
        and current.policy_version == candidate.policy_version
        and current.access_closed_at == candidate.access_closed_at
        and current.source_refs == candidate.source_refs
        and current.created_at == candidate.created_at
    )

    if not immutable_equal:
        raise ValueError(
            'Retention operation immutable coordinates cannot change.'
        )

    if current.status is RetentionOperationStatus.COMPLETED:
        raise ValueError(
            'Completed retention operations are immutable.'
        )

    if candidate.revision != current.revision + 1:
        raise ValueError(
            'Retention operation revision must advance exactly once.'
        )

    if current.targets_frozen_at is not None:
        if (
            candidate.targets_frozen_at != current.targets_frozen_at
            or candidate.targets != current.targets
        ):
            raise ValueError(
                'Frozen retention cleanup targets cannot change.'
            )
    elif candidate.targets_frozen_at is None and candidate.targets:
        raise ValueError(
            'Retention targets cannot exist before their freeze coordinate.'
        )

    current_evidence = current.step_evidence

    if (
        len(candidate.step_evidence) < len(current_evidence)
        or candidate.step_evidence[: len(current_evidence)]
        != current_evidence
    ):
        raise ValueError(
            'Retention step evidence is append-only.'
        )

    if not set(current.hold_refs).issubset(candidate.hold_refs):
        raise ValueError(
            'Retention hold references are append-only.'
        )


def validate_retention_hold_transition(
    current: RetentionHoldRecord,
    candidate: RetentionHoldRecord,
) -> None:
    """Allow only an idempotent hold replay or one monotonic release."""

    if current == candidate:
        return

    if (
        current.hold_id != candidate.hold_id
        or current.claim_id != candidate.claim_id
        or current.reason != candidate.reason
        or current.authority_ref != candidate.authority_ref
        or current.source_refs != candidate.source_refs
        or current.applied_at != candidate.applied_at
    ):
        raise ValueError(
            'Retention hold authority coordinates cannot change.'
        )

    if current.released_at is not None:
        raise ValueError(
            'A released retention hold is immutable.'
        )

    if candidate.released_at is None:
        raise ValueError(
            'The only permitted retention hold transition is release.'
        )



class RetentionEligibilityReason(str, Enum):
    CLAIM_NOT_FOUND = 'claim_not_found'
    TERMINAL_REQUIRED = 'terminal_required'
    TERMINAL_NOT_ELIGIBLE = 'terminal_not_eligible'
    SOURCE_REVISION_MISMATCH = 'source_revision_mismatch'
    SOURCE_TERMINAL_MISMATCH = 'source_terminal_mismatch'
    RETENTION_POLICY_MISMATCH = 'retention_policy_mismatch'
    INVALID_OPERATION_SHAPE = 'invalid_operation_shape'
    RECOVERY_OPERATION_OPEN = 'recovery_operation_open'
    EXTERNAL_OUTCOME_UNKNOWN = 'external_outcome_unknown'
    STAFF_RESPONSIBILITY_OPEN = 'staff_responsibility_open'


class RetentionEligibilityRejected(ValueError):
    """Typed fail-closed rejection before retention access closure is committed."""

    def __init__(
        self,
        reason: RetentionEligibilityReason,
        claim_id: str,
    ) -> None:
        self.reason = reason
        self.claim_id = claim_id
        super().__init__(
            f'Retention eligibility rejected for {claim_id}: {reason.value}'
        )


def retention_terminal_source_ref(
    claim_id: str,
    recorded_revision: int,
) -> str:
    """Return the stable reference to the existing Claim terminal authority."""

    return (
        f'claim-terminal:{claim_id}:'
        f'revision:{recorded_revision}'
    )


def validate_retention_source_authority(
    claim: WorkingClaim,
    operation: RetentionOperation,
) -> None:
    """Revalidate the immutable Claim terminal source used by retention."""

    if claim.claim_id != operation.claim_id:
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.SOURCE_TERMINAL_MISMATCH,
            operation.claim_id,
        )

    terminal = claim.terminal_disposition

    if terminal is None:
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.TERMINAL_REQUIRED,
            claim.claim_id,
        )

    eligible_reasons = {
        TerminalDispositionReasonCode.RECOVERY_EXPIRED,
        TerminalDispositionReasonCode.AUTHORISED_STAFF_ABANDONMENT,
        TerminalDispositionReasonCode.AUTHORISED_CLOSURE,
    }

    if (
        terminal.reason_code not in eligible_reasons
        or terminal.value
        not in {
            TerminalDispositionValue.ABANDONED,
            TerminalDispositionValue.CLOSED,
        }
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.TERMINAL_NOT_ELIGIBLE,
            claim.claim_id,
        )

    if (
        operation.source_claim_revision != claim.revision
        or terminal.recorded_revision != claim.revision
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.SOURCE_REVISION_MISMATCH,
            claim.claim_id,
        )

    expected_terminal_ref = retention_terminal_source_ref(
        claim.claim_id,
        terminal.recorded_revision,
    )

    if (
        operation.source_terminal_ref != expected_terminal_ref
        or expected_terminal_ref not in operation.source_refs
        or not set(terminal.source_refs).issubset(
            operation.source_refs
        )
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.SOURCE_TERMINAL_MISMATCH,
            claim.claim_id,
        )

    if (
        operation.policy_id
        != INCOMPLETE_CLAIM_RETENTION_POLICY_ID
        or operation.policy_version
        != INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.RETENTION_POLICY_MISMATCH,
            claim.claim_id,
        )


def validate_retention_eligibility_source(
    claim: WorkingClaim,
    operation: RetentionOperation,
) -> None:
    """Validate the source plus the initial pre-reservation operation shape."""

    validate_retention_source_authority(
        claim,
        operation,
    )

    if (
        operation.revision != 1
        or operation.status
        is not RetentionOperationStatus.RESERVED
        or operation.targets_frozen_at is not None
        or operation.targets
        or operation.step_evidence
        or operation.completed_at is not None
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.INVALID_OPERATION_SHAPE,
            claim.claim_id,
        )



class RetentionTargetFreezeReason(str, Enum):
    OPERATION_NOT_FOUND = 'operation_not_found'
    INVALID_OPERATION_SHAPE = 'invalid_operation_shape'
    ACTIVE_HOLD = 'active_hold'
    RECOVERY_OPERATION_OPEN = 'recovery_operation_open'
    EXTERNAL_OUTCOME_UNKNOWN = 'external_outcome_unknown'
    STAFF_RESPONSIBILITY_OPEN = 'staff_responsibility_open'
    INVALID_RECORD_IDENTITY = 'invalid_record_identity'
    INVALID_STORAGE_REFERENCE = 'invalid_storage_reference'
    TARGET_LIMIT_EXCEEDED = 'target_limit_exceeded'


class RetentionTargetFreezeRejected(ValueError):
    """Fail-closed target-selection rejection before destructive work."""

    def __init__(
        self,
        reason: RetentionTargetFreezeReason,
        claim_id: str,
    ) -> None:
        self.reason = reason
        self.claim_id = claim_id
        super().__init__(
            f'Retention target freeze rejected for '
            f'{claim_id}: {reason.value}'
        )


# Storage-level selection for the approved prototype retention baseline.
#
# ANONYMISE means preserve only the minimum schema-valid/business-authority
# projection selected by the destructive executor.
# RETAIN means no destructive mutation is required, but the record is frozen
# into the operation so completion proves it was deliberately preserved.
# DELETE means the record itself is selected for deletion.
#
# RetentionOperation itself is deliberately absent: it is the execution
# authority carrying this target set and must not target itself.
RETENTION_STORAGE_TARGETS: Mapping[
    str,
    tuple[str, RetentionClassification],
] = MappingProxyType(
    {
        'claim': (
            'WorkingClaim',
            RetentionClassification.ANONYMISE,
        ),
        'session': (
            'SessionRecord',
            RetentionClassification.ANONYMISE,
        ),
        'message': (
            'MessageRecord',
            RetentionClassification.DELETE,
        ),
        'follow_up': (
            'FollowUpRecord',
            RetentionClassification.ANONYMISE,
        ),
        'follow_up_operation': (
            'FollowUpOperation',
            RetentionClassification.RETAIN,
        ),
        'runtime_work_item': (
            'RuntimeWorkItemRecord',
            RetentionClassification.RETAIN,
        ),
        'handoff': (
            'HandoffRecord',
            RetentionClassification.ANONYMISE,
        ),
        'evidence': (
            'EvidenceRecord',
            RetentionClassification.ANONYMISE,
        ),
        'evidence_claim_link': (
            'EvidenceClaimLink',
            RetentionClassification.ANONYMISE,
        ),
        'external_task': (
            'ExternalTaskRecord',
            RetentionClassification.ANONYMISE,
        ),
        'external_task_request': (
            'ExternalTaskRequest',
            RetentionClassification.ANONYMISE,
        ),
        'external_task_attempt': (
            'ExternalTaskAttempt',
            RetentionClassification.RETAIN,
        ),
        'external_task_result': (
            'ExternalTaskResult',
            RetentionClassification.ANONYMISE,
        ),
        'external_task_evidence_link': (
            'ExternalTaskEvidenceLink',
            RetentionClassification.RETAIN,
        ),
        'idempotency': (
            'IdempotencyRecord',
            RetentionClassification.ANONYMISE,
        ),
        'audit_event': (
            'AuditEventEnvelope',
            RetentionClassification.RETAIN,
        ),
        'retention_hold': (
            'RetentionHoldRecord',
            RetentionClassification.RETAIN,
        ),
    }
)


def retention_record_identity(
    prefix: str,
    *parts: str,
) -> str:
    """Return a bounded deterministic identity for composite storage records."""

    material = '|'.join((prefix, *parts))
    return (
        f'{prefix}_'
        + sha256(material.encode()).hexdigest()[:32]
    )


def build_retention_cleanup_target(
    *,
    operation: RetentionOperation,
    record_type: str,
    record_id: str,
    classification: RetentionClassification,
    kind: RetentionTargetKind = RetentionTargetKind.MONGO_RECORD,
    storage_key: str | None = None,
    source_refs: Sequence[str] = (),
) -> RetentionCleanupTarget:
    """Build one stable frozen target without reading mutable state."""

    identity_material = '|'.join(
        (
            operation.operation_id,
            kind.value,
            record_type,
            record_id,
            classification.value,
        )
    )

    refs = list(
        dict.fromkeys(
            [
                operation.source_terminal_ref,
                *source_refs,
            ]
        )
    )

    return RetentionCleanupTarget(
        target_id=(
            'rtg_'
            + sha256(
                identity_material.encode()
            ).hexdigest()[:32]
        ),
        kind=kind,
        record_type=record_type,
        record_id=record_id,
        classification=classification,
        storage_key=storage_key,
        source_refs=refs,
    )



RETENTION_TARGET_STORAGE_TYPE: Mapping[str, str] = MappingProxyType(
    {
        logical_type: storage_type
        for storage_type, (
            logical_type,
            _classification,
        ) in RETENTION_STORAGE_TARGETS.items()
    }
)


RETENTION_TOMBSTONE_AUTHORITY_FIELDS: Mapping[
    str,
    tuple[str, ...],
] = MappingProxyType(
    {
        'WorkingClaim': (
            'revision',
        ),
        'SessionRecord': (
            'status',
            'context_revision',
        ),
        'FollowUpRecord': (
            'policy_id',
            'policy_version',
            'status',
            'reason_code',
            'attempt_count',
        ),
        'HandoffRecord': (
            'type',
            'status',
            'priority',
            'applied_rule',
        ),
        'EvidenceRecord': (
            'kind',
            'status',
            'file_status',
            'source',
            'material_version',
        ),
        'EvidenceClaimLink': (
            'state',
        ),
        'ExternalTaskRecord': (
            'service_identity',
            'requested_action',
            'integration_source',
            'status',
            'delivery',
            'failure_code',
        ),
        'ExternalTaskRequest': (
            'task_id',
            'operation_id',
            'status',
        ),
        'ExternalTaskResult': (
            'task_id',
            'verification',
        ),
    }
)


class RetentionRecordTombstone(ContractModel):
    """Minimum durable proof that one selected record was anonymised/tombstoned."""

    tombstone_id: str = Field(min_length=1, max_length=200)
    operation_id: str = Field(min_length=1, max_length=200)
    target_id: str = Field(min_length=1, max_length=200)
    claim_id: str = Field(min_length=1, max_length=160)

    source_record_type: str = Field(min_length=1, max_length=120)
    source_record_id: str = Field(min_length=1, max_length=240)

    classification: RetentionClassification

    authority: dict[
        str,
        str | int | bool | None,
    ] = Field(default_factory=dict, max_length=30)

    source_refs: list[str] = Field(
        default_factory=list,
        max_length=30,
    )

    created_at: datetime

    @model_validator(mode='after')
    def validate_tombstone(
        self,
    ) -> RetentionRecordTombstone:
        if self.classification not in {
            RetentionClassification.ANONYMISE,
            RetentionClassification.TOMBSTONE,
        }:
            raise ValueError(
                'Retention record tombstones require anonymise/tombstone classification.'
            )

        if self.created_at.utcoffset() is None:
            raise ValueError(
                'Retention tombstone time must be timezone-aware.'
            )

        if len(self.source_refs) != len(
            set(self.source_refs)
        ):
            raise ValueError(
                'Retention tombstone source references must be unique.'
            )

        return self


def retention_tombstone_authority(
    record_type: str,
    payload: Mapping[str, Any],
) -> dict[str, str | int | bool | None]:
    """Select only approved scalar authority fields from a destroyed record."""

    selected: dict[
        str,
        str | int | bool | None,
    ] = {}

    for field_name in RETENTION_TOMBSTONE_AUTHORITY_FIELDS.get(
        record_type,
        (),
    ):
        value = payload.get(field_name)

        if isinstance(
            value,
            str | int | bool,
        ) or value is None:
            selected[field_name] = value

    return selected


def retention_next_attempt(
    operation: RetentionOperation,
    target_id: str,
) -> int:
    return (
        max(
            (
                evidence.attempt
                for evidence in operation.step_evidence
                if evidence.target_id == target_id
            ),
            default=0,
        )
        + 1
    )


def retention_step_evidence_id(
    operation_id: str,
    target_id: str,
    attempt: int,
) -> str:
    material = (
        f'{operation_id}|{target_id}|{attempt}'
    )

    return (
        'rse_'
        + sha256(
            material.encode()
        ).hexdigest()[:32]
    )


def retention_candidate_after_step(
    operation: RetentionOperation,
    evidence: RetentionStepEvidence,
    *,
    now: datetime,
) -> RetentionOperation:
    """Append one immutable step result and derive the bounded operation state."""

    evidence_set = [
        *operation.step_evidence,
        evidence,
    ]

    statuses = retention_target_statuses(
        operation.targets,
        evidence_set,
    )

    if evidence.status in {
        RetentionStepStatus.FAILED,
        RetentionStepStatus.UNKNOWN,
    }:
        status = (
            RetentionOperationStatus.RECONCILIATION_REQUIRED
        )
        completed_at = None
    elif (
        operation.targets_frozen_at is not None
        and operation.targets
        and all(
            value is RetentionStepStatus.SATISFIED
            for value in statuses.values()
        )
    ):
        status = RetentionOperationStatus.COMPLETED
        completed_at = now
    else:
        status = RetentionOperationStatus.RESERVED
        completed_at = None

    payload = operation.model_dump(
        mode='python'
    )

    payload.update(
        {
            'revision': operation.revision + 1,
            'status': status,
            'step_evidence': evidence_set,
            'updated_at': now,
            'completed_at': completed_at,
        }
    )

    return RetentionOperation.model_validate(
        payload
    )



class RetentionDatabaseStepError(RuntimeError):
    """Repository-level destructive step failure with bounded commit certainty."""

    def __init__(
        self,
        target_id: str,
        *,
        commit_unknown: bool,
        diagnostic_code: str,
    ) -> None:
        if not target_id:
            raise ValueError(
                'Retention database failure requires a target identity.'
            )

        if (
            not diagnostic_code
            or len(diagnostic_code) > 160
        ):
            raise ValueError(
                'Retention database failure diagnostic must be bounded.'
            )

        self.target_id = target_id
        self.commit_unknown = commit_unknown
        self.diagnostic_code = diagnostic_code

        super().__init__(
            f'Retention database step failed for {target_id}.'
        )



class RetentionProjectedContentState(str, Enum):
    """Role-safe content outcome; never exposes physical cleanup coordinates."""

    UNAVAILABLE = 'unavailable'
    ANONYMISED = 'anonymised'
    RETAINED_FOR_AUDIT = 'retained_for_audit'
    DELETED = 'deleted'


class StaffRetentionResourceSummary(ContractModel):
    """Aggregate staff projection; deliberately omits record/storage identities."""

    record_type: str = Field(min_length=1, max_length=120)
    content_state: RetentionProjectedContentState
    count: int = Field(ge=1)


class StaffRetentionProjection(ContractModel):
    """Safe Workbench view over durable retention authority."""

    claim_id: str = Field(min_length=1, max_length=160)
    operation_status: RetentionOperationStatus
    access_closed_at: datetime
    completed_at: datetime | None = None
    hold_active: bool
    reconciliation_required: bool
    resources: list[StaffRetentionResourceSummary] = Field(
        default_factory=list,
        max_length=200,
    )


class ClaimantRetentionProjection(ContractModel):
    """Minimal claimant projection for an already closed retention boundary."""

    availability: RetentionProjectedContentState = (
        RetentionProjectedContentState.UNAVAILABLE
    )
    message: str = (
        'This claim is no longer available.'
    )
