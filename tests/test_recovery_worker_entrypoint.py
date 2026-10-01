"""Bounds, failure isolation and shutdown for the deployable P17 recovery worker."""

import json
import signal
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Event
from types import SimpleNamespace
from typing import Any

import pytest

import backend.recovery_worker_main as worker_main
import backend.services.recovery_worker as recovery_worker
from backend.core.config import Settings
from backend.domain.retention import (
    RetentionEligibilityReason,
    RetentionEligibilityRejected,
    RetentionTargetFreezeReason,
    RetentionTargetFreezeRejected,
)
from backend.services.recovery_worker import RecoveryCycleResult, run_recovery_cycle

NOW = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)
RESULT = RecoveryCycleResult(
    expiring_candidates=0,
    expired=0,
    due_candidates=0,
    contacted=0,
    retention_progressed=0,
    retention_blocked=0,
    failed_candidates=0,
)


@pytest.mark.parametrize(
    ('limit', 'interval', 'reason'),
    [
        (0, 1.0, 'limit'),
        (101, 1.0, 'limit'),
        (1, 0.0, 'interval'),
        (1, worker_main.MAX_INTERVAL_SECONDS + 1, 'interval'),
    ],
)
def test_worker_rejects_unbounded_configuration(limit: int, interval: float, reason: str) -> None:
    with pytest.raises(ValueError, match=reason):
        worker_main.run_worker(
            object(),  # type: ignore[arg-type]
            object(),  # type: ignore[arg-type]
            limit=limit,
            interval_seconds=interval,
            once=True,
        )


def test_single_cycle_failure_exits_non_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*_args: Any, **_kwargs: Any) -> RecoveryCycleResult:
        raise RuntimeError('repository unavailable')

    monkeypatch.setattr(worker_main, 'run_recovery_cycle', fail)

    code = worker_main.run_worker(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        limit=5,
        interval_seconds=1.0,
        once=True,
        now_fn=lambda: NOW,
    )

    assert code == 1


def test_loop_isolates_a_failed_cycle_and_stops_on_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[datetime] = []
    stop = Event()

    def cycle(*_args: Any, now: datetime, limit: int, **_kwargs: Any) -> RecoveryCycleResult:
        calls.append(now)
        assert limit == 7
        if len(calls) == 1:
            raise RuntimeError('transient failure')
        return RESULT

    emitted: list[RecoveryCycleResult] = []

    def emit(result: RecoveryCycleResult) -> None:
        emitted.append(result)
        stop.set()

    monkeypatch.setattr(worker_main, 'run_recovery_cycle', cycle)

    code = worker_main.run_worker(
        object(),  # type: ignore[arg-type]
        object(),  # type: ignore[arg-type]
        limit=7,
        interval_seconds=0.001,
        once=False,
        stop_event=stop,
        now_fn=lambda: NOW,
        emit=emit,
    )

    assert code == 0
    assert len(calls) == 2
    assert emitted == [RESULT]


def test_emitted_cycle_result_is_one_json_line(capsys: pytest.CaptureFixture[str]) -> None:
    worker_main._emit_json(RESULT)

    assert json.loads(capsys.readouterr().out) == {
        'contacted': 0,
        'due_candidates': 0,
        'expired': 0,
        'expiring_candidates': 0,
        'failed_candidates': 0,
        'retention_blocked': 0,
        'retention_progressed': 0,
    }
    assert worker_main._utc_now().utcoffset() is not None


def test_signal_handlers_request_graceful_shutdown(monkeypatch: pytest.MonkeyPatch) -> None:
    handlers: dict[int, Any] = {}
    monkeypatch.setattr(
        signal, 'signal', lambda signum, handler: handlers.setdefault(signum, handler)
    )
    stop = Event()

    worker_main._install_signal_handlers(stop)

    assert signal.SIGINT in handlers
    handlers[signal.SIGINT](signal.SIGINT, None)
    assert stop.is_set()


@dataclass
class _Bundle:
    repository: object = field(default_factory=object)
    evidence_storage: object = field(default_factory=object)
    closed: bool = False

    def close(self) -> None:
        self.closed = True


@pytest.mark.parametrize('once', [True, False])
def test_main_runs_configured_profile_and_always_closes_it(
    monkeypatch: pytest.MonkeyPatch,
    once: bool,
) -> None:
    bundle = _Bundle()
    installed: list[Event] = []
    seen: dict[str, Any] = {}

    def run_worker(repository: object, storage: object, **kwargs: Any) -> int:
        assert repository is bundle.repository
        assert storage is bundle.evidence_storage
        seen.update(kwargs)
        if not once:
            raise RuntimeError('stop')
        return 0

    monkeypatch.setattr(worker_main, '_configured_bundle', lambda: bundle)
    monkeypatch.setattr(worker_main, '_install_signal_handlers', installed.append)
    monkeypatch.setattr(worker_main, 'run_worker', run_worker)

    argv = ['--limit', '9', '--interval-seconds', '2.5', *(['--once'] if once else [])]
    if once:
        assert worker_main.main(argv) == 0
    else:
        with pytest.raises(RuntimeError):
            worker_main.main(argv)

    assert bundle.closed is True
    assert seen['limit'] == 9
    assert seen['interval_seconds'] == 2.5
    assert seen['once'] is once
    # A one-shot scheduler invocation leaves signal ownership to its caller.
    assert (installed != []) is (not once)


def test_configured_bundle_uses_environment_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = object()
    bundle = _Bundle()
    monkeypatch.setattr(Settings, 'from_environment', lambda: settings)
    monkeypatch.setattr(
        worker_main,
        'build_data_runtime_bundle',
        lambda value: bundle if value is settings else None,
    )

    configured: object = worker_main._configured_bundle()
    assert configured is bundle


class _Repository:
    def __init__(self) -> None:
        self.expiring = [SimpleNamespace(follow_up_id='fup_expiring')]
        self.retention = [
            SimpleNamespace(operation_id='ret_blocked', targets_frozen_at=None),
            SimpleNamespace(operation_id='ret_broken', targets_frozen_at=NOW),
        ]
        self.due = [
            SimpleNamespace(follow_up_id='fup_broken'),
            SimpleNamespace(follow_up_id='fup_ok'),
        ]

    def list_expiring_follow_ups(self, _now: datetime, *, limit: int) -> tuple[list[Any], None]:
        return self.expiring, None

    def list_pending_retention_operations(self, *, limit: int) -> list[Any]:
        return self.retention

    def list_due_follow_ups(self, _now: datetime, *, limit: int) -> tuple[list[Any], None]:
        return self.due, None

    def list_retention_handoff_candidates(self, *, limit: int) -> list[str]:
        return ['clm_expired']


def test_cycle_rejects_naive_time_and_unbounded_page() -> None:
    repository: Any = _Repository()

    with pytest.raises(ValueError, match='timezone-aware'):
        run_recovery_cycle(repository, object(), now=NOW.replace(tzinfo=None))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match='between 1 and 100'):
        run_recovery_cycle(repository, object(), now=NOW, limit=0)  # type: ignore[arg-type]


def test_cycle_counts_blocked_and_failed_candidates_without_stopping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def expire(_repository: Any, _candidate: Any, _now: datetime) -> Any:
        return SimpleNamespace(claim=SimpleNamespace(claim_id='clm_expired'))

    def reserve(*_args: Any, **_kwargs: Any) -> None:
        raise RetentionEligibilityRejected(
            RetentionEligibilityReason.EXTERNAL_OUTCOME_UNKNOWN, 'clm_expired'
        )

    def freeze(_repository: Any, operation_id: str, *, now: datetime) -> Any:
        raise RetentionTargetFreezeRejected(RetentionTargetFreezeReason.ACTIVE_HOLD, operation_id)

    def execute(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError('object store unavailable')

    def due(_repository: Any, candidate: Any, _now: datetime) -> object:
        if candidate.follow_up_id == 'fup_broken':
            raise RuntimeError('broken snapshot')
        return object()

    monkeypatch.setattr(recovery_worker, 'process_expiring_follow_up', expire)
    monkeypatch.setattr(recovery_worker, 'reserve_retention_from_terminal', reserve)
    monkeypatch.setattr(recovery_worker, 'freeze_retention_cleanup_targets', freeze)
    monkeypatch.setattr(recovery_worker, 'execute_retention_cleanup', execute)
    monkeypatch.setattr(recovery_worker, 'process_due_follow_up', due)

    result = run_recovery_cycle(_Repository(), object(), now=NOW, limit=5)  # type: ignore[arg-type]

    assert result == RecoveryCycleResult(
        expiring_candidates=1,
        expired=1,
        due_candidates=2,
        contacted=1,
        retention_progressed=0,
        retention_blocked=2,
        failed_candidates=2,
    )
