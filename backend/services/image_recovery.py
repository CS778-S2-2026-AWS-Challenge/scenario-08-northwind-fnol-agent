"""One bounded worker for queued image validation and PDF processing."""

import logging
from datetime import datetime
from threading import Event, Thread
from typing import Protocol

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
from backend.services.support import now_utc

logger = logging.getLogger(__name__)


class PdfProcessor(Protocol):
    def process(self, record: EvidenceRecord, claim_revision: int) -> None:
        """Process one current claimant-owned PDF generation."""


def _eligible_image(record: EvidenceRecord) -> bool:
    return (
        record.source is EvidenceSource.CLAIMANT
        and record.status is EvidenceStatus.RECEIVED
        and record.file_status is EvidenceFileStatus.PROCESSING
        and record.media_type in IMAGE_MEDIA_TYPES
        and record.claimant_history_state is EvidenceHistoryState.AVAILABLE
        and record.provenance.get('processing_state') == 'queued'
        and not record.provenance.get('extraction_state')
    )


def _eligible_pdf(record: EvidenceRecord) -> bool:
    if (
        record.source is not EvidenceSource.CLAIMANT
        or record.status is not EvidenceStatus.RECEIVED
        or record.file_status is not EvidenceFileStatus.PROCESSING
        or record.media_type != 'application/pdf'
        or record.claimant_history_state is not EvidenceHistoryState.AVAILABLE
        or record.provenance.get('extraction_state')
    ):
        return False
    state = record.provenance.get('processing_state')
    if state == 'queued':
        return True
    if state != 'running':
        return False
    expires_at = record.provenance.get('processing_lease_expires_at')
    if not isinstance(expires_at, str):
        return False
    try:
        return datetime.fromisoformat(expires_at) <= now_utc()
    except ValueError:
        return False


class EvidenceProcessingWorker:
    """Sweep bounded pages without performing provider I/O on request threads."""

    def __init__(
        self,
        repository: PersistenceRepository,
        storage: EvidenceStorage,
        pdf_processor: PdfProcessor | None = None,
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
        self._pdf_processor = pdf_processor
        self._page_size = page_size
        self._page_interval_seconds = page_interval_seconds
        self._sweep_interval_seconds = sweep_interval_seconds
        self._cursor: str | None = None
        self._stop = Event()
        self._wake = Event()
        self._thread: Thread | None = None

    def start(self) -> None:
        """Start one process-local worker; repeated startup is harmless.

        Returns:
            None. Discovery and validation run on the background thread.
        """
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = Thread(target=self._run, name='evidence-processing', daemon=True)
        self._thread.start()

    def wake(self) -> None:
        """Request an early bounded sweep after a durable upload completion."""

        self._wake.set()

    def stop(self) -> None:
        """Stop between records and wait for in-flight storage work before closing dependencies.

        Returns:
            None, after the worker can no longer access its repository or storage.
        """
        self._stop.set()
        self._wake.set()
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
            image = _eligible_image(record)
            pdf = self._pdf_processor is not None and _eligible_pdf(record)
            if not image and not pdf:
                continue
            try:
                claim = self._repository.get_claim_internal(record.claim_id)
                if claim is None:
                    continue
                if image:
                    repair_processing_image(
                        self._repository,
                        self._storage,
                        record.claim_id,
                        record.evidence_id,
                        claim.revision,
                        record.material_version,
                        apply=True,
                    )
                elif self._pdf_processor is not None:
                    self._pdf_processor.process(record, claim.revision)
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
            delay = self.run_once()
            self._wake.wait(delay)
            self._wake.clear()


# Compatibility name for operator scripts and focused regressions written before PDF support.
ImageRecoveryWorker = EvidenceProcessingWorker
