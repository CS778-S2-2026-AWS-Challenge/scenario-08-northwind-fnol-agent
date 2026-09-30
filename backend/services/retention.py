"""Durable P17 destructive-retention execution.

This service consumes a previously reserved RetentionOperation.  It does not
decide Claim terminal state and is not an authentication authority.
"""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256

from backend.adapters.evidence_storage import (
    EvidenceStorage,
    EvidenceStorageUnavailable,
)
from backend.domain.audit import (
    AuditActor,
    AuditEventEnvelope,
    AuditEventType,
    AuditOutcome,
    AuditSubject,
    AuditSubjectType,
    AuditVisibility,
)
from backend.domain.ids import stable_operation_id
from backend.domain.models import ActorType
from backend.domain.retention import (
    INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
    INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
    ClaimantRetentionProjection,
    ObjectDeletionOutcome,
    RetentionClassification,
    RetentionDatabaseStepError,
    RetentionEligibilityReason,
    RetentionEligibilityRejected,
    RetentionOperation,
    RetentionOperationStatus,
    RetentionProjectedContentState,
    RetentionStepEvidence,
    RetentionStepStatus,
    RetentionTargetFreezeReason,
    RetentionTargetFreezeRejected,
    RetentionTargetKind,
    StaffRetentionProjection,
    StaffRetentionResourceSummary,
    retention_access_closed,
    retention_target_statuses,
    retention_terminal_source_ref,
)
from backend.repositories.protocols import PersistenceRepository


def _active_hold_ids(
    repository: PersistenceRepository,
    claim_id: str,
) -> list[str]:
    return sorted(hold.hold_id for hold in repository.list_retention_holds(claim_id) if hold.active)


def _step_evidence_id(
    operation_id: str,
    target_id: str,
    attempt: int,
) -> str:
    digest = sha256((f'{operation_id}|{target_id}|{attempt}').encode()).hexdigest()[:40]

    return f'rse_{digest}'


def _next_attempt(
    operation: RetentionOperation,
    target_id: str,
) -> int:
    return (
        max(
            (item.attempt for item in operation.step_evidence if item.target_id == target_id),
            default=0,
        )
        + 1
    )


def _candidate_after_step(
    operation: RetentionOperation,
    evidence: RetentionStepEvidence,
    *,
    now: datetime,
) -> RetentionOperation:
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
        and all(item_status is RetentionStepStatus.SATISFIED for item_status in statuses.values())
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


def _held_candidate(
    operation: RetentionOperation,
    hold_ids: list[str],
    *,
    now: datetime,
) -> RetentionOperation:
    combined = sorted(set(operation.hold_refs).union(hold_ids))

    if operation.status is RetentionOperationStatus.HELD and combined == operation.hold_refs:
        return operation

    payload = operation.model_dump(mode='python')
    payload.update(
        {
            'revision': operation.revision + 1,
            'status': RetentionOperationStatus.HELD,
            'hold_refs': combined,
            'updated_at': now,
            'completed_at': None,
        }
    )

    return RetentionOperation.model_validate(payload)


def execute_retention_object_cleanup(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    operation_id: str,
    *,
    now: datetime,
) -> RetentionOperation:
    """Execute unfinished object targets through a durable authorization fence.

    Authorization and hold creation contend on the RetentionOperation revision.
    A hold that commits first blocks authorization. If authorization commits
    first, that one in-flight provider call may settle, but a later hold leaves
    the operation HELD and prevents every subsequent destructive target.
    """

    if now.utcoffset() is None:
        raise ValueError('Retention execution time must be timezone-aware.')

    operation = repository.get_retention_operation(operation_id)
    if operation is None:
        raise KeyError(operation_id)
    if operation.status is RetentionOperationStatus.COMPLETED:
        return operation

    hold_ids = _active_hold_ids(repository, operation.claim_id)
    if hold_ids and operation.active_delete_authorization_id is None:
        held = _held_candidate(operation, hold_ids, now=now)
        if held != operation:
            repository.save_retention_operation(held, operation.revision)
        return held

    statuses = retention_target_statuses(operation.targets, operation.step_evidence)

    for target in sorted(operation.targets, key=lambda item: item.target_id):
        if target.kind is not RetentionTargetKind.OBJECT_BYTES:
            continue
        if statuses[target.target_id] is RetentionStepStatus.SATISFIED:
            continue
        if target.storage_key is None:
            raise ValueError('Object retention target lost its storage key.')

        try:
            operation, authorization = repository.authorize_retention_object_target(
                operation.operation_id,
                target.target_id,
                operation.revision,
                now=now,
            )
        except RetentionTargetFreezeRejected:
            refreshed = repository.get_retention_operation(operation.operation_id)
            if refreshed is None:
                raise
            return refreshed
        except Exception:
            refreshed = repository.get_retention_operation(operation.operation_id)
            if (
                refreshed is not None
                and refreshed.status is RetentionOperationStatus.HELD
                and refreshed.active_delete_authorization_id is None
            ):
                return refreshed
            raise

        try:
            outcome = storage.delete_upload(
                claim_id=operation.claim_id,
                evidence_id=target.record_id,
                storage_key=target.storage_key,
            )
        except EvidenceStorageUnavailable:
            outcome = ObjectDeletionOutcome.FAILED

        operation = repository.record_retention_object_result(
            operation.operation_id,
            authorization.authorization_id,
            outcome=outcome,
            now=now,
        )
        statuses = retention_target_statuses(operation.targets, operation.step_evidence)

        latest_status = statuses[target.target_id]
        if operation.status is RetentionOperationStatus.HELD:
            return operation
        if latest_status in {
            RetentionStepStatus.FAILED,
            RetentionStepStatus.UNKNOWN,
        }:
            break

    return operation


def reserve_retention_from_terminal(
    repository: PersistenceRepository,
    claim_id: str,
    *,
    now: datetime,
) -> RetentionOperation:
    """Consume an existing terminal fact and atomically reserve retention.

    The service performs a readable preflight, but repository reservation repeats
    every authoritative predicate inside its own lock/transaction.
    """

    if now.utcoffset() is None:
        raise ValueError('Retention reservation time must be timezone-aware.')

    claim = repository.get_claim_internal(claim_id)

    if claim is None:
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.CLAIM_NOT_FOUND,
            claim_id,
        )

    terminal = claim.terminal_disposition

    if terminal is None:
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.TERMINAL_REQUIRED,
            claim_id,
        )

    source_terminal_ref = retention_terminal_source_ref(
        claim.claim_id,
        terminal.recorded_revision,
    )

    source_refs = list(
        dict.fromkeys(
            [
                source_terminal_ref,
                *terminal.source_refs,
            ]
        )
    )

    operation_seed = '|'.join(
        (
            claim.claim_id,
            source_terminal_ref,
            INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
            # The seed keeps the original ``v1`` label so operation identities
            # derived before the integer coordinate stay stable on restart.
            f'v{INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION}',
        )
    )

    operation = RetentionOperation(
        operation_id=stable_operation_id('ret', operation_seed),
        claim_id=claim.claim_id,
        source_terminal_ref=source_terminal_ref,
        source_claim_revision=claim.revision,
        policy_id=(INCOMPLETE_CLAIM_RETENTION_POLICY_ID),
        policy_version=(INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION),
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=now,
        source_refs=source_refs,
        created_at=now,
        updated_at=now,
    )

    return repository.reserve_eligible_retention_operation(operation)


def freeze_retention_cleanup_targets(
    repository: PersistenceRepository,
    operation_id: str,
    *,
    now: datetime,
) -> RetentionOperation:
    """Freeze the exact cleanup inventory before any destructive operation."""

    if now.utcoffset() is None:
        raise ValueError('Retention target freeze time must be timezone-aware.')

    operation = repository.get_retention_operation(operation_id)

    if operation is None:
        raise RetentionTargetFreezeRejected(
            RetentionTargetFreezeReason.OPERATION_NOT_FOUND,
            operation_id,
        )

    if operation.targets_frozen_at is None:
        operation = repository.freeze_retention_targets(
            operation.operation_id,
            operation.revision,
            frozen_at=now,
        )

    assert operation.targets_frozen_at is not None

    _append_retention_audit(
        repository,
        operation,
        phase='prepared',
        event_at=operation.targets_frozen_at,
    )

    return operation


_RETENTION_DATABASE_ORDER = {
    'MessageRecord': 10,
    'EvidenceClaimLink': 20,
    'EvidenceRecord': 30,
    'SessionRecord': 40,
    'FollowUpRecord': 50,
    'HandoffRecord': 60,
    'ExternalTaskResult': 70,
    'ExternalTaskRequest': 80,
    'ExternalTaskRecord': 90,
    'ExternalTaskEvidenceLink': 100,
    'ExternalTaskAttempt': 110,
    'FollowUpOperation': 120,
    'RuntimeWorkItemRecord': 130,
    'AuditEventEnvelope': 140,
    'RetentionHoldRecord': 150,
    'IdempotencyRecord': 800,
    # Claim is deliberately last: it is the broadest business authority and
    # must remain available while the earlier selected records are processed.
    'WorkingClaim': 900,
}


def execute_retention_cleanup(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    operation_id: str,
    *,
    now: datetime,
) -> RetentionOperation:
    """Execute frozen cleanup and reconcile the same logical operation."""

    if now.utcoffset() is None:
        raise ValueError('Retention execution time must be timezone-aware.')

    operation = repository.get_retention_operation(operation_id)

    if operation is None:
        raise KeyError(operation_id)

    if operation.status is RetentionOperationStatus.COMPLETED:
        assert operation.completed_at is not None

        _append_retention_audit(
            repository,
            operation,
            phase='completed',
            event_at=operation.completed_at,
        )

        return operation

    if operation.targets_frozen_at is None:
        raise ValueError('Retention cleanup cannot execute before targets are frozen.')

    # Cross-store order remains strict: object bytes first.
    operation = execute_retention_object_cleanup(
        repository,
        storage,
        operation_id,
        now=now,
    )

    if operation.status is RetentionOperationStatus.HELD:
        return operation

    if operation.status is RetentionOperationStatus.COMPLETED:
        assert operation.completed_at is not None

        _append_retention_audit(
            repository,
            operation,
            phase='completed',
            event_at=operation.completed_at,
        )

        return operation

    statuses = retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    )

    object_incomplete = any(
        target.kind is RetentionTargetKind.OBJECT_BYTES
        and statuses[target.target_id] is not RetentionStepStatus.SATISFIED
        for target in operation.targets
    )

    if object_incomplete:
        if operation.status is RetentionOperationStatus.RECONCILIATION_REQUIRED:
            _audit_reconciliation(
                repository,
                operation,
            )

        return operation

    database_targets = sorted(
        (target for target in operation.targets if target.kind is RetentionTargetKind.MONGO_RECORD),
        key=lambda target: (
            _RETENTION_DATABASE_ORDER.get(
                target.record_type,
                500,
            ),
            target.record_type,
            target.record_id,
            target.target_id,
        ),
    )

    for target in database_targets:
        statuses = retention_target_statuses(
            operation.targets,
            operation.step_evidence,
        )

        if statuses[target.target_id] is RetentionStepStatus.SATISFIED:
            continue

        # Database cleanup is destructive too. A hold that became active after
        # object cleanup must stop the next unstarted database mutation.
        hold_ids = _active_hold_ids(repository, operation.claim_id)
        if hold_ids:
            held = _held_candidate(operation, hold_ids, now=now)
            if held != operation:
                repository.save_retention_operation(held, operation.revision)
            return held

        try:
            operation = repository.apply_retention_record_target(
                operation.operation_id,
                target.target_id,
                operation.revision,
                now=now,
            )

        except RetentionDatabaseStepError as error:
            # A Mongo commit response can be unknown even though the
            # transaction actually committed. Reload before recording
            # reconciliation so a committed target is never repeated.
            refreshed = repository.get_retention_operation(operation.operation_id)

            if refreshed is None:
                raise

            refreshed_statuses = retention_target_statuses(
                refreshed.targets,
                refreshed.step_evidence,
            )

            if refreshed_statuses.get(target.target_id) is RetentionStepStatus.SATISFIED:
                operation = refreshed

                if operation.status is RetentionOperationStatus.COMPLETED:
                    break

                continue

            operation = repository.record_retention_step_failure(
                refreshed.operation_id,
                target.target_id,
                refreshed.revision,
                status=(
                    RetentionStepStatus.UNKNOWN
                    if error.commit_unknown
                    else RetentionStepStatus.FAILED
                ),
                diagnostic_code=error.diagnostic_code,
                now=now,
            )

            _audit_reconciliation(
                repository,
                operation,
            )

            return operation

        if operation.status is RetentionOperationStatus.RECONCILIATION_REQUIRED:
            _audit_reconciliation(
                repository,
                operation,
            )

            return operation

        if operation.status is RetentionOperationStatus.COMPLETED:
            break

    if operation.status is RetentionOperationStatus.COMPLETED:
        assert operation.completed_at is not None

        _append_retention_audit(
            repository,
            operation,
            phase='completed',
            event_at=operation.completed_at,
        )

    return operation


def _append_retention_audit(
    repository: PersistenceRepository,
    operation: RetentionOperation,
    *,
    phase: str,
    event_at: datetime,
    target_id: str | None = None,
    unknown: bool = False,
) -> None:
    if phase == 'prepared':
        event_type = AuditEventType.ACTION_PREPARED
        outcome = AuditOutcome.SUCCEEDED
        reason = 'Retention cleanup target set was frozen from the authoritative terminal source.'
    elif phase == 'completed':
        event_type = AuditEventType.ACTION_COMPLETED
        outcome = AuditOutcome.SUCCEEDED
        reason = 'Retention cleanup completed with every required frozen target satisfied.'
    elif phase == 'reconciliation':
        if unknown:
            event_type = AuditEventType.ACTION_UNKNOWN_OUTCOME
            outcome = AuditOutcome.UNKNOWN
            reason = (
                'Retention cleanup requires reconciliation '
                'because a database step commit result is unknown.'
            )
        else:
            event_type = AuditEventType.ACTION_FAILED
            outcome = AuditOutcome.FAILED
            reason = 'Retention cleanup requires reconciliation after a database step failure.'
    else:
        raise ValueError(f'Unsupported retention audit phase: {phase}')

    material = '|'.join(
        (
            operation.operation_id,
            phase,
            target_id or '-',
            'unknown' if unknown else 'known',
        )
    )

    event_id = 'aud_ret_' + sha256(material.encode()).hexdigest()[:32]

    refs = list(
        dict.fromkeys(
            [
                f'retention-operation:{operation.operation_id}',
                operation.source_terminal_ref,
                *operation.source_refs,
                *([f'retention-target:{target_id}'] if target_id is not None else []),
            ]
        )
    )[:100]

    event = AuditEventEnvelope(
        event_id=event_id,
        event_type=event_type,
        outcome=outcome,
        subject=AuditSubject(
            subject_type=AuditSubjectType.CLAIM,
            subject_id=operation.claim_id,
            claim_id=operation.claim_id,
        ),
        actor=AuditActor(
            actor_type=ActorType.SYSTEM,
            actor_id='retention-engine',
            auth_source='system',
        ),
        reason=reason,
        source_refs=refs,
        visibility=AuditVisibility.AUDIT_ONLY,
        correlation_id=None,
        claim_revision=(operation.source_claim_revision),
        created_at=event_at,
    )

    repository.append_audit_event(event)


def _audit_reconciliation(
    repository: PersistenceRepository,
    operation: RetentionOperation,
) -> None:
    latest = operation.step_evidence[-1] if operation.step_evidence else None

    if latest is None:
        return

    if latest.status not in {
        RetentionStepStatus.FAILED,
        RetentionStepStatus.UNKNOWN,
    }:
        return

    _append_retention_audit(
        repository,
        operation,
        phase='reconciliation',
        event_at=latest.recorded_at,
        target_id=latest.target_id,
        unknown=(latest.status is RetentionStepStatus.UNKNOWN),
    )


def project_claimant_retention(
    repository: PersistenceRepository,
    claim_id: str,
) -> ClaimantRetentionProjection | None:
    """Return only the generic closed-resource claimant projection."""

    operation = repository.get_retention_operation_for_claim(claim_id)

    if not retention_access_closed(operation):
        return None

    return ClaimantRetentionProjection()


def _retention_projected_content_state(
    classification: RetentionClassification,
    step_status: RetentionStepStatus,
) -> RetentionProjectedContentState:
    if step_status is not RetentionStepStatus.SATISFIED:
        return RetentionProjectedContentState.UNAVAILABLE

    if classification is RetentionClassification.DELETE:
        return RetentionProjectedContentState.DELETED

    if classification in {
        RetentionClassification.ANONYMISE,
        RetentionClassification.TOMBSTONE,
    }:
        return RetentionProjectedContentState.ANONYMISED

    return RetentionProjectedContentState.RETAINED_FOR_AUDIT


def project_staff_retention(
    repository: PersistenceRepository,
    claim_id: str,
) -> StaffRetentionProjection | None:
    """Project retention state without raw target IDs, storage keys or diagnostics."""

    operation = repository.get_retention_operation_for_claim(claim_id)

    if operation is None:
        return None

    if operation.access_closed_at is None:
        return None

    statuses = retention_target_statuses(
        operation.targets,
        operation.step_evidence,
    )

    counts: dict[
        tuple[
            str,
            RetentionProjectedContentState,
        ],
        int,
    ] = {}

    for target in operation.targets:
        content_state = _retention_projected_content_state(
            target.classification,
            statuses[target.target_id],
        )

        key = (
            target.record_type,
            content_state,
        )

        counts[key] = counts.get(key, 0) + 1

    # RetentionOperation itself is deliberately retained as the durable
    # execution/audit authority and is not a destructive target of itself.
    operation_key = (
        'RetentionOperation',
        RetentionProjectedContentState.RETAINED_FOR_AUDIT,
    )

    counts[operation_key] = counts.get(operation_key, 0) + 1

    resources = [
        StaffRetentionResourceSummary(
            record_type=record_type,
            content_state=content_state,
            count=count,
        )
        for (
            record_type,
            content_state,
        ), count in sorted(
            counts.items(),
            key=lambda item: (
                item[0][0],
                item[0][1].value,
            ),
        )
    ]

    holds = repository.list_retention_holds(claim_id)

    return StaffRetentionProjection(
        claim_id=claim_id,
        operation_status=operation.status,
        access_closed_at=operation.access_closed_at,
        completed_at=operation.completed_at,
        hold_active=any(hold.active for hold in holds),
        reconciliation_required=(
            operation.status is RetentionOperationStatus.RECONCILIATION_REQUIRED
        ),
        resources=resources,
    )
