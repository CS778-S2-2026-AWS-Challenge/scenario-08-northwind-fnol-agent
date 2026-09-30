"""Run the bounded P17 recovery worker against the configured data profile."""

from __future__ import annotations

import argparse
import json
import logging
import signal
from collections.abc import Callable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime
from threading import Event
from types import FrameType

from backend.adapters.evidence_storage import EvidenceStorage
from backend.core.config import Settings
from backend.core.runtime_profiles import DataRuntimeBundle, build_data_runtime_bundle
from backend.repositories.protocols import PersistenceRepository
from backend.services.recovery_worker import RecoveryCycleResult, run_recovery_cycle

LOGGER = logging.getLogger(__name__)
DEFAULT_INTERVAL_SECONDS = 30.0
MAX_INTERVAL_SECONDS = 3600.0


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _configured_bundle() -> DataRuntimeBundle:
    return build_data_runtime_bundle(Settings.from_environment())


def _emit_json(result: RecoveryCycleResult) -> None:
    print(json.dumps(asdict(result), sort_keys=True), flush=True)


def run_worker(
    repository: PersistenceRepository,
    storage: EvidenceStorage,
    *,
    limit: int,
    interval_seconds: float,
    once: bool,
    stop_event: Event | None = None,
    now_fn: Callable[[], datetime] = _utc_now,
    emit: Callable[[RecoveryCycleResult], None] = _emit_json,
) -> int:
    """Run bounded recovery cycles until one cycle completes or shutdown is requested.

    Each cycle owns at most one configured page for expiry, retention and due-contact
    discovery. A failed cycle is logged and isolated from later cycles; durable
    repository state is reloaded by the next cycle. Signal ownership stays in main
    so this function remains deterministic in tests.
    """

    if not 1 <= limit <= 100:
        raise ValueError('Recovery worker limit must be between 1 and 100.')
    if not 0 < interval_seconds <= MAX_INTERVAL_SECONDS:
        raise ValueError(
            f'Recovery worker interval must be greater than 0 and at most {MAX_INTERVAL_SECONDS}.'
        )

    stop = stop_event or Event()

    while not stop.is_set():
        try:
            result = run_recovery_cycle(
                repository,
                storage,
                now=now_fn(),
                limit=limit,
            )
        except Exception:
            LOGGER.exception('P17 recovery cycle failed; durable work remains eligible for retry.')
            if once:
                return 1
        else:
            emit(result)
            if once:
                return 0

        if stop.wait(interval_seconds):
            break

    return 0


def _install_signal_handlers(stop_event: Event) -> None:
    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        LOGGER.info('Received signal %s; recovery worker will stop after the current cycle.', signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_shutdown)
    if hasattr(signal, 'SIGTERM'):
        signal.signal(signal.SIGTERM, request_shutdown)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        '--limit',
        type=int,
        default=50,
        help='maximum candidates processed per discovery class in one cycle (1-100)',
    )
    parser.add_argument(
        '--interval-seconds',
        type=float,
        default=DEFAULT_INTERVAL_SECONDS,
        help='loop delay between bounded cycles; ignored after a successful --once cycle',
    )
    parser.add_argument(
        '--once',
        action='store_true',
        help='run exactly one bounded cycle for an external scheduler and exit',
    )
    args = parser.parse_args(argv)

    stop_event = Event()
    if not args.once:
        _install_signal_handlers(stop_event)

    bundle = _configured_bundle()
    try:
        return run_worker(
            bundle.repository,
            bundle.evidence_storage,
            limit=args.limit,
            interval_seconds=args.interval_seconds,
            once=args.once,
            stop_event=stop_event,
            now_fn=_utc_now,
        )
    finally:
        bundle.close()


if __name__ == '__main__':
    raise SystemExit(main())
