"""Authoritative P17 retention execution contracts.

Retention owns destructive cleanup execution only.  It does not own Claim
terminal state, recovery expiry, Session business state, ExternalTask result,
or authentication state.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Any

from pydantic import Field, model_validator

from backend.domain.ids import stable_record_id
from backend.domain.models import (
    ContractModel,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.domain.models import (
    ObjectDeletionOutcome as ObjectDeletionOutcome,
)
from backend.domain.models import (
    RetentionClassification as RetentionClassification,
)
from backend.domain.models import (
    RetentionCleanupTarget as RetentionCleanupTarget,
)
from backend.domain.models import (
    RetentionDeleteAuthorization as RetentionDeleteAuthorization,
)
from backend.domain.models import (
    RetentionHoldReason as RetentionHoldReason,
)
from backend.domain.models import (
    RetentionHoldRecord as RetentionHoldRecord,
)
from backend.domain.models import (
    RetentionOperation as RetentionOperation,
)
from backend.domain.models import (
    RetentionOperationStatus as RetentionOperationStatus,
)
from backend.domain.models import (
    RetentionStepEvidence as RetentionStepEvidence,
)
from backend.domain.models import (
    RetentionStepStatus as RetentionStepStatus,
)
from backend.domain.models import (
    RetentionTargetKind as RetentionTargetKind,
)
from backend.domain.models import (
    retention_target_statuses as retention_target_statuses,
)
from backend.domain.recovery import reduce_owned_recovery
from backend.domain.recovery_policy_registry import RecoveryTrigger

INCOMPLETE_CLAIM_RETENTION_POLICY_ID = 'incomplete_claim_retention'
INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION = 1


class ResourceAccessClosed(KeyError):
    """A retained resource still exists internally but claimant access is closed.

    This internal signal must always be projected using the same concealed-
    absence contract as a resource that does not exist.
    """

    def __init__(self, claim_id: str) -> None:
        super().__init__(claim_id)
        self.claim_id = claim_id


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
        'FollowUpOperation': (RetentionClassification.RETAIN,),
        'RuntimeWorkItemRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'HandoffRecord': (
            RetentionClassification.ANONYMISE,
            RetentionClassification.RETAIN,
        ),
        'EvidenceObjectBytes': (RetentionClassification.DELETE,),
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
        'RetentionOperation': (RetentionClassification.RETAIN,),
    }
)


def retention_next_status(
    operation: RetentionOperation,
    *,
    active_hold: bool,
) -> RetentionOperationStatus:
    """Purely derive the next retention execution status."""

    if operation.status is RetentionOperationStatus.COMPLETED:
        return RetentionOperationStatus.COMPLETED

    if active_hold:
        plan = reduce_owned_recovery(
            RecoveryTrigger(source='retention', outcome_code='hold'),
            operation.claim_id,
            operation.source_claim_revision,
            operation.operation_id,
            operation.updated_at,
            operation.source_refs,
            operation.operation_id,
        )
        if plan.decision_code != 'retention_hold':
            raise ValueError('Published policy does not permit retention hold.')
        return RetentionOperationStatus.HELD

    current = retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    )

    if any(
        status
        in {
            RetentionStepStatus.FAILED,
            RetentionStepStatus.UNKNOWN,
        }
        for status in current.values()
    ):
        plan = reduce_owned_recovery(
            RecoveryTrigger(source='retention', outcome_code='unknown'),
            operation.claim_id,
            operation.source_claim_revision,
            operation.operation_id,
            operation.updated_at,
            operation.source_refs,
            operation.operation_id,
        )
        if plan.decision_code != 'retention_reconcile':
            raise ValueError('Published policy does not permit retention reconciliation.')
        return RetentionOperationStatus.RECONCILIATION_REQUIRED

    if (
        operation.targets_frozen_at is not None
        and operation.targets
        and all(status is RetentionStepStatus.SATISFIED for status in current.values())
    ):
        return RetentionOperationStatus.COMPLETED

    return RetentionOperationStatus.RESERVED


def retention_access_closed(
    operation: RetentionOperation | None,
) -> bool:
    """Access closure is monotonic once a retention operation is reserved."""

    if operation is None or operation.access_closed_at is None:
        return False
    plan = reduce_owned_recovery(
        RecoveryTrigger(source='retention', outcome_code='old_session_denied'),
        operation.claim_id,
        operation.source_claim_revision,
        operation.operation_id,
        operation.updated_at,
        operation.source_refs,
        operation.operation_id,
    )
    return plan.decision_code == 'deny_access'


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
        raise ValueError('Retention operation immutable coordinates cannot change.')

    if current.status is RetentionOperationStatus.COMPLETED:
        raise ValueError('Completed retention operations are immutable.')

    if candidate.revision != current.revision + 1:
        raise ValueError('Retention operation revision must advance exactly once.')

    if current.targets_frozen_at is not None:
        if (
            candidate.targets_frozen_at != current.targets_frozen_at
            or candidate.targets != current.targets
        ):
            raise ValueError('Frozen retention cleanup targets cannot change.')
    elif candidate.targets_frozen_at is None and candidate.targets:
        raise ValueError('Retention targets cannot exist before their freeze coordinate.')

    current_evidence = current.step_evidence

    if (
        len(candidate.step_evidence) < len(current_evidence)
        or candidate.step_evidence[: len(current_evidence)] != current_evidence
    ):
        raise ValueError('Retention step evidence is append-only.')

    if not set(current.hold_refs).issubset(candidate.hold_refs):
        raise ValueError('Retention hold references are append-only.')

    current_authorizations = current.delete_authorizations
    if (
        len(candidate.delete_authorizations) < len(current_authorizations)
        or candidate.delete_authorizations[: len(current_authorizations)] != current_authorizations
    ):
        raise ValueError('Retention delete authorizations are append-only.')

    current_active = current.active_delete_authorization_id
    candidate_active = candidate.active_delete_authorization_id
    if current_active is None and candidate_active is not None:
        newly_authorized = candidate.delete_authorizations[len(current_authorizations) :]
        if len(newly_authorized) != 1 or newly_authorized[0].authorization_id != candidate_active:
            raise ValueError('Active delete authorization must be the newly appended fence.')
        if candidate.step_evidence != current.step_evidence:
            raise ValueError('Delete authorization cannot also settle a retention step.')
    elif current_active is not None and candidate_active not in {current_active, None}:
        raise ValueError('An active delete authorization cannot be replaced.')
    elif current_active is not None and candidate_active is None:
        if not any(
            evidence.authorization_id == current_active
            for evidence in candidate.step_evidence[len(current.step_evidence) :]
        ):
            raise ValueError('Clearing delete authorization requires its durable result evidence.')


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
        raise ValueError('Retention hold authority coordinates cannot change.')

    if current.released_at is not None:
        raise ValueError('A released retention hold is immutable.')

    if candidate.released_at is None:
        raise ValueError('The only permitted retention hold transition is release.')


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
        super().__init__(f'Retention eligibility rejected for {claim_id}: {reason.value}')


def retention_terminal_source_ref(
    claim_id: str,
    recorded_revision: int,
) -> str:
    """Return the stable reference to the existing Claim terminal authority."""

    return f'claim-terminal:{claim_id}:revision:{recorded_revision}'


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

    if terminal.reason_code not in eligible_reasons or terminal.value not in {
        TerminalDispositionValue.ABANDONED,
        TerminalDispositionValue.CLOSED,
    }:
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
        or not set(terminal.source_refs).issubset(operation.source_refs)
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.SOURCE_TERMINAL_MISMATCH,
            claim.claim_id,
        )

    if (
        operation.policy_id != INCOMPLETE_CLAIM_RETENTION_POLICY_ID
        or operation.policy_version != INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION
    ):
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.RETENTION_POLICY_MISMATCH,
            claim.claim_id,
        )

    policy_plan = reduce_owned_recovery(
        RecoveryTrigger(source='retention', outcome_code='eligible'),
        claim.claim_id,
        claim.revision,
        operation.operation_id,
        operation.updated_at,
        operation.source_refs,
        operation.operation_id,
    )
    if policy_plan.decision_code != 'retention_eligible':
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
        or operation.status is not RetentionOperationStatus.RESERVED
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
        super().__init__(f'Retention target freeze rejected for {claim_id}: {reason.value}')


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

    return stable_record_id(prefix, '|'.join((prefix, *parts)))


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
        target_id=stable_record_id('rtg', identity_material),
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
        'WorkingClaim': ('revision',),
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
        'EvidenceClaimLink': ('state',),
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
            raise ValueError('Retention tombstone time must be timezone-aware.')

        if len(self.source_refs) != len(set(self.source_refs)):
            raise ValueError('Retention tombstone source references must be unique.')

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

        if (
            isinstance(
                value,
                str | int | bool,
            )
            or value is None
        ):
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


def retention_tombstone_id(target_id: str) -> str:
    """Return the tombstone identity that shares its cleanup target's digest.

    Args:
        target_id: A frozen ``rtg_`` cleanup target identity.

    Returns:
        The ``rts_`` identity for that target's minimum retained evidence.

    Raises:
        ValueError: If ``target_id`` is not a cleanup target identity.
    """
    if not target_id.startswith('rtg_'):
        raise ValueError('A retention tombstone derives only from an rtg_ cleanup target.')
    return 'rts_' + target_id.removeprefix('rtg_')


def retention_step_evidence_id(
    operation_id: str,
    target_id: str,
    attempt: int,
) -> str:
    return stable_record_id('rse', f'{operation_id}|{target_id}|{attempt}')


def retention_delete_authorization_id(
    operation_id: str,
    target_id: str,
    attempt: int,
) -> str:
    return stable_record_id('rda', f'{operation_id}|{target_id}|{attempt}|delete-authorization')


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
        status = RetentionOperationStatus.RECONCILIATION_REQUIRED
        completed_at = None
    elif (
        operation.targets_frozen_at is not None
        and operation.targets
        and all(value is RetentionStepStatus.SATISFIED for value in statuses.values())
    ):
        status = RetentionOperationStatus.COMPLETED
        completed_at = now
    else:
        status = RetentionOperationStatus.RESERVED
        completed_at = None

    payload = operation.model_dump(mode='python')

    payload.update(
        {
            'revision': operation.revision + 1,
            'status': status,
            'step_evidence': evidence_set,
            'updated_at': now,
            'completed_at': completed_at,
        }
    )

    return RetentionOperation.model_validate(payload)


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
            raise ValueError('Retention database failure requires a target identity.')

        if not diagnostic_code or len(diagnostic_code) > 160:
            raise ValueError('Retention database failure diagnostic must be bounded.')

        self.target_id = target_id
        self.commit_unknown = commit_unknown
        self.diagnostic_code = diagnostic_code

        super().__init__(f'Retention database step failed for {target_id}.')


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

    availability: RetentionProjectedContentState = RetentionProjectedContentState.UNAVAILABLE
    message: str = 'This claim is no longer available.'
