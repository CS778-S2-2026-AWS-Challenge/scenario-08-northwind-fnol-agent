from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from backend.services.support import now_utc

MAX_UPLOAD_SIZE_BYTES = 10_485_760
ALLOWED_MEDIA_TYPES = ('image/jpeg', 'image/png', 'application/pdf')


class EvidenceStorageError(Exception):
    """Base class for replaceable evidence-storage adapter failures."""


class UnsupportedEvidenceMediaType(EvidenceStorageError):
    pass


class EvidenceUploadTooLarge(EvidenceStorageError):
    pass


class EvidenceUploadNotFound(EvidenceStorageError):
    pass


class EvidenceUploadSizeMismatch(EvidenceStorageError):
    pass


class EvidenceStorageUnavailable(EvidenceStorageError):
    """The configured object store could not be reached.

    Carried separately from the validation errors above so a transport outage
    is never reported to a claimant as a rejected file.
    """

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True, slots=True)
class StoredUploadTarget:
    method: str
    url: str
    headers: dict[str, str]
    expires_at: datetime
    storage_key: str


@dataclass(frozen=True, slots=True)
class StoredUpload:
    storage_key: str
    checksum: str


class EvidenceStorage(Protocol):
    max_size_bytes: int
    allowed_media_types: tuple[str, ...]

    def connection_status(self) -> str:
        raise NotImplementedError

    def create_upload_target(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUploadTarget:
        raise NotImplementedError

    def complete_upload(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        checksum: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUpload:
        raise NotImplementedError

    def put_upload(self, *, claim_id: str, evidence_id: str, content: bytes) -> None:
        raise NotImplementedError

    def read_upload(self, *, claim_id: str, evidence_id: str) -> bytes | None:
        raise NotImplementedError


@dataclass(frozen=True, slots=True)
class _PendingUpload:
    claim_id: str
    evidence_id: str
    media_type: str
    size_bytes: int
    storage_key: str


class MockEvidenceStorage(EvidenceStorage):
    """In-memory Sprint 1 adapter; no signed URL is persisted in claim fixtures."""

    max_size_bytes = MAX_UPLOAD_SIZE_BYTES
    allowed_media_types = ALLOWED_MEDIA_TYPES

    def __init__(self, outage: EvidenceStorageUnavailable | None = None) -> None:
        self._pending: dict[tuple[str, str], _PendingUpload] = {}
        self._completed: dict[tuple[str, str], StoredUpload] = {}
        self._content: dict[tuple[str, str], bytes] = {}
        self._outage = outage

    def set_outage(self, outage: EvidenceStorageUnavailable | None) -> None:
        self._outage = outage

    def connection_status(self) -> str:
        return 'unavailable' if self._outage is not None else 'using_fixture'

    def _guard(self) -> None:
        if self._outage is not None:
            raise self._outage

    def reset_demo_state(self) -> dict[str, int]:
        cleared = {
            'mock_pending_uploads': len(self._pending),
            'mock_completed_uploads': len(self._completed),
            'mock_uploaded_files': len(self._content),
        }
        self._pending.clear()
        self._completed.clear()
        self._content.clear()
        self._outage = None
        return cleared

    def create_upload_target(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUploadTarget:
        self._guard()
        if media_type not in self.allowed_media_types:
            raise UnsupportedEvidenceMediaType(media_type)
        if size_bytes > self.max_size_bytes:
            raise EvidenceUploadTooLarge(size_bytes)
        storage_key = f'claims/{claim_id}/evidence/{evidence_id}'
        self._pending[(claim_id, evidence_id)] = _PendingUpload(
            claim_id=claim_id,
            evidence_id=evidence_id,
            media_type=media_type,
            size_bytes=size_bytes,
            storage_key=storage_key,
        )
        return StoredUploadTarget(
            method='PUT',
            url=f'/api/v1/claims/{claim_id}/evidence/{evidence_id}/content',
            headers={'Content-Type': media_type},
            expires_at=now_utc() + timedelta(minutes=15),
            storage_key=storage_key,
        )

    def put_upload(self, *, claim_id: str, evidence_id: str, content: bytes) -> None:
        self._guard()
        pending = self._pending.get((claim_id, evidence_id))
        if pending is None:
            raise EvidenceUploadNotFound(evidence_id)
        if len(content) != pending.size_bytes:
            raise EvidenceUploadSizeMismatch(evidence_id)
        self._content[(claim_id, evidence_id)] = content

    def read_upload(self, *, claim_id: str, evidence_id: str) -> bytes | None:
        self._guard()
        if (claim_id, evidence_id) not in self._completed:
            return None
        return self._content.get((claim_id, evidence_id))

    def complete_upload(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        checksum: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUpload:
        self._guard()
        pending = self._pending.get((claim_id, evidence_id))
        if pending is None or pending.media_type != media_type or pending.size_bytes != size_bytes:
            raise EvidenceUploadNotFound(evidence_id)
        completed = StoredUpload(storage_key=pending.storage_key, checksum=checksum)
        self._completed[(claim_id, evidence_id)] = completed
        return completed

    def completed_upload(self, claim_id: str, evidence_id: str) -> StoredUpload | None:
        return self._completed.get((claim_id, evidence_id))
