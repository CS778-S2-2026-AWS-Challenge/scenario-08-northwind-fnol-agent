from datetime import UTC, datetime, timedelta

import mongomock
import pytest

from backend.adapters.evidence_storage import (
    EvidenceStorageUnavailable,
    MockEvidenceStorage,
)
from backend.domain.audit import (
    AuditEventType,
    AuditSubject,
    AuditSubjectType,
)
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
    ResourceAccessClosed,
    RetentionClassification,
    RetentionDatabaseStepError,
    RetentionEligibilityReason,
    RetentionEligibilityRejected,
    RetentionHoldReason,
    RetentionHoldRecord,
    RetentionOperation,
    RetentionOperationStatus,
    RetentionProjectedContentState,
    RetentionStepStatus,
    RetentionTargetFreezeReason,
    RetentionTargetFreezeRejected,
    RetentionTargetKind,
    retention_target_statuses,
    retention_terminal_source_ref,
)
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.protocols import (
    IdempotencyRecord,
    PersistenceRepository,
)
from backend.services.retention import (
    execute_retention_cleanup,
    freeze_retention_cleanup_targets,
    project_claimant_retention,
    project_staff_retention,
    reserve_retention_from_terminal,
)

NOW = datetime(2026, 9, 29, 0, 30, tzinfo=UTC)


def _repository(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> PersistenceRepository:
    if kind == 'fixture':
        return FixtureRepository()

    repository = MongoDBRepository(
        mongomock.MongoClient(),
        f'retention_eligibility_{kind}',
    )

    monkeypatch.setattr(
        repository,
        '_atomic',
        lambda operation: operation(None),
    )

    return repository


def _claim(
    claim_id: str,
) -> WorkingClaim:
    return WorkingClaim(
        claim_id=claim_id,
        customer_id='cus_retention',
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


def _session(
    claim: WorkingClaim,
) -> SessionRecord:
    return SessionRecord(
        session_id=claim.active_session_id or '',
        claim_id=claim.claim_id,
        customer_id=claim.customer_id,
        context_revision=claim.revision,
        started_at=NOW,
        last_active_at=NOW,
    )


def _terminalise(
    repository: PersistenceRepository,
    claim: WorkingClaim,
) -> WorkingClaim:
    timestamp = NOW + timedelta(minutes=1)

    terminal = ClaimTerminalDisposition(
        value=TerminalDispositionValue.ABANDONED,
        reason_code=(TerminalDispositionReasonCode.RECOVERY_EXPIRED),
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
    )

    updated = claim.model_copy(
        update={
            'revision': claim.revision + 1,
            'terminal_disposition': terminal,
            'customer_next_step': CustomerNextStep(
                status='recovery_expired',
                summary='Recovery expired.',
                responsible_party=ResponsibleParty.SYSTEM,
                can_resume=False,
            ),
            'updated_at': timestamp,
        }
    )

    repository.save_claim(
        updated,
        expected_revision=claim.revision,
    )

    return updated


def _operation(
    claim: WorkingClaim,
    *,
    source_revision: int | None = None,
) -> RetentionOperation:
    terminal = claim.terminal_disposition
    assert terminal is not None

    source_ref = retention_terminal_source_ref(
        claim.claim_id,
        terminal.recorded_revision,
    )

    return RetentionOperation(
        operation_id=f'ret_manual_{claim.claim_id}',
        claim_id=claim.claim_id,
        source_terminal_ref=source_ref,
        source_claim_revision=(source_revision if source_revision is not None else claim.revision),
        policy_id=INCOMPLETE_CLAIM_RETENTION_POLICY_ID,
        policy_version=(INCOMPLETE_CLAIM_RETENTION_POLICY_VERSION),
        revision=1,
        status=RetentionOperationStatus.RESERVED,
        access_closed_at=NOW + timedelta(minutes=2),
        source_refs=[
            source_ref,
            *terminal.source_refs,
        ],
        created_at=NOW + timedelta(minutes=2),
        updated_at=NOW + timedelta(minutes=2),
    )


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_terminal_retention_reservation_has_provider_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_eligible_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    assert operation.status is RetentionOperationStatus.RESERVED
    assert operation.source_claim_revision == claim.revision
    assert operation.source_terminal_ref == retention_terminal_source_ref(
        claim.claim_id,
        claim.revision,
    )

    # Access closes immediately at reservation.
    assert (
        repository.get_claim(
            claim.claim_id,
            claim.customer_id,
        )
        is None
    )

    # Internal retention authority still sees the terminal Claim.
    assert repository.get_claim_internal(claim.claim_id) == claim

    replay = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=5),
    )

    assert replay == operation


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_non_terminal_claim_is_not_retention_eligible(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    claim = _claim(f'clm_nonterminal_{kind}')

    repository.create_claim(
        claim,
        _session(claim),
    )

    with pytest.raises(RetentionEligibilityRejected) as caught:
        reserve_retention_from_terminal(
            repository,
            claim.claim_id,
            now=NOW + timedelta(minutes=2),
        )

    assert caught.value.reason is RetentionEligibilityReason.TERMINAL_REQUIRED

    assert (
        repository.get_claim(
            claim.claim_id,
            claim.customer_id,
        )
        == claim
    )


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_stale_terminal_revision_fails_closed(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_stale_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    claim = _terminalise(
        repository,
        base,
    )

    stale = _operation(
        claim,
        source_revision=claim.revision - 1,
    )

    with pytest.raises(RetentionEligibilityRejected) as caught:
        repository.reserve_eligible_retention_operation(stale)

    assert caught.value.reason is RetentionEligibilityReason.SOURCE_REVISION_MISMATCH

    assert repository.get_retention_operation_for_claim(claim.claim_id) is None


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_active_hold_closes_access_but_blocks_destructive_progress(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_hold_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    claim = _terminalise(
        repository,
        base,
    )

    hold = RetentionHoldRecord(
        hold_id=f'hold_{claim.claim_id}',
        claim_id=claim.claim_id,
        reason=RetentionHoldReason.INVESTIGATION,
        authority_ref='staff:investigation',
        source_refs=[
            'staff:investigation',
        ],
        applied_at=NOW + timedelta(minutes=1),
    )

    repository.save_retention_hold(hold)

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    assert operation.status is RetentionOperationStatus.HELD
    assert operation.hold_refs == [hold.hold_id]

    # A hold pauses destruction. It does not restore claimant access.
    assert (
        repository.get_claim(
            claim.claim_id,
            claim.customer_id,
        )
        is None
    )


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_unknown_external_outcome_blocks_retention_reservation(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_external_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    task = ExternalTaskRecord(
        task_id=f'ext_{kind}',
        claim_id=base.claim_id,
        service_identity=('vehicle_damage_assessment_routing'),
        requested_action='vehicle_damage_assessment',
        integration_source=IntegrationSource.FIXTURE,
        status=ExternalTaskOperationStatus.UNKNOWN_OUTCOME,
        delivery=ExternalTaskDelivery.SUBMITTED,
        delivery_evidence='fixture:submitted',
        failure_code=ExternalTaskFailureCode.TIMEOUT,
        created_at=NOW + timedelta(seconds=10),
        updated_at=NOW + timedelta(seconds=10),
    )

    repository.save_external_task(
        task,
        base.customer_id,
    )

    claim = _terminalise(
        repository,
        base,
    )

    with pytest.raises(RetentionEligibilityRejected) as caught:
        reserve_retention_from_terminal(
            repository,
            claim.claim_id,
            now=NOW + timedelta(minutes=2),
        )

    assert caught.value.reason is RetentionEligibilityReason.EXTERNAL_OUTCOME_UNKNOWN

    assert repository.get_retention_operation_for_claim(claim.claim_id) is None


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_cleanup_target_freeze_has_provider_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_targets_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    evidence = EvidenceRecord(
        evidence_id=f'evd_targets_{kind}',
        claim_id=base.claim_id,
        kind='other_document',
        status=EvidenceStatus.PENDING,
        file_status=EvidenceFileStatus.AWAITING_UPLOAD,
        original_filename='retention.jpg',
        media_type='image/jpeg',
        size_bytes=7,
        source=EvidenceSource.CLAIMANT,
        provenance={'storage_key': (f'claims/{base.claim_id}/evidence/evd_targets_{kind}')},
        created_at=NOW + timedelta(seconds=10),
        updated_at=NOW + timedelta(seconds=10),
    )

    repository.save_evidence(
        evidence,
        base.customer_id,
    )

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    assert frozen.revision == operation.revision + 1
    assert frozen.targets_frozen_at == NOW + timedelta(minutes=3)

    observed = {
        (
            target.kind,
            target.record_type,
            target.record_id,
            target.classification,
            target.storage_key,
        )
        for target in frozen.targets
    }

    expected = {
        (
            RetentionTargetKind.MONGO_RECORD,
            'WorkingClaim',
            claim.claim_id,
            RetentionClassification.ANONYMISE,
            None,
        ),
        (
            RetentionTargetKind.MONGO_RECORD,
            'SessionRecord',
            base.active_session_id,
            RetentionClassification.ANONYMISE,
            None,
        ),
        (
            RetentionTargetKind.MONGO_RECORD,
            'EvidenceRecord',
            evidence.evidence_id,
            RetentionClassification.ANONYMISE,
            None,
        ),
        (
            RetentionTargetKind.OBJECT_BYTES,
            'EvidenceObjectBytes',
            evidence.evidence_id,
            RetentionClassification.DELETE,
            evidence.provenance['storage_key'],
        ),
    }

    assert observed == expected

    replay = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=10),
    )

    assert replay == frozen
    assert replay.targets_frozen_at == frozen.targets_frozen_at


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_active_hold_prevents_target_freeze_until_release(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_freeze_hold_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    claim = _terminalise(
        repository,
        base,
    )

    hold = RetentionHoldRecord(
        hold_id=f'hold_freeze_{kind}',
        claim_id=claim.claim_id,
        reason=RetentionHoldReason.INVESTIGATION,
        authority_ref='staff:investigation',
        source_refs=['staff:investigation'],
        applied_at=NOW + timedelta(minutes=1),
    )

    repository.save_retention_hold(hold)

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    assert operation.status is RetentionOperationStatus.HELD

    with pytest.raises(RetentionTargetFreezeRejected) as caught:
        freeze_retention_cleanup_targets(
            repository,
            operation.operation_id,
            now=NOW + timedelta(minutes=3),
        )

    assert caught.value.reason is RetentionTargetFreezeReason.ACTIVE_HOLD

    unchanged = repository.get_retention_operation(operation.operation_id)

    assert unchanged is not None
    assert unchanged.targets_frozen_at is None
    assert unchanged.targets == []

    repository.save_retention_hold(
        hold.model_copy(update={'released_at': (NOW + timedelta(minutes=4))})
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=5),
    )

    assert frozen.status is RetentionOperationStatus.RESERVED
    assert frozen.targets_frozen_at is not None
    assert frozen.hold_refs == [hold.hold_id]


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_full_retention_cleanup_is_object_first_and_provider_parity(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_cleanup_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    storage = MockEvidenceStorage()

    stored = storage.store_generated_content(
        claim_id=base.claim_id,
        evidence_id=f'evd_cleanup_{kind}',
        content=b'cleanup',
        media_type='image/jpeg',
    )

    evidence = EvidenceRecord(
        evidence_id=f'evd_cleanup_{kind}',
        claim_id=base.claim_id,
        kind='other_document',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        original_filename='sensitive.jpg',
        media_type='image/jpeg',
        size_bytes=7,
        source=EvidenceSource.CLAIMANT,
        provenance={
            'storage_key': stored.storage_key,
            'upload_checksum': stored.checksum,
        },
        claimant_note='claimant-sensitive note',
        created_at=NOW + timedelta(seconds=10),
        updated_at=NOW + timedelta(seconds=10),
    )

    repository.save_evidence(
        evidence,
        base.customer_id,
    )

    idempotency = IdempotencyRecord(
        actor_id=base.customer_id,
        route=f'/api/v1/claims/{base.claim_id}/evidence',
        key=f'idem_cleanup_{kind}',
        request_fingerprint='fingerprint',
        claim_id=base.claim_id,
        session_id=base.active_session_id or '',
        response_payload={
            'sensitive': 'payload',
        },
    )

    repository.save_idempotency(idempotency)

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    completed = execute_retention_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=4),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED

    statuses = retention_target_statuses(
        completed.targets,
        completed.step_evidence,
    )

    assert statuses
    assert all(status is RetentionStepStatus.SATISFIED for status in statuses.values())

    # Bytes were destroyed before Evidence/Claim metadata disappeared.
    assert (
        storage.read_upload(
            claim_id=claim.claim_id,
            evidence_id=evidence.evidence_id,
            storage_key=stored.storage_key,
        )
        is None
    )

    # The normal business authority is no longer returned internally.
    assert repository.get_claim_internal(claim.claim_id) is None

    claim_target = next(
        target for target in completed.targets if target.record_type == 'WorkingClaim'
    )

    claim_tombstone = repository.get_retention_tombstone(claim_target.target_id)

    assert claim_tombstone is not None
    assert claim_tombstone.authority == {
        'revision': claim.revision,
    }

    evidence_target = next(
        target for target in completed.targets if target.record_type == 'EvidenceRecord'
    )

    evidence_tombstone = repository.get_retention_tombstone(evidence_target.target_id)

    assert evidence_tombstone is not None
    assert 'claimant_note' not in evidence_tombstone.authority
    assert 'provenance' not in evidence_tombstone.authority

    # The old retry identity still resolves to the retention closure rather
    # than looking unused and allowing resurrection.
    with pytest.raises(ResourceAccessClosed):
        repository.find_idempotency(
            idempotency.actor_id,
            idempotency.route,
            idempotency.key,
        )

    replay = execute_retention_cleanup(
        repository,
        storage,
        completed.operation_id,
        now=NOW + timedelta(minutes=10),
    )

    assert replay == completed


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_object_failure_stops_database_cleanup_and_restart_finishes_same_operation(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_restart_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    storage = MockEvidenceStorage()

    stored = storage.store_generated_content(
        claim_id=base.claim_id,
        evidence_id=f'evd_restart_{kind}',
        content=b'restart',
        media_type='image/jpeg',
    )

    evidence = EvidenceRecord(
        evidence_id=f'evd_restart_{kind}',
        claim_id=base.claim_id,
        kind='other_document',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        original_filename='restart.jpg',
        media_type='image/jpeg',
        size_bytes=7,
        source=EvidenceSource.CLAIMANT,
        provenance={
            'storage_key': stored.storage_key,
            'upload_checksum': stored.checksum,
        },
        created_at=NOW + timedelta(seconds=10),
        updated_at=NOW + timedelta(seconds=10),
    )

    repository.save_evidence(
        evidence,
        base.customer_id,
    )

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    storage.set_outage(
        EvidenceStorageUnavailable(
            'fixture_outage',
            'simulated retention delete outage',
        )
    )

    failed = execute_retention_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=4),
    )

    assert failed.status is RetentionOperationStatus.RECONCILIATION_REQUIRED

    # Database content remains intact because object cleanup did not succeed.
    assert repository.get_claim_internal(claim.claim_id) == claim

    failed_statuses = retention_target_statuses(
        failed.targets,
        failed.step_evidence,
    )

    assert all(
        failed_statuses[target.target_id] is RetentionStepStatus.PENDING
        for target in failed.targets
        if target.kind is RetentionTargetKind.MONGO_RECORD
    )

    storage.set_outage(None)

    completed = execute_retention_cleanup(
        repository,
        storage,
        failed.operation_id,
        now=NOW + timedelta(minutes=5),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED
    assert repository.get_claim_internal(claim.claim_id) is None

    object_target = next(
        target for target in completed.targets if target.kind is RetentionTargetKind.OBJECT_BYTES
    )

    attempts = [
        step for step in completed.step_evidence if step.target_id == object_target.target_id
    ]

    assert [step.attempt for step in attempts] == [1, 2]
    assert attempts[0].status is RetentionStepStatus.FAILED
    assert attempts[1].status is RetentionStepStatus.SATISFIED


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_retention_closes_claimant_retry_without_retiring_internal_retry(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_idem_scope_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    claimant_record = IdempotencyRecord(
        actor_id=base.customer_id,
        route=f'/api/v1/claims/{base.claim_id}',
        key=f'claimant_retry_{kind}',
        request_fingerprint='claimant-fingerprint',
        claim_id=base.claim_id,
        session_id=base.active_session_id or '',
        response_payload={
            'claimant_sensitive': 'result',
        },
    )

    internal_record = IdempotencyRecord(
        actor_id='system-retention-regression',
        route='/internal/reconcile',
        key=f'internal_retry_{kind}',
        request_fingerprint='internal-fingerprint',
        claim_id=base.claim_id,
        session_id=base.active_session_id or '',
        response_payload={
            'authority': 'internal-replay',
        },
    )

    repository.save_idempotency(claimant_record)
    repository.save_idempotency(internal_record)

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    with pytest.raises(ResourceAccessClosed):
        repository.find_idempotency(
            claimant_record.actor_id,
            claimant_record.route,
            claimant_record.key,
        )

    assert (
        repository.find_idempotency(
            internal_record.actor_id,
            internal_record.route,
            internal_record.key,
        )
        == internal_record
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    idempotency_targets = [
        target for target in frozen.targets if target.record_type == 'IdempotencyRecord'
    ]

    assert len(idempotency_targets) == 1


@pytest.mark.parametrize(
    ('kind', 'commit_unknown', 'expected_event'),
    [
        (
            'fixture',
            False,
            AuditEventType.ACTION_FAILED,
        ),
        (
            'fixture',
            True,
            AuditEventType.ACTION_UNKNOWN_OUTCOME,
        ),
        (
            'mongodb',
            False,
            AuditEventType.ACTION_FAILED,
        ),
        (
            'mongodb',
            True,
            AuditEventType.ACTION_UNKNOWN_OUTCOME,
        ),
    ],
)
def test_database_failure_requires_reconciliation_and_retries_same_operation(
    kind: str,
    commit_unknown: bool,
    expected_event: AuditEventType,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(kind, monkeypatch)
    base = _claim(f'clm_db_reconcile_{kind}_{int(commit_unknown)}')

    repository.create_claim(
        base,
        _session(base),
    )

    claim = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        claim.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    original_apply = repository.apply_retention_record_target

    state: dict[str, bool | str | None] = {
        'failed': False,
        'target_id': None,
    }

    def fail_once(
        operation_id: str,
        target_id: str,
        expected_revision: int,
        *,
        now: datetime,
    ) -> RetentionOperation:
        if not state['failed']:
            state['failed'] = True
            state['target_id'] = target_id

            raise RetentionDatabaseStepError(
                target_id,
                commit_unknown=commit_unknown,
                diagnostic_code=(
                    'TEST_DATABASE_COMMIT_UNKNOWN'
                    if commit_unknown
                    else 'TEST_DATABASE_NOT_COMMITTED'
                ),
            )

        return original_apply(
            operation_id,
            target_id,
            expected_revision,
            now=now,
        )

    monkeypatch.setattr(
        repository,
        'apply_retention_record_target',
        fail_once,
    )

    storage = MockEvidenceStorage()

    interrupted = execute_retention_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=4),
    )

    assert interrupted.status is RetentionOperationStatus.RECONCILIATION_REQUIRED

    failed_target_id = state['target_id']
    assert isinstance(
        failed_target_id,
        str,
    )

    failed_steps = [
        step for step in interrupted.step_evidence if step.target_id == failed_target_id
    ]

    assert len(failed_steps) == 1
    assert failed_steps[0].status is (
        RetentionStepStatus.UNKNOWN if commit_unknown else RetentionStepStatus.FAILED
    )

    # No destructive mutation was asserted successful for the failed target.
    assert repository.get_claim_internal(claim.claim_id) == claim

    subject = AuditSubject(
        subject_type=AuditSubjectType.CLAIM,
        subject_id=claim.claim_id,
        claim_id=claim.claim_id,
    )

    events = repository.list_audit_events_internal(subject)

    retention_events = [
        event
        for event in events
        if (f'retention-operation:{operation.operation_id}' in event.source_refs)
    ]

    assert any(event.event_type is AuditEventType.ACTION_PREPARED for event in retention_events)

    assert any(event.event_type is expected_event for event in retention_events)

    monkeypatch.setattr(
        repository,
        'apply_retention_record_target',
        original_apply,
    )

    completed = execute_retention_cleanup(
        repository,
        storage,
        interrupted.operation_id,
        now=NOW + timedelta(minutes=5),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED

    retry_steps = [step for step in completed.step_evidence if step.target_id == failed_target_id]

    assert [step.attempt for step in retry_steps] == [1, 2]

    assert retry_steps[-1].status is RetentionStepStatus.SATISFIED

    events = repository.list_audit_events_internal(subject)

    retention_events = [
        event
        for event in events
        if (f'retention-operation:{operation.operation_id}' in event.source_refs)
    ]

    assert any(event.event_type is AuditEventType.ACTION_COMPLETED for event in retention_events)

    # Completion replay must not append a conflicting duplicate audit fact.
    replay = execute_retention_cleanup(
        repository,
        storage,
        completed.operation_id,
        now=NOW + timedelta(minutes=10),
    )

    assert replay == completed


@pytest.mark.parametrize(
    'kind',
    ['fixture', 'mongodb'],
)
def test_retention_projection_e2e_is_role_safe_after_cleanup(
    kind: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository(
        kind,
        monkeypatch,
    )

    base = _claim(f'clm_projection_{kind}')

    repository.create_claim(
        base,
        _session(base),
    )

    storage = MockEvidenceStorage()

    stored = storage.store_generated_content(
        claim_id=base.claim_id,
        evidence_id=f'evd_projection_{kind}',
        content=b'projection-evidence',
        media_type='image/jpeg',
    )

    evidence = EvidenceRecord(
        evidence_id=f'evd_projection_{kind}',
        claim_id=base.claim_id,
        kind='other_document',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.READY,
        original_filename='private-projection.jpg',
        media_type='image/jpeg',
        size_bytes=len(b'projection-evidence'),
        source=EvidenceSource.CLAIMANT,
        provenance={
            'storage_key': stored.storage_key,
            'upload_checksum': stored.checksum,
        },
        claimant_note=('must never appear in retention projection'),
        created_at=NOW + timedelta(seconds=10),
        updated_at=NOW + timedelta(seconds=10),
    )

    repository.save_evidence(
        evidence,
        base.customer_id,
    )

    terminal = _terminalise(
        repository,
        base,
    )

    operation = reserve_retention_from_terminal(
        repository,
        terminal.claim_id,
        now=NOW + timedelta(minutes=2),
    )

    claimant_projection = project_claimant_retention(
        repository,
        terminal.claim_id,
    )

    assert claimant_projection is not None
    assert claimant_projection.availability is RetentionProjectedContentState.UNAVAILABLE

    claimant_json = claimant_projection.model_dump_json()

    for forbidden in (
        'storage_key',
        'diagnostic',
        'policy_id',
        'policy_version',
        'source_refs',
        'hold',
        operation.operation_id,
    ):
        assert forbidden not in claimant_json

    frozen = freeze_retention_cleanup_targets(
        repository,
        operation.operation_id,
        now=NOW + timedelta(minutes=3),
    )

    before_cleanup = project_staff_retention(
        repository,
        terminal.claim_id,
    )

    assert before_cleanup is not None

    assert any(
        item.record_type == 'WorkingClaim'
        and item.content_state is RetentionProjectedContentState.UNAVAILABLE
        for item in before_cleanup.resources
    )

    completed = execute_retention_cleanup(
        repository,
        storage,
        frozen.operation_id,
        now=NOW + timedelta(minutes=4),
    )

    assert completed.status is RetentionOperationStatus.COMPLETED

    assert repository.get_claim_internal(terminal.claim_id) is None

    final_projection = project_staff_retention(
        repository,
        terminal.claim_id,
    )

    assert final_projection is not None

    assert final_projection.operation_status is RetentionOperationStatus.COMPLETED

    assert final_projection.completed_at is not None
    assert not final_projection.hold_active
    assert not final_projection.reconciliation_required

    states = {
        (
            item.record_type,
            item.content_state,
        )
        for item in final_projection.resources
    }

    assert (
        'WorkingClaim',
        RetentionProjectedContentState.ANONYMISED,
    ) in states

    assert (
        'SessionRecord',
        RetentionProjectedContentState.ANONYMISED,
    ) in states

    assert (
        'EvidenceRecord',
        RetentionProjectedContentState.ANONYMISED,
    ) in states

    assert any(
        item.content_state is RetentionProjectedContentState.DELETED
        for item in final_projection.resources
    )

    assert (
        'RetentionOperation',
        RetentionProjectedContentState.RETAINED_FOR_AUDIT,
    ) in states

    staff_json = final_projection.model_dump_json()

    for forbidden in (
        'storage_key',
        'upload_checksum',
        'claimant_note',
        'diagnostic_code',
        'policy_id',
        'policy_version',
        'source_refs',
        stored.storage_key,
    ):
        assert forbidden not in staff_json

    replay = execute_retention_cleanup(
        repository,
        storage,
        completed.operation_id,
        now=NOW + timedelta(minutes=10),
    )

    assert replay == completed

    replay_projection = project_staff_retention(
        repository,
        terminal.claim_id,
    )

    assert replay_projection == final_projection
