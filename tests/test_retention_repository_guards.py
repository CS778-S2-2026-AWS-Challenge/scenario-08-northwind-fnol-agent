"""Fail-closed guards on the retention freeze and database-cleanup repository steps.

Each case runs against both persistence adapters so the Fixture and MongoDB
profiles keep the same destructive-operation contract.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from pydantic import ValidationError

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.domain.external_services import (
    ExternalTaskDelivery,
    ExternalTaskFailureCode,
    ExternalTaskOperationStatus,
    ExternalTaskRecord,
)
from backend.domain.models import (
    ActorReference,
    ActorType,
    Channel,
    ClaimState,
    ClaimTerminalDisposition,
    CustomerNextStep,
    EvidenceFileStatus,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
    IntegrationSource,
    ResponsibleParty,
    SessionRecord,
    TerminalDispositionReasonCode,
    TerminalDispositionValue,
    WorkingClaim,
)
from backend.domain.retention import (
    INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
    INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
    ObjectDeletionOutcome,
    RetentionClassification,
    RetentionCleanupTarget,
    RetentionDeleteAuthorization,
    RetentionHoldReason,
    RetentionHoldRecord,
    RetentionOperation,
    RetentionOperationStatus,
    RetentionStepEvidence,
    RetentionStepStatus,
    RetentionTargetFreezeReason,
    RetentionTargetFreezeRejected,
    RetentionTargetKind,
    retention_terminal_source_ref,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyConflict,
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.retention import (
    execute_retention_cleanup,
    execute_retention_object_cleanup,
    freeze_retention_cleanup_targets,
    reserve_retention_from_terminal,
)

NOW = datetime(2026, 9, 30, 9, 0, tzinfo=UTC)
KINDS = pytest.mark.parametrize('kind', ['fixture', 'mongodb'])


def _repository(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'retention_guards_{kind}',
    )
    monkeypatch.setattr(
        repository,
        '_atomic',
        lambda operation: operation(None),
    )
    return repository


def _claim(claim_id: str) -> WorkingClaim:
    return WorkingClaim(
        claim_id=claim_id,
        customer_id='cus_retention_guards',
        revision=1,
        channel=Channel.WEB_AGENT,
        locale='en-NZ',
        claim_state=ClaimState(),
        active_session_id=f'ses_{claim_id}',
        customer_next_step=CustomerNextStep(
            status='collecting_details',
            summary='Continue the report.',
            responsible_party=ResponsibleParty.CLAIMANT,
        ),
        created_at=NOW,
        updated_at=NOW,
    )


def _create(repository: PersistenceRepository, claim_id: str) -> WorkingClaim:
    claim = _claim(claim_id)
    repository.create_claim(
        claim,
        SessionRecord(
            session_id=claim.active_session_id or '',
            claim_id=claim.claim_id,
            customer_id=claim.customer_id,
            model_profile_id='openrouter-gpt-4o',
            context_revision=claim.revision,
            started_at=NOW,
            last_active_at=NOW,
        ),
    )
    return claim


def _terminalise(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> WorkingClaim:
    timestamp = NOW + timedelta(minutes=1)
    updated = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'terminal_disposition': ClaimTerminalDisposition(
                value=TerminalDispositionValue.ABANDONED,
                reason_code=TerminalDispositionReasonCode.RECOVERY_EXPIRED,
                source_refs=[
                    f'follow-up:fup_{claim.claim_id}',
                    f'session:{claim.active_session_id}',
                ],
                recorded_by=ActorReference(
                    actor_type=ActorType.SYSTEM,
                    actor_id='p17-recovery-expiry',
                ),
                recorded_at=timestamp,
                recorded_revision=claim.revision + 1,
            ),
            'customer_next_step': CustomerNextStep(
                status='recovery_expired',
                summary='Recovery expired.',
                responsible_party=ResponsibleParty.SYSTEM,
                can_resume=False,
            ),
            'updated_at': timestamp,
        }
    )
    repository.save_claim(updated, expected_revision=claim.revision)
    return updated


def _manual_operation(claim: WorkingClaim) -> RetentionOperation:
    """Reserve directly through the repository, bypassing service eligibility.

    This lets a test place a blocker that eligibility would have refused, so the
    freeze step's own fail-closed recheck is what gets exercised.
    """

    terminal = claim.terminal_disposition
    assert terminal is not None
    source_ref = retention_terminal_source_ref(claim.claim_id, terminal.recorded_revision)
    return RetentionOperation(
        operation_id=f'ret_guard_{claim.claim_id}',
        claim_id=claim.claim_id,
        source_terminal_ref=source_ref,
        source_claim_revision=claim.revision,
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=NOW + timedelta(minutes=2),
        source_refs=[source_ref, *terminal.source_refs],
        created_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
    )


def _frozen_with_object(
    repository: PersistenceRepository,
    storage: MockEvidenceStorage,
    claim_id: str,
) -> RetentionOperation:
    """Return a frozen operation holding object bytes plus database records."""

    base = _create(repository, claim_id)
    stored = storage.store_generated_content(
        claim_id=base.claim_id,
        evidence_id=f'evd_{claim_id}',
        content=b'guard',
        media_type='image/jpeg',
    )
    repository.save_evidence(
        EvidenceRecord(
            evidence_id=f'evd_{claim_id}',
            claim_id=base.claim_id,
            kind='other_document',
            status=EvidenceStatus.RECEIVED,
            file_status=EvidenceFileStatus.READY,
            original_filename='guard.jpg',
            media_type='image/jpeg',
            size_bytes=5,
            source=EvidenceSource.CLAIMANT,
            provenance={
                'storage_key': stored.storage_key,
                'upload_checksum': stored.checksum,
            },
            created_at=NOW + timedelta(seconds=10),
            updated_at=NOW + timedelta(seconds=10),
        ),
        base.customer_id,
    )
    claim = _terminalise(repository, base)
    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )
    return freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )


def _target_id(operation: RetentionOperation, kind: RetentionTargetKind) -> str:
    return next(target.target_id for target in operation.targets if target.kind is kind)


def _standalone_operation(operation_id: str) -> RetentionOperation:
    """A frozen operation with one object target and one database target."""

    return RetentionOperation(
        operation_id=operation_id,
        claim_id=f'clm_{operation_id}',
        source_terminal_ref=f'claim-terminal:clm_{operation_id}:revision:7',
        source_claim_revision=7,
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=NOW,
        targets_frozen_at=NOW,
        targets=[
            RetentionCleanupTarget(
                target_id='target-object',
                kind=RetentionTargetKind.OBJECT_BYTES,
                record_type='EvidenceObjectBytes',
                record_id='evd-object',
                classification=RetentionClassification.DELETE,
                storage_key=f'claims/clm_{operation_id}/evidence/evd-object/finalised/abc',
                source_refs=['evd-object'],
            ),
            RetentionCleanupTarget(
                target_id='target-record',
                kind=RetentionTargetKind.MONGO_RECORD,
                record_type='EvidenceRecord',
                record_id='evd-object',
                classification=RetentionClassification.ANONYMISE,
                source_refs=['evd-object'],
            ),
        ],
        source_refs=[f'claim-terminal:clm_{operation_id}:revision:7'],
        created_at=NOW,
        updated_at=NOW,
    )


@KINDS
def test_object_delete_authorization_rejects_invalid_coordinates(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    operation = _standalone_operation(f'ret_authorize_{kind}')
    assert repository.reserve_retention_operation(operation) is True
    later = NOW + timedelta(seconds=1)

    with pytest.raises(KeyError):
        repository.authorize_retention_object_target('ret_missing', 'target-object', 1, now=later)
    with pytest.raises(RevisionConflict):
        repository.authorize_retention_object_target(
            operation.operation_id, 'target-object', operation.revision + 1, now=later
        )
    with pytest.raises(KeyError):
        repository.authorize_retention_object_target(
            operation.operation_id, 'target-missing', operation.revision, now=later
        )
    with pytest.raises(ValueError, match='object-byte'):
        repository.authorize_retention_object_target(
            operation.operation_id, 'target-record', operation.revision, now=later
        )
    assert repository.get_retention_operation(operation.operation_id) == operation

    authorized, authorization = repository.authorize_retention_object_target(
        operation.operation_id, 'target-object', operation.revision, now=later
    )

    # An in-flight authorization fences every other target until it settles.
    with pytest.raises(IdempotencyConflict):
        repository.authorize_retention_object_target(
            operation.operation_id, 'target-record', authorized.revision, now=later
        )

    settled = repository.record_retention_object_result(
        operation.operation_id,
        authorization.authorization_id,
        outcome=ObjectDeletionOutcome.DELETED,
        now=later,
    )
    assert settled.active_delete_authorization_id is None

    with pytest.raises(ValueError, match='re-authorized'):
        repository.authorize_retention_object_target(
            operation.operation_id, 'target-object', settled.revision, now=later
        )


@KINDS
def test_object_delete_result_requires_the_active_authorization(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    operation = _standalone_operation(f'ret_result_{kind}')
    assert repository.reserve_retention_operation(operation) is True
    later = NOW + timedelta(seconds=1)

    with pytest.raises(KeyError):
        repository.record_retention_object_result(
            'ret_missing', 'auth-missing', outcome=ObjectDeletionOutcome.DELETED, now=later
        )
    with pytest.raises(KeyError):
        repository.record_retention_object_result(
            operation.operation_id,
            'auth-missing',
            outcome=ObjectDeletionOutcome.DELETED,
            now=later,
        )

    _, authorization = repository.authorize_retention_object_target(
        operation.operation_id, 'target-object', operation.revision, now=later
    )
    failed = repository.record_retention_object_result(
        operation.operation_id,
        authorization.authorization_id,
        outcome=ObjectDeletionOutcome.FAILED,
        now=later,
    )

    # Replaying the same provider result is stable and adds no evidence.
    replay = repository.record_retention_object_result(
        operation.operation_id,
        authorization.authorization_id,
        outcome=ObjectDeletionOutcome.DELETED,
        now=later + timedelta(seconds=1),
    )
    assert replay == failed
    assert failed.status is RetentionOperationStatus.RECONCILIATION_REQUIRED


@KINDS
def test_database_failure_evidence_rejects_invalid_coordinates(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    operation = _standalone_operation(f'ret_step_failure_{kind}')
    assert repository.reserve_retention_operation(operation) is True
    later = NOW + timedelta(seconds=1)

    def record(
        operation_id: str = operation.operation_id,
        target_id: str = 'target-record',
        expected_revision: int = operation.revision,
        status: RetentionStepStatus = RetentionStepStatus.FAILED,
    ) -> RetentionOperation:
        return repository.record_retention_step_failure(
            operation_id,
            target_id,
            expected_revision,
            status=status,
            diagnostic_code='DATABASE_STEP_FAILED',
            now=later,
        )

    with pytest.raises(KeyError):
        record(operation_id='ret_missing')
    with pytest.raises(RevisionConflict):
        record(expected_revision=operation.revision + 1)
    with pytest.raises(ValueError, match='failed or unknown'):
        record(status=RetentionStepStatus.SATISFIED)
    with pytest.raises(KeyError):
        record(target_id='target-missing')
    with pytest.raises(ValueError, match='MONGO_RECORD'):
        record(target_id='target-object')
    assert repository.get_retention_operation(operation.operation_id) == operation

    unknown = record(status=RetentionStepStatus.UNKNOWN)
    assert unknown.revision == operation.revision + 1
    assert unknown.status is RetentionOperationStatus.RECONCILIATION_REQUIRED
    assert [item.status for item in unknown.step_evidence] == [RetentionStepStatus.UNKNOWN]


@KINDS
def test_freeze_rejects_unknown_operation_and_stale_revision(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)

    with pytest.raises(RetentionTargetFreezeRejected) as caught:
        repository.freeze_retention_targets('ret_missing', 1, frozen_at=NOW)
    assert caught.value.reason is RetentionTargetFreezeReason.OPERATION_NOT_FOUND

    claim = _terminalise(repository, _create(repository, f'clm_freeze_stale_{kind}'))
    operation = _manual_operation(claim)
    assert repository.reserve_retention_operation(operation) is True

    with pytest.raises(RevisionConflict):
        repository.freeze_retention_targets(
            operation.operation_id,
            operation.revision + 1,
            frozen_at=NOW + timedelta(minutes=3),
        )

    unchanged = repository.get_retention_operation(operation.operation_id)
    assert unchanged == operation


@KINDS
def test_freeze_rechecks_unknown_external_outcome(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _create(repository, f'clm_freeze_external_{kind}')
    repository.save_external_task(
        ExternalTaskRecord(
            task_id=f'ext_guard_{kind}',
            claim_id=base.claim_id,
            service_identity='vehicle_damage_assessment_routing',
            requested_action='vehicle_damage_assessment',
            integration_source=IntegrationSource.FIXTURE,
            status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
            delivery=ExternalTaskDelivery.SUBMITTED,
            delivery_evidence='fixture:submitted',
            failure_code=ExternalTaskFailureCode.TIMEOUT,
            created_at=NOW + timedelta(seconds=10),
            updated_at=NOW + timedelta(seconds=10),
        ),
        base.customer_id,
    )
    claim = _terminalise(repository, base)
    operation = _manual_operation(claim)
    assert repository.reserve_retention_operation(operation) is True

    with pytest.raises(RetentionTargetFreezeRejected) as caught:
        repository.freeze_retention_targets(
            operation.operation_id,
            operation.revision,
            frozen_at=NOW + timedelta(minutes=3),
        )

    assert caught.value.reason is RetentionTargetFreezeReason.EXTERNAL_OUTCOME_UNKNOWN
    unchanged = repository.get_retention_operation(operation.operation_id)
    assert unchanged is not None
    assert unchanged.targets_frozen_at is None
    assert unchanged.targets == []


@KINDS
def test_database_step_rejects_invalid_coordinates(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    storage = MockEvidenceStorage()
    frozen = _frozen_with_object(repository, storage, f'clm_apply_coords_{kind}')
    record_target = _target_id(frozen, RetentionTargetKind.MONGO_RECORD)
    object_target = _target_id(frozen, RetentionTargetKind.OBJECT_BYTES)
    later = NOW + timedelta(minutes=4)

    with pytest.raises(KeyError):
        repository.apply_retention_record_target('ret_missing', record_target, 1, now=later)

    with pytest.raises(RevisionConflict):
        repository.apply_retention_record_target(
            frozen.operation_id, record_target, frozen.revision + 1, now=later
        )

    with pytest.raises(KeyError):
        repository.apply_retention_record_target(
            frozen.operation_id, 'target-missing', frozen.revision, now=later
        )

    with pytest.raises(ValueError, match='MONGO_RECORD'):
        repository.apply_retention_record_target(
            frozen.operation_id, object_target, frozen.revision, now=later
        )

    # Database metadata may never be removed while object bytes still exist.
    with pytest.raises(ValueError, match='object target'):
        repository.apply_retention_record_target(
            frozen.operation_id, record_target, frozen.revision, now=later
        )

    assert repository.get_retention_operation(frozen.operation_id) == frozen
    assert repository.get_claim_internal(frozen.claim_id) is not None


@KINDS
def test_database_step_stops_under_hold_applied_after_object_cleanup(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    storage = MockEvidenceStorage()
    frozen = _frozen_with_object(repository, storage, f'clm_apply_hold_{kind}')

    objects_done = execute_retention_object_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=4),
    )
    record_target = _target_id(objects_done, RetentionTargetKind.MONGO_RECORD)

    hold = RetentionHoldRecord(
        hold_id=f'hold_apply_{kind}',
        claim_id=frozen.claim_id,
        reason=RetentionHoldReason.INVESTIGATION,
        authority_ref='staff:investigation',
        source_refs=['review:apply'],
        applied_at=NOW + timedelta(minutes=5),
    )
    repository.save_retention_hold(hold)
    held = repository.get_retention_operation(frozen.operation_id)
    assert held is not None

    with pytest.raises(RetentionTargetFreezeRejected) as caught:
        repository.apply_retention_record_target(
            held.operation_id,
            record_target,
            held.revision,
            now=NOW + timedelta(minutes=6),
        )

    assert caught.value.reason is RetentionTargetFreezeReason.ACTIVE_HOLD
    assert repository.get_claim_internal(frozen.claim_id) is not None

    repository.save_retention_hold(
        hold.model_copy(update={'released_at': NOW + timedelta(minutes=7)})
    )
    completed = execute_retention_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=8),
    )
    assert completed.status is RetentionOperationStatus.COMPLETED
    assert repository.get_claim_internal(frozen.claim_id) is None

    # Replaying a satisfied step or a completed operation is a stable no-op.
    assert (
        repository.apply_retention_record_target(
            completed.operation_id,
            record_target,
            completed.revision,
            now=NOW + timedelta(minutes=9),
        )
        == completed
    )


NAIVE = NOW.replace(tzinfo=None)
BEFORE = NOW - timedelta(minutes=1)


def _hold_payload() -> dict[str, Any]:
    return {
        'hold_id': 'hold-model',
        'claim_id': 'clm-model',
        'reason': RetentionHoldReason.INVESTIGATION,
        'authority_ref': 'staff:reviewer',
        'source_refs': ['review:1'],
        'applied_at': NOW,
    }


def _target_payload() -> dict[str, Any]:
    return {
        'target_id': 'target-model',
        'kind': RetentionTargetKind.MONGO_RECORD,
        'record_type': 'EvidenceRecord',
        'record_id': 'evd-model',
        'classification': RetentionClassification.ANONYMISE,
        'source_refs': ['evd-model'],
    }


def _step_payload() -> dict[str, Any]:
    return {
        'evidence_id': 'step-model',
        'target_id': 'target-model',
        'attempt': 1,
        'status': RetentionStepStatus.FAILED,
        'diagnostic_code': 'DATABASE_STEP_FAILED',
        'source_refs': ['evd-model'],
        'recorded_at': NOW,
    }


def _operation_payload() -> dict[str, Any]:
    return _standalone_operation('ret_model').model_dump(mode='python')


RECORD_CASES: list[tuple[str, type[Any], Callable[[], dict[str, Any]], dict[str, Any], str]] = [
    ('hold-naive-applied', RetentionHoldRecord, _hold_payload, {'applied_at': NAIVE}, 'applied_at'),
    (
        'hold-naive-released',
        RetentionHoldRecord,
        _hold_payload,
        {'released_at': NAIVE},
        'released_at',
    ),
    (
        'hold-duplicate-refs',
        RetentionHoldRecord,
        _hold_payload,
        {'source_refs': ['review:1', 'review:1']},
        'must be unique',
    ),
    (
        'target-duplicate-refs',
        RetentionCleanupTarget,
        _target_payload,
        {'source_refs': ['evd-model', 'evd-model']},
        'must be unique',
    ),
    (
        'record-target-storage-key',
        RetentionCleanupTarget,
        _target_payload,
        {'storage_key': 'claims/clm-model/evidence/evd-model'},
        'Only object-byte targets',
    ),
    (
        'tombstone-target-classification',
        RetentionCleanupTarget,
        _target_payload,
        {'kind': RetentionTargetKind.TOMBSTONE},
        'TOMBSTONE classification',
    ),
    (
        'step-naive-time',
        RetentionStepEvidence,
        _step_payload,
        {'recorded_at': NAIVE},
        'timezone-aware',
    ),
    (
        'step-duplicate-refs',
        RetentionStepEvidence,
        _step_payload,
        {'source_refs': ['evd-model', 'evd-model']},
        'must be unique',
    ),
    (
        'step-failure-without-diagnostic',
        RetentionStepEvidence,
        _step_payload,
        {'diagnostic_code': None},
        'safe diagnostic code',
    ),
]

OPERATION_CASES: list[tuple[str, type[Any], Callable[[], dict[str, Any]], dict[str, Any], str]] = [
    (
        'operation-naive-created',
        RetentionOperation,
        _operation_payload,
        {'created_at': NAIVE},
        'created_at must be timezone-aware',
    ),
    (
        'operation-updated-before-created',
        RetentionOperation,
        _operation_payload,
        {'updated_at': BEFORE},
        'cannot precede created_at',
    ),
    (
        'operation-access-closed-before-created',
        RetentionOperation,
        _operation_payload,
        {'access_closed_at': BEFORE},
        'Resource-access closure',
    ),
    (
        'operation-naive-freeze',
        RetentionOperation,
        _operation_payload,
        {'targets_frozen_at': NAIVE},
        'freeze time must be timezone-aware',
    ),
    (
        'operation-frozen-before-created',
        RetentionOperation,
        _operation_payload,
        {'targets_frozen_at': BEFORE},
        'frozen before creation',
    ),
    (
        'operation-duplicate-refs',
        RetentionOperation,
        _operation_payload,
        {'source_refs': ['ref', 'ref']},
        'must be unique',
    ),
]


def _assert_rejected(
    model: type[Any],
    payload: Callable[[], dict[str, Any]],
    update: dict[str, Any],
    reason: str,
) -> None:
    assert model.model_validate(payload()) is not None
    data = payload()
    data.update(update)
    with pytest.raises(ValidationError, match=reason):
        model.model_validate(data)


@pytest.mark.parametrize(
    ('case', 'model', 'payload', 'update', 'reason'),
    RECORD_CASES,
    ids=[case[0] for case in RECORD_CASES],
)
def test_retention_evidence_records_reject_inconsistent_facts(
    case: str,
    model: type[Any],
    payload: Callable[[], dict[str, Any]],
    update: dict[str, Any],
    reason: str,
) -> None:
    """Holds, cleanup targets and step evidence refuse naive times, duplicate sources,
    misplaced storage keys and unexplained failures."""

    _assert_rejected(model, payload, update, reason)


@pytest.mark.parametrize(
    ('case', 'model', 'payload', 'update', 'reason'),
    OPERATION_CASES,
    ids=[case[0] for case in OPERATION_CASES],
)
def test_retention_operation_rejects_an_impossible_timeline(
    case: str,
    model: type[Any],
    payload: Callable[[], dict[str, Any]],
    update: dict[str, Any],
    reason: str,
) -> None:
    _assert_rejected(model, payload, update, reason)


def test_delete_authorization_requires_an_aware_timestamp() -> None:
    with pytest.raises(ValidationError, match='timezone-aware'):
        RetentionDeleteAuthorization(
            authorization_id='auth-model',
            target_id='target-model',
            attempt=1,
            authorized_at=NAIVE,
        )
