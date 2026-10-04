"""Repeatable worker lifecycle and retry regressions; no external providers."""

from datetime import UTC, datetime, timedelta
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
from backend.services.image_recovery import EvidenceProcessingWorker, ImageRecoveryWorker
from backend.services.support import now_utc


def _record(evidence_id: str = 'evd_1', **updates: object) -> EvidenceRecord:
    record = EvidenceRecord(
        evidence_id=evidence_id,
        claim_id='clm_recovery',
        kind='incident_photo',
        status=EvidenceStatus.RECEIVED,
        file_status=EvidenceFileStatus.PROCESSING,
        source=EvidenceSource.CLAIMANT,
        media_type='image/png',
        provenance={'processing_state': 'queued'},
        created_at=datetime(2026, 9, 29, tzinfo=UTC),
        updated_at=datetime(2026, 9, 29, tzinfo=UTC),
    )
    return record.model_copy(update=updates)


def _pdf_record(evidence_id: str = 'evd_pdf', **updates: object) -> EvidenceRecord:
    return _record(evidence_id).model_copy(
        update={
            'kind': 'police_report',
            'media_type': 'application/pdf',
            **updates,
        }
    )


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


def test_orphan_and_unexpected_provider_failure_do_not_skip_later_images(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.return_value = [
        _record('evd_orphan'),
        _record('evd_error'),
        _record('evd_valid'),
    ]
    repository.get_claim_internal.side_effect = [None, Mock(revision=7), Mock(revision=8)]
    repair = Mock(side_effect=[RuntimeError('private-provider-payload'), None])
    monkeypatch.setattr('backend.services.image_recovery.repair_processing_image', repair)
    worker = ImageRecoveryWorker(cast(PersistenceRepository, repository), MockEvidenceStorage())
    assert worker.run_once() == 60.0
    assert [call.args[3] for call in repair.call_args_list] == ['evd_error', 'evd_valid']
    assert repair.call_args.args[4] == 8
    assert repair.call_args.kwargs['apply'] is True
    assert 'private-provider-payload' not in caplog.text


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


def test_pdf_requires_processor_and_running_lease_must_expire_before_dispatch() -> None:
    repository = _repository()
    processor = Mock()
    repository.list_evidence_recovery_page.return_value = [_pdf_record()]

    EvidenceProcessingWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage()
    ).run_once()
    processor.process.assert_not_called()

    repository.reset_mock()
    repository.get_claim_internal.return_value = Mock(revision=7)
    repository.list_evidence_recovery_page.return_value = [
        _pdf_record(
            provenance={
                'processing_state': 'running',
                'processing_lease_expires_at': (now_utc() + timedelta(minutes=1)).isoformat(),
            }
        )
    ]
    EvidenceProcessingWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage(), processor
    ).run_once()
    processor.process.assert_not_called()

    for lease in (None, 'not-a-timestamp'):
        repository.list_evidence_recovery_page.return_value = [
            _pdf_record(
                provenance={
                    'processing_state': 'running',
                    'processing_lease_expires_at': lease,
                }
            )
        ]
        EvidenceProcessingWorker(
            cast(PersistenceRepository, repository), MockEvidenceStorage(), processor
        ).run_once()
    processor.process.assert_not_called()

    repository.list_evidence_recovery_page.return_value = [
        _pdf_record(
            provenance={
                'processing_state': 'running',
                'processing_lease_expires_at': (now_utc() - timedelta(seconds=1)).isoformat(),
            }
        )
    ]
    EvidenceProcessingWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage(), processor
    ).run_once()
    processor.process.assert_called_once()


def test_poison_pdf_does_not_starve_later_pdf_record() -> None:
    repository = _repository()
    repository.list_evidence_recovery_page.return_value = [
        _pdf_record('evd_poison'),
        _pdf_record('evd_valid'),
    ]
    processor = Mock(
        **{
            'process.side_effect': [
                ApiError(
                    status_code=409,
                    code='REVISION_CONFLICT',
                    message='synthetic conflict',
                    retryable=True,
                ),
                None,
            ]
        }
    )

    EvidenceProcessingWorker(
        cast(PersistenceRepository, repository), MockEvidenceStorage(), processor
    ).run_once()

    assert [call.args[0].evidence_id for call in processor.process.call_args_list] == [
        'evd_poison',
        'evd_valid',
    ]


def test_wake_interrupts_full_sweep_wait() -> None:
    repository = _repository()
    first_sweep = Event()
    second_sweep = Event()

    def page(**kwargs: object) -> list[EvidenceRecord]:
        if repository.list_evidence_recovery_page.call_count == 1:
            first_sweep.set()
        else:
            second_sweep.set()
        return []

    repository.list_evidence_recovery_page.side_effect = page
    worker = EvidenceProcessingWorker(
        cast(PersistenceRepository, repository),
        MockEvidenceStorage(),
        sweep_interval_seconds=60,
    )
    worker.start()
    try:
        assert first_sweep.wait(2)
        worker.wake()
        assert second_sweep.wait(2)
    finally:
        worker.stop()
