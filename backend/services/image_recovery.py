"""Bounded background recovery of legacy claimant images awaiting validation."""

import logging
from threading import Event, Thread

from backend.adapters.evidence_storage import EvidenceStorage
from backend.core.errors import ApiError
from backend.domain.models import (
    EvidenceFileStatus,
    EvidenceHistoryState,
    EvidenceRecord,
    EvidenceSource,
    EvidenceStatus,
)
from backend.repositories.protocols import PersistenceRepository
from backend.services.evidence import repair_processing_image
from backend.services.image_readiness import IMAGE_MEDIA_TYPES

logger = logging.getLogger(__name__)


def _eligible(record: EvidenceRecord) -> bool:
    return (
        record.source is EvidenceSource.CLAIMANT
        and record.status is EvidenceStatus.RECEIVED
        and record.file_status is EvidenceFileStatus.PROCESSING
        and record.media_type in IMAGE_MEDIA_TYPES
        and record.claimant_history_state is EvidenceHistoryState.AVAILABLE
        and record.provenance.get('processing_state') == 'queued'
        and not record.provenance.get('extraction_state')
    )


class ImageRecoveryWorker:
    """Sweep bounded pages without performing object-store I/O on request threads."""

    def __init__(
        self,
        repository: PersistenceRepository,
        storage: EvidenceStorage,
        *,
        page_size: int = 10,
        page_interval_seconds: float = 5.0,
        sweep_interval_seconds: float = 60.0,
    ) -> None:
        if not 1 <= page_size <= 50:
            raise ValueError('Image recovery page size must be between 1 and 50.')
        if page_interval_seconds <= 0 or sweep_interval_seconds <= 0:
            raise ValueError('Image recovery intervals must be positive.')
        self._repository = repository
        self._storage = storage
        self._page_size = page_size
        self._page_interval_seconds = page_interval_seconds
        self._sweep_interval_seconds = sweep_interval_seconds
        self._cursor: str | None = None
        self._stop = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start one process-local worker; repeated startup is harmless.

        Returns:
            None. Discovery and validation run on the background thread.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name='image-recovery', daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop between records and wait for in-flight storage work before closing dependencies.

        Returns:
            None, after the worker can no longer access its repository or storage.
        """
        self._stop.set()
        if self._thread is not None:
            self._thread.join()
            self._thread = None

    def run_once(self) -> float:
        """Process one bounded page, isolating unavailable or concurrently changed records.

        Returns:
            Seconds until the next page or full sweep. Failed reads retain the cursor;
            individual failures advance it and are retried on the next full sweep.
        """
        if self._stop.is_set():
            return self._sweep_interval_seconds
        try:
            records = self._repository.list_evidence_recovery_page(
                after_evidence_id=self._cursor, limit=self._page_size
            )
        except Exception:
            # Provider exceptions can contain connection strings. This is the
            # background isolation boundary; log neither their text nor traceback.
            logger.warning('image_recovery_page_unavailable')
            return self._sweep_interval_seconds
        for record in records:
            if self._stop.is_set():
                return self._sweep_interval_seconds
            self._cursor = record.evidence_id
            if not _eligible(record):
                continue
            try:
                claim = self._repository.get_claim_internal(record.claim_id)
                if claim is None:
                    continue
                repair_processing_image(
                    self._repository,
                    self._storage,
                    record.claim_id,
                    record.evidence_id,
                    claim.revision,
                    record.material_version,
                    apply=True,
                )
            except ApiError:
                # CAS conflicts, missing objects, and transient storage failures
                # remain eligible for a later sweep without overwriting authority.
                logger.info('image_recovery_record_deferred')
            except Exception:
                logger.warning('image_recovery_record_unavailable')
        if len(records) < self._page_size:
            self._cursor = None
            return self._sweep_interval_seconds
        return self._page_interval_seconds

    def _run(self) -> None:
        while not self._stop.is_set():
            if self._stop.wait(self.run_once()):
                return
