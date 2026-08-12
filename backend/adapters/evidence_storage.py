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

    def __init__(self) -> None:
        self._pending: dict[tuple[str, str], _PendingUpload] = {}
        self._completed: dict[tuple[str, str], StoredUpload] = {}

    def create_upload_target(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUploadTarget:
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
            url=f'https://example.invalid/uploads/{evidence_id}',
            headers={'Content-Type': media_type},
            expires_at=now_utc() + timedelta(minutes=15),
            storage_key=storage_key,
        )

    def complete_upload(
        self,
        *,
        claim_id: str,
        evidence_id: str,
        checksum: str,
        media_type: str,
        size_bytes: int,
    ) -> StoredUpload:
        pending = self._pending.get((claim_id, evidence_id))
        if pending is None or pending.media_type != media_type or pending.size_bytes != size_bytes:
            raise EvidenceUploadNotFound(evidence_id)
        completed = StoredUpload(storage_key=pending.storage_key, checksum=checksum)
        self._completed[(claim_id, evidence_id)] = completed
        return completed

    def completed_upload(self, claim_id: str, evidence_id: str) -> StoredUpload | None:
        return self._completed.get((claim_id, evidence_id))
