from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from backend.domain.retention import (
    INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
    INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
    RETENTION_CLASSIFICATION_BASELINE,
    ObjectDeletionOutcome,
    RetentionClassification,
    RetentionCleanupTarget,
    RetentionHoldReason,
    RetentionHoldRecord,
    RetentionOperation,
    RetentionOperationStatus,
    RetentionStepEvidence,
    RetentionStepStatus,
    RetentionTargetKind,
    retention_access_closed,
    retention_next_status,
    retention_target_statuses,
)

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def _object_target() -> RetentionCleanupTarget:
    return RetentionCleanupTarget(
        target_id='target-object-1',
        kind=RetentionTargetKind.OBJECT_BYTES,
        record_type='EvidenceObjectBytes',
        record_id='evd-1',
        classification=RetentionClassification.DELETE,
        storage_key='claims/clm-1/evidence/evd-1/finalised/abc',
        source_refs=['evd-1'],
    )


def _operation(
    *,
    status: RetentionOperationStatus = RetentionOperationStatus.RESERVED,
    target: RetentionCleanupTarget | None = None,
    evidence: list[RetentionStepEvidence] | None = None,
    targets_frozen: bool = True,
    completed: bool = False,
) -> RetentionOperation:
    selected = [target or _object_target()]

    return RetentionOperation(
        operation_id='ret-1',
        claim_id='clm-1',
        source_terminal_ref='claim-terminal:clm-1:revision:7',
        source_claim_revision=7,
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
        revision=1,
        status=status,
        access_closed_at=NOW,
        targets_frozen_at=NOW if targets_frozen else None,
        targets=selected,
        step_evidence=evidence or [],
        source_refs=['claim-terminal:clm-1:revision:7'],
        created_at=NOW,
        updated_at=NOW,
        completed_at=NOW if completed else None,
    )


def _object_evidence(
    outcome: ObjectDeletionOutcome,
    *,
    attempt: int = 1,
) -> RetentionStepEvidence:
    status = {
        ObjectDeletionOutcome.DELETED: RetentionStepStatus.SATISFIED,
        ObjectDeletionOutcome.ALREADY_ABSENT: RetentionStepStatus.SATISFIED,
        ObjectDeletionOutcome.FAILED: RetentionStepStatus.FAILED,
        ObjectDeletionOutcome.UNKNOWN: RetentionStepStatus.UNKNOWN,
    }[outcome]

    return RetentionStepEvidence(
        evidence_id=f'step-{attempt}-{outcome.value}',
        target_id='target-object-1',
        attempt=attempt,
        status=status,
        object_outcome=outcome,
        diagnostic_code=(
            f'OBJECT_{outcome.value.upper()}'
            if status
            in {
                RetentionStepStatus.FAILED,
                RetentionStepStatus.UNKNOWN,
            }
            else None
        ),
        source_refs=['evd-1'],
        recorded_at=NOW,
    )


def test_retention_classification_baseline_preserves_authority_boundaries() -> None:
    assert RETENTION_CLASSIFICATION_BASELINE['EvidenceObjectBytes'] == (
        RetentionClassification.DELETE,
    )

    assert (
        RetentionClassification.RETAIN in (RETENTION_CLASSIFICATION_BASELINE['FollowUpOperation'])
    )

    assert (
        RetentionClassification.RETAIN in (RETENTION_CLASSIFICATION_BASELINE['ExternalTaskRecord'])
    )

    assert (
        RetentionClassification.RETAIN in (RETENTION_CLASSIFICATION_BASELINE['AuditEventEnvelope'])
    )

    assert (
        RetentionClassification.RETAIN in (RETENTION_CLASSIFICATION_BASELINE['RetentionOperation'])
    )


def test_retention_hold_blocks_cleanup_but_is_independent_of_access_closure() -> None:
    hold = RetentionHoldRecord(
        hold_id='hold-1',
        claim_id='clm-1',
        reason=RetentionHoldReason.INVESTIGATION,
        authority_ref='staff:reviewer-1',
        source_refs=['work-item-1'],
        applied_at=NOW,
    )

    operation = _operation()

    assert hold.active is True
    assert (
        retention_next_status(
            operation,
            active_hold=hold.active,
        )
        is RetentionOperationStatus.HELD
    )

    # A hold pauses destructive work.  It does not make stale claimant
    # credentials or old Sessions valid again.
    assert retention_access_closed(operation) is True


@pytest.mark.parametrize(
    'outcome',
    [
        ObjectDeletionOutcome.DELETED,
        ObjectDeletionOutcome.ALREADY_ABSENT,
    ],
)
def test_idempotent_object_deletion_success_satisfies_target(
    outcome: ObjectDeletionOutcome,
) -> None:
    evidence = _object_evidence(outcome)

    operation = _operation(evidence=[evidence])

    assert retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    ) == {
        'target-object-1': RetentionStepStatus.SATISFIED,
    }

    assert (
        retention_next_status(
            operation,
            active_hold=False,
        )
        is RetentionOperationStatus.COMPLETED
    )


@pytest.mark.parametrize(
    'outcome',
    [
        ObjectDeletionOutcome.FAILED,
        ObjectDeletionOutcome.UNKNOWN,
    ],
)
def test_failed_or_unknown_object_deletion_requires_reconciliation(
    outcome: ObjectDeletionOutcome,
) -> None:
    evidence = _object_evidence(outcome)

    operation = _operation(
        status=RetentionOperationStatus.RECONCILIATION_REQUIRED,
        evidence=[evidence],
    )

    assert (
        retention_next_status(
            operation,
            active_hold=False,
        )
        is RetentionOperationStatus.RECONCILIATION_REQUIRED
    )


def test_unknown_object_deletion_cannot_be_presented_as_satisfied() -> None:
    with pytest.raises(ValidationError):
        RetentionStepEvidence(
            evidence_id='step-bad',
            target_id='target-object-1',
            attempt=1,
            status=RetentionStepStatus.SATISFIED,
            object_outcome=ObjectDeletionOutcome.UNKNOWN,
            source_refs=['evd-1'],
            recorded_at=NOW,
        )


def test_retry_uses_latest_attempt_without_erasing_previous_evidence() -> None:
    first = _object_evidence(
        ObjectDeletionOutcome.UNKNOWN,
        attempt=1,
    )
    second = _object_evidence(
        ObjectDeletionOutcome.ALREADY_ABSENT,
        attempt=2,
    )

    operation = _operation(
        evidence=[first, second],
    )

    assert len(operation.step_evidence) == 2

    assert retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    ) == {
        'target-object-1': RetentionStepStatus.SATISFIED,
    }

    assert (
        retention_next_status(
            operation,
            active_hold=False,
        )
        is RetentionOperationStatus.COMPLETED
    )


def test_completed_retention_requires_every_frozen_target_satisfied() -> None:
    satisfied = _object_evidence(
        ObjectDeletionOutcome.DELETED,
    )

    completed = _operation(
        status=RetentionOperationStatus.COMPLETED,
        evidence=[satisfied],
        completed=True,
    )

    assert retention_access_closed(completed) is True

    with pytest.raises(ValidationError):
        _operation(
            status=RetentionOperationStatus.COMPLETED,
            evidence=[],
            completed=True,
        )


def test_retention_operation_cannot_reference_unknown_target_evidence() -> None:
    evidence = RetentionStepEvidence(
        evidence_id='step-other',
        target_id='missing-target',
        attempt=1,
        status=RetentionStepStatus.SATISFIED,
        source_refs=['source'],
        recorded_at=NOW,
    )

    with pytest.raises(ValidationError):
        _operation(evidence=[evidence])


def test_object_target_requires_delete_classification_and_storage_key() -> None:
    with pytest.raises(ValidationError):
        RetentionCleanupTarget(
            target_id='bad-object',
            kind=RetentionTargetKind.OBJECT_BYTES,
            record_type='EvidenceObjectBytes',
            record_id='evd-1',
            classification=RetentionClassification.ANONYMISE,
            storage_key='object/key',
        )

    with pytest.raises(ValidationError):
        RetentionCleanupTarget(
            target_id='bad-object-2',
            kind=RetentionTargetKind.OBJECT_BYTES,
            record_type='EvidenceObjectBytes',
            record_id='evd-1',
            classification=RetentionClassification.DELETE,
        )


def test_hold_release_is_monotonic_in_time() -> None:
    with pytest.raises(ValidationError):
        RetentionHoldRecord(
            hold_id='hold-bad',
            claim_id='clm-1',
            reason=RetentionHoldReason.LEGAL_HOLD,
            authority_ref='staff:reviewer',
            source_refs=['source'],
            applied_at=NOW,
            released_at=datetime(
                2026,
                9,
                28,
                9,
                59,
                tzinfo=UTC,
            ),
        )


def test_access_is_open_without_reserved_retention_operation() -> None:
    assert retention_access_closed(None) is False


def test_retention_policy_coordinate_is_integer_and_reads_legacy_label() -> None:
    operation = _operation()
    assert operation.policy_version == 1

    legacy = RetentionOperation.model_validate(
        {**operation.model_dump(mode='json'), 'policy_version': 'v1'}
    )
    assert legacy == operation

    with pytest.raises(ValueError):
        RetentionOperation.model_validate(
            {**operation.model_dump(mode='json'), 'policy_version': 'v2'}
        )
