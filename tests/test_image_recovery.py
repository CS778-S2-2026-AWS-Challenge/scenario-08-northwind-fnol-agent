"""Repeatable worker lifecycle and retry regressions; no external providers."""

from datetime import UTC, datetime
from threading import Event, Thread
from typing import cast
from unittest.mock import Mock

import pytest

from backend.adapters.evidence_storage import MockEvidenceStorage
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.core.errors import ApiError
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceHistoryState,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.image_recovery import ImageRecoveryWorker


def _record(evidence_id: str = 'evd_1', **updates: object) -> EvidenceRecord:
    record = EvidenceRecord(
        evidence_id=evidence_id,
        claim_id='clm_recovery',
        kind='incident_image',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.PROCESSING,
        source=EvidenceSource.CLAIMANT,
        media_type='image/png',
        provenance={'processing_state': 'queued'},
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
        updated_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    return record.model_copy(update=updates)


def _repository() -> Mock:
    repository = Mock(spec=PersistenceRepository)
    repository.get_claim_internal.return_value = Mock(revision=7)
    return repository


@pytest.mark.parametrize('error_code', ['REVISION_CONFLICT', 'DEPENDENCY_UNAVAILABLE'])
def test_poison_head_advances_and_transient_failure_retries_next_sweep(
    monkeypatch: pytest.MonkeyPatch, error_code: str
) -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.side_effect = [
        [_record('evd_1')],
        [_record('evd_2')],
        [],
        [_record('evd_1')],
    ]
    attempts: list[str] = []

    def repair(*args: object, **kwargs: object) -> None:
        evidence_id = str(args[3])
        attempts.append(evidence_id)
        if len(attempts) == 1:
            raise ApiError(
                status_code=409 if error_code == 'REVISION_CONFLICT' else 503,
                code=error_code,
                message='synthetic transient failure',
                retryable=True,
            )

    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', repair)
    worker = ImageRecoveryWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage(), page_size=1
    )
    assert [worker.run_once() for _ in range(4)] == [5.0, 5.0, 60.0, 5.0]
    assert attempts == ['evd_1', 'evd_2', 'evd_1']
    assert [
        call.kwargs['after_evidence_id']
        for call in repository.list_evidence_recovery_page.call_args_list
    ] == [None, 'evd_1', 'evd_2', None]


def test_discovery_outage_preserves_cursor_and_does_not_log_provider_secrets(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.side_effect = [
        [_record('evd_1')],
        RuntimeError('mongodb://private-credential'),
        [],
    ]
    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', Mock())
    worker = ImageRecoveryWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage(), page_size=1
    )
    assert [worker.run_once() for _ in range(3)] == [5.0, 60.0, 60.0]
    assert [
        call.kwargs['after_evidence_id']
        for call in repository.list_evidence_recovery_page.call_args_list
    ] == [None, 'evd_1', 'evd_1']
    assert 'private-credential' not in caplog.text


@pytest.mark.parametrize(
    'updates',
    [
        {'media_type': 'application/pdf'},
        {'source': EvidenceSource.EXTERNAL_SYSTEM},
        {'provenance': {'processing_state': 'queued', 'extraction_state': 'proposed'}},
        {'claimant_history_state': EvidenceHistoryState.REMOVED},
        {'file_status': EvidenceFileStatus.AWAITING_UPLOAD},
        {'file_status': EvidenceFileStatus.READY},
        {'file_status': EvidenceFileStatus.FAILED},
        {'status': EvidenceStatus.INVALID},
        {'provenance': {}},
    ],
)
def test_worker_ignores_records_outside_unprocessed_claimant_image_scope(
    monkeypatch: pytest.MonkeyPatch, updates: dict[str, object]
) -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.return_value = [_record().model_copy(update=updates)]
    repair = Mock()
    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', repair)
    ImageRecoveryWorker(cast(PersistenceRepository, repository), MockEvidenceStorage()).run_once()
    repair.assert_not_called()
    repository.get_claim_internal.assert_not_called()


def test_new_worker_rereads_current_state_and_does_not_repeat_settled_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()
    current = [_record()]
    repository.list_evidence_recovery_page.side_effect = lambda **kwargs: list(current)
    repair = Mock(side_effect=lambda *args, **kwargs: current.clear())
    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', repair)
    ImageRecoveryWorker(cast(PersistenceRepository, repository), MockEvidenceStorage()).run_once()
    ImageRecoveryWorker(cast(PersistenceRepository, repository), MockEvidenceStorage()).run_once()
    assert repair.call_count == 1
    assert repository.list_evidence_recovery_page.call_count == 2


def test_stop_waits_for_inflight_repair_and_prevents_next_record(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.return_value = [_record('evd_1'), _record('evd_2')]
    entered, release, stopped = Event(), Event(), Event()
    attempts: list[str] = []

    def repair(*args: object, **kwargs: object) -> None:
        attempts.append(str(args[3]))
        entered.set()
        assert release.wait(5)

    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', repair)
    worker = ImageRecoveryWorker(cast(PersistenceRepository, repository), MockEvidenceStorage())
    worker.start()
    worker.start()
    assert entered.wait(5)

    def stop() -> None:
        worker.stop()
        stopped.set()

    stop_thread = Thread(target=stop)
    stop_thread.start()
    try:
        assert not stopped.wait(0.05)
    finally:
        release.set()
        stop_thread.join(5)
        worker.stop()
    assert stopped.is_set()
    assert attempts == ['evd_1']
    query_count = repository.list_evidence_recovery_page.call_count
    worker.run_once()
    assert repository.list_evidence_recovery_page.call_count == query_count


def test_fixture_profile_does_not_start_background_recovery() -> None:
    app = create_app(Settings(environment='test', identity_mode=IdentityMode.DEVELOPER))
    assert app.state.image_recovery_worker is None
