from datetime import UTC, datetime, timedelta
from typing import Any

import mongomock
import pytest
from botocore.exceptions import ClientError

from backend.adapters.evidence_storage import (
    MinioEvidenceStorage,
    MockEvidenceStorage,
    S3CompatibleObjectStorageConfig,
)
from backend.domain.retention import (
    INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
    INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
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
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    PersistenceRepository,
    RevisionConflict,
)
from backend.services.retention import (
    execute_retention_object_cleanup,
)

NOW = datetime(2026, 9, 28, 11, 0, tzinfo=UTC)


def _target(
    suffix: str = '1',
) -> RetentionCleanupTarget:
    return RetentionCleanupTarget(
        target_id=f'target-{suffix}',
        kind=RetentionTargetKind.OBJECT_BYTES,
        record_type='EvidenceObjectBytes',
        record_id=f'evd-{suffix}',
        classification=RetentionClassification.DELETE,
        storage_key=(f'claims/clm-retention/evidence/evd-{suffix}/finalised/abc{suffix}'),
        source_refs=[f'evd-{suffix}'],
    )


def _operation(
    *,
    operation_id: str = 'ret-op-1',
    targets: list[RetentionCleanupTarget] | None = None,
) -> RetentionOperation:
    return RetentionOperation(
        operation_id=operation_id,
        claim_id='clm-retention',
        source_terminal_ref=('claim-terminal:clm-retention:revision:7'),
        source_claim_revision=7,
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION,
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=NOW,
        targets_frozen_at=NOW,
        targets=targets or [_target()],
        source_refs=['claim-terminal:clm-retention:revision:7'],
        created_at=NOW,
        updated_at=NOW,
    )


def _repository(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'retention_{kind}',
    )
    monkeypatch.setattr(
        repository,
        '_atomic',
        lambda operation: operation(None),
    )
    return repository


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_retention_operation_repository_has_fixture_mongo_cas_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    operation = _operation(operation_id=f'ret-{kind}')

    assert repository.reserve_retention_operation(operation) is True

    assert repository.reserve_retention_operation(operation) is False

    stored = repository.get_retention_operation(operation.operation_id)
    assert stored == operation

    by_claim = repository.get_retention_operation_for_claim(operation.claim_id)
    assert by_claim == operation

    failed = RetentionStepEvidence(
        evidence_id='step-failed',
        target_id='target-1',
        attempt=1,
        status=RetentionStepStatus.FAILED,
        object_outcome=ObjectDeletionOutcome.FAILED,
        diagnostic_code='OBJECT_DELETE_FAILED',
        source_refs=['evd-1'],
        recorded_at=NOW + timedelta(minutes=1),
    )

    payload = operation.model_dump(mode='python')
    payload.update(
        {
            'revision': 2,
            'status': (RetentionOperationStatus.RECONCILIATION_REQUIRED),
            'step_evidence': [failed],
            'updated_at': NOW + timedelta(minutes=1),
        }
    )

    candidate = RetentionOperation.model_validate(payload)

    repository.save_retention_operation(
        candidate,
        expected_revision=1,
    )

    assert repository.get_retention_operation(operation.operation_id) == candidate

    stale_payload = candidate.model_dump(mode='python')
    stale_payload.update(
        {
            'revision': 3,
            'updated_at': NOW + timedelta(minutes=2),
        }
    )

    stale = RetentionOperation.model_validate(stale_payload)

    with pytest.raises(RevisionConflict):
        repository.save_retention_operation(
            stale,
            expected_revision=1,
        )


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_retention_hold_repository_has_fixture_mongo_release_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)

    hold = RetentionHoldRecord(
        hold_id=f'hold-{kind}',
        claim_id='clm-retention',
        reason=RetentionHoldReason.INVESTIGATION,
        authority_ref='staff:reviewer',
        source_refs=['review:1'],
        applied_at=NOW,
    )

    repository.save_retention_hold(hold)
    repository.save_retention_hold(hold)

    # The hold's authority coordinates are immutable once created.
    with pytest.raises(ValueError):
        repository.save_retention_hold(
            hold.model_copy(update={'reason': RetentionHoldReason.LEGAL_HOLD})
        )

    listed = repository.list_retention_holds(hold.claim_id)
    assert listed == [hold]
    assert listed[0].active is True

    released = hold.model_copy(
        update={
            'released_at': NOW + timedelta(hours=1),
        }
    )

    repository.save_retention_hold(released)

    listed = repository.list_retention_holds(hold.claim_id)
    assert listed == [released]
    assert listed[0].active is False


class _HoldAfterFirstDeleteStorage:
    max_size_bytes = 1
    allowed_media_types: tuple[str, ...] = ()
    supports_content_proxy = False

    def __init__(self, repository: PersistenceRepository) -> None:
        self.repository = repository
        self.delete_calls = 0

    def delete_upload(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        storage_key: str,
    ) -> ObjectDeletionOutcome:
        del evidence_id, storage_key
        self.delete_calls += 1
        if self.delete_calls == 1:
            self.repository.save_retention_hold(
                RetentionHoldRecord(
                    hold_id='hold-mid-cleanup',
                    claim_id=claim_id,
                    reason=RetentionHoldReason.INVESTIGATION,
                    authority_ref='staff:reviewer',
                    source_refs=['review:mid-cleanup'],
                    applied_at=NOW + timedelta(seconds=1),
                )
            )
        return ObjectDeletionOutcome.DELETED


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_hold_applied_mid_cleanup_stops_next_target_and_resume_uses_same_operation(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    operation = _operation(
        operation_id=f'ret-mid-hold-{kind}',
        targets=[_target('1'), _target('2')],
    )
    assert repository.reserve_retention_operation(operation) is True
    storage = _HoldAfterFirstDeleteStorage(repository)

    held = execute_retention_object_cleanup(
        repository,
        storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(seconds=2),
    )

    assert held.operation_id == operation.operation_id
    assert held.status is RetentionOperationStatus.HELD
    assert storage.delete_calls == 1
    assert len(held.step_evidence) == 1
    assert held.step_evidence[0].target_id == 'target-1'
    assert held.step_evidence[0].status is RetentionStepStatus.SATISFIED

    hold = repository.list_retention_holds(operation.claim_id)[0]
    repository.save_retention_hold(
        hold.model_copy(update={'released_at': NOW + timedelta(seconds=3)})
    )

    completed = execute_retention_object_cleanup(
        repository,
        storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(seconds=4),
    )

    assert completed.operation_id == operation.operation_id
    assert completed.status is RetentionOperationStatus.COMPLETED
    assert storage.delete_calls == 2
    assert [item.target_id for item in completed.step_evidence] == [
        'target-1',
        'target-2',
    ]


def test_mock_evidence_storage_delete_is_idempotent() -> None:
    storage = MockEvidenceStorage()

    stored = storage.store_generated_content(
        claim_id='clm-retention',
        evidence_id='evd-1',
        content=b'retention-object',
        media_type='application/pdf',
    )

    assert (
        storage.delete_upload(
            claim_id='clm-retention',
            evidence_id='evd-1',
            storage_key=stored.storage_key,
        )
        is ObjectDeletionOutcome.DELETED
    )

    assert (
        storage.delete_upload(
            claim_id='clm-retention',
            evidence_id='evd-1',
            storage_key=stored.storage_key,
        )
        is ObjectDeletionOutcome.ALREADY_ABSENT
    )


class _DeleteClient:
    def __init__(
        self,
        *,
        exists: bool = True,
        fail_precheck: bool = False,
        fail_delete: bool = False,
        fail_postcheck: bool = False,
    ) -> None:
        self.exists = exists
        self.fail_precheck = fail_precheck
        self.fail_delete = fail_delete
        self.fail_postcheck = fail_postcheck
        self.delete_calls = 0
        self.head_calls = 0

    @staticmethod
    def _error(code: str, operation: str) -> ClientError:
        return ClientError(
            {
                'Error': {
                    'Code': code,
                    'Message': code,
                }
            },
            operation,
        )

    def head_object(
        self,
        **_: Any,
    ) -> dict[str, object]:
        self.head_calls += 1

        if self.head_calls == 1 and self.fail_precheck:
            raise self._error(
                'InternalError',
                'HeadObject',
            )

        if self.head_calls > 1 and self.fail_postcheck:
            raise self._error(
                'InternalError',
                'HeadObject',
            )

        if not self.exists:
            raise self._error(
                '404',
                'HeadObject',
            )

        return {}

    def delete_object(
        self,
        **_: Any,
    ) -> dict[str, object]:
        self.delete_calls += 1

        if self.fail_delete:
            raise self._error(
                'InternalError',
                'DeleteObject',
            )

        self.exists = False
        return {}


def _minio_storage(
    client: _DeleteClient,
) -> MinioEvidenceStorage:
    return MinioEvidenceStorage(
        S3CompatibleObjectStorageConfig(
            endpoint_url='https://storage.example.test',
            access_key_id='fixture-key',
            secret_access_key='fixture-secret',
            bucket='northwind-evidence',
        ),
        client=client,
    )


@pytest.mark.parametrize(
    ('client', 'expected'),
    [
        (
            _DeleteClient(exists=True),
            ObjectDeletionOutcome.DELETED,
        ),
        (
            _DeleteClient(exists=False),
            ObjectDeletionOutcome.ALREADY_ABSENT,
        ),
        (
            _DeleteClient(
                exists=True,
                fail_precheck=True,
            ),
            ObjectDeletionOutcome.FAILED,
        ),
        (
            _DeleteClient(
                exists=True,
                fail_delete=True,
            ),
            ObjectDeletionOutcome.UNKNOWN,
        ),
        (
            _DeleteClient(
                exists=True,
                fail_postcheck=True,
            ),
            ObjectDeletionOutcome.UNKNOWN,
        ),
    ],
)
def test_minio_retention_delete_reports_bounded_outcome(
    client: _DeleteClient,
    expected: ObjectDeletionOutcome,
) -> None:
    storage = _minio_storage(client)

    outcome = storage.delete_upload(
        claim_id='clm-retention',
        evidence_id='evd-1',
        storage_key=('claims/clm-retention/evidence/evd-1/finalised/abc1'),
    )

    assert outcome is expected


class _ScriptedStorage:
    def __init__(
        self,
        outcomes: dict[
            str,
            list[ObjectDeletionOutcome],
        ],
    ) -> None:
        self.outcomes = outcomes
        self.calls: list[str] = []

    def delete_upload(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        storage_key: str,
    ) -> ObjectDeletionOutcome:
        del claim_id, storage_key
        self.calls.append(evidence_id)

        return self.outcomes[evidence_id].pop(0)


def test_retention_restart_retries_only_unsatisfied_target() -> None:
    repository = FixtureRepository()

    operation = _operation(
        targets=[
            _target('1'),
            _target('2'),
        ]
    )

    assert repository.reserve_retention_operation(operation)

    first_storage = _ScriptedStorage(
        {
            'evd-1': [
                ObjectDeletionOutcome.DELETED,
            ],
            'evd-2': [
                ObjectDeletionOutcome.UNKNOWN,
            ],
        }
    )

    first = execute_retention_object_cleanup(
        repository,
        first_storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(minutes=1),
    )

    assert first.status is (RetentionOperationStatus.RECONCILIATION_REQUIRED)
    assert first_storage.calls == [
        'evd-1',
        'evd-2',
    ]

    second_storage = _ScriptedStorage(
        {
            'evd-1': [],
            'evd-2': [
                ObjectDeletionOutcome.ALREADY_ABSENT,
            ],
        }
    )

    second = execute_retention_object_cleanup(
        repository,
        second_storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(minutes=2),
    )

    assert second.status is (RetentionOperationStatus.COMPLETED)
    assert second_storage.calls == ['evd-2']

    evd_1 = [item for item in second.step_evidence if item.target_id == 'target-1']
    evd_2 = [item for item in second.step_evidence if item.target_id == 'target-2']

    assert len(evd_1) == 1
    assert [item.attempt for item in evd_2] == [1, 2]


def test_active_hold_prevents_any_destructive_call() -> None:
    repository = FixtureRepository()
    operation = _operation()

    assert repository.reserve_retention_operation(operation)

    hold = RetentionHoldRecord(
        hold_id='hold-active',
        claim_id=operation.claim_id,
        reason=RetentionHoldReason.LEGAL_HOLD,
        authority_ref='staff:legal-review',
        source_refs=['legal-case:1'],
        applied_at=NOW,
    )

    repository.save_retention_hold(hold)

    storage = _ScriptedStorage(
        {
            'evd-1': [
                ObjectDeletionOutcome.DELETED,
            ]
        }
    )

    held = execute_retention_object_cleanup(
        repository,
        storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(minutes=1),
    )

    assert held.status is RetentionOperationStatus.HELD
    assert storage.calls == []
    assert hold.hold_id in held.hold_refs

    released = hold.model_copy(
        update={
            'released_at': NOW + timedelta(minutes=2),
        }
    )
    repository.save_retention_hold(released)

    completed = execute_retention_object_cleanup(
        repository,
        storage,  # type: ignore[arg-type]
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED
    assert storage.calls == ['evd-1']
