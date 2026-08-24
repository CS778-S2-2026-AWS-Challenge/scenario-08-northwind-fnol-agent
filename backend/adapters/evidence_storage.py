import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlparse

import boto3
from botocore.client import Config as BotoClientConfig
from botocore.exceptions import BotoCoreError, ClientError

from backend.services.support import now_utc

MAX_UPLOAD_SIZE_BYTES = 10_485_760
ALLOWED_MEDIA_TYPES = ('image/jpeg', 'image/png', 'application/pdf')
DEFAULT_PRESIGN_EXPIRY_SECONDS = 900
MAX_PRESIGN_EXPIRY_SECONDS = 604_800
_BUCKET_NAME = re.compile(r'^[a-z0-9](?:[a-z0-9.-]{1,61}[a-z0-9])?$')


class EvidenceStorageError(Exception):
    """Base class for replaceable evidence-storage adapter failures."""


class UnsupportedEvidenceMediaType(EvidenceStorageError):
    pass


class EvidenceUploadTooLarge(EvidenceStorageError):
    pass


class EvidenceUploadNotFound(EvidenceStorageError):
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
class S3CompatibleObjectStorageConfig:
    """Environment-backed connection contract shared by MinIO and S3."""

    endpoint_url: str
    access_key_id: str = field(repr=False)
    secret_access_key: str = field(repr=False)
    bucket: str
    region: str = 'us-east-1'
    presign_expiry_seconds: int = DEFAULT_PRESIGN_EXPIRY_SECONDS

    def __post_init__(self) -> None:
        parsed = urlparse(self.endpoint_url)
        if parsed.scheme not in {'http', 'https'} or not parsed.netloc:
            raise ValueError('endpoint_url must be an absolute HTTP(S) URL.')
        if parsed.username is not None or parsed.password is not None:
            raise ValueError('endpoint_url must not contain embedded credentials.')
        if not self.access_key_id.strip() or not self.secret_access_key.strip():
            raise ValueError('access_key_id and secret_access_key must be non-empty.')
        if not _BUCKET_NAME.fullmatch(self.bucket):
            raise ValueError('bucket must be a valid lowercase S3 bucket name.')
        if not self.region.strip():
            raise ValueError('region must be non-empty.')
        if not 1 <= self.presign_expiry_seconds <= MAX_PRESIGN_EXPIRY_SECONDS:
            raise ValueError(
                f'presign_expiry_seconds must be between 1 and {MAX_PRESIGN_EXPIRY_SECONDS}.'
            )

    @classmethod
    def from_environment(cls) -> 'S3CompatibleObjectStorageConfig':
        """Read the runtime connection values from the process environment.

        Secret values are intentionally required at runtime and are never given
        source-controlled defaults.
        """

        required = {
            'NORTHWIND_OBJECT_STORAGE_ENDPOINT': os.getenv('NORTHWIND_OBJECT_STORAGE_ENDPOINT'),
            'NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID': os.getenv(
                'NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'
            ),
            'NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY': os.getenv(
                'NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'
            ),
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(f'Missing object-storage settings: {", ".join(missing)}.')
        raw_expiry = os.getenv(
            'NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS',
            str(DEFAULT_PRESIGN_EXPIRY_SECONDS),
        )
        try:
            expiry = int(raw_expiry)
        except ValueError as error:
            raise ValueError(
                'NORTHWIND_OBJECT_STORAGE_PRESIGN_EXPIRY_SECONDS must be an integer.'
            ) from error
        return cls(
            endpoint_url=required['NORTHWIND_OBJECT_STORAGE_ENDPOINT'] or '',
            access_key_id=required['NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'] or '',
            secret_access_key=required['NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'] or '',
            bucket=os.getenv('NORTHWIND_OBJECT_STORAGE_BUCKET', 'northwind-evidence'),
            region=os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1'),
            presign_expiry_seconds=expiry,
        )


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
    source_id: str


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
        }
        self._pending.clear()
        self._completed.clear()
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
        self._guard()
        pending = self._pending.get((claim_id, evidence_id))
        if pending is None or pending.media_type != media_type or pending.size_bytes != size_bytes:
            raise EvidenceUploadNotFound(evidence_id)
        completed = StoredUpload(
            storage_key=pending.storage_key,
            checksum=checksum,
            source_id='fixture_evidence_storage',
        )
        self._completed[(claim_id, evidence_id)] = completed
        return completed

    def completed_upload(self, claim_id: str, evidence_id: str) -> StoredUpload | None:
        return self._completed.get((claim_id, evidence_id))


class MinioEvidenceStorage(EvidenceStorage):
    """S3-compatible evidence object adapter for a local MinIO endpoint.

    The same adapter can target AWS S3 by changing only the endpoint and
    credentials. Domain services receive only the provider-neutral
    ``EvidenceStorage`` contract and never see bucket names or SDK types.
    """

    max_size_bytes = MAX_UPLOAD_SIZE_BYTES
    allowed_media_types = ALLOWED_MEDIA_TYPES

    def __init__(self, config: S3CompatibleObjectStorageConfig, client: Any = None) -> None:
        self._config = config
        self._client = client or boto3.client(
            's3',
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
            config=BotoClientConfig(signature_version='s3v4'),
        )

    @staticmethod
    def _storage_key(claim_id: str, evidence_id: str) -> str:
        if not claim_id or '/' in claim_id or '\\' in claim_id:
            raise ValueError('claim_id must be a non-empty path-safe identifier.')
        if not evidence_id or '/' in evidence_id or '\\' in evidence_id:
            raise ValueError('evidence_id must be a non-empty path-safe identifier.')
        return f'claims/{claim_id}/evidence/{evidence_id}/staging'

    @classmethod
    def _final_storage_key(cls, claim_id: str, evidence_id: str, checksum: str) -> str:
        digest = checksum.removeprefix('sha256:').lower()
        if not re.fullmatch(r'[0-9a-f]{64}', digest):
            raise EvidenceUploadNotFound(evidence_id)
        staging_key = cls._storage_key(claim_id, evidence_id)
        return f'{staging_key.removesuffix("/staging")}/finalised/{digest}'

    @staticmethod
    def _metadata(
        claim_id: str, evidence_id: str, media_type: str, size_bytes: int
    ) -> dict[str, str]:
        return {
            'claim-id': claim_id,
            'evidence-id': evidence_id,
            'media-type': media_type,
            'expected-size': str(size_bytes),
        }

    @staticmethod
    def _not_found(error: ClientError) -> bool:
        code = str(error.response.get('Error', {}).get('Code', ''))
        return code in {'404', 'NotFound', 'NoSuchKey'}

    @staticmethod
    def _unavailable(operation: str, error: Exception) -> EvidenceStorageUnavailable:
        return EvidenceStorageUnavailable(
            code='OBJECT_STORAGE_UNAVAILABLE',
            detail=f'Object storage is unavailable while attempting to {operation}.',
        )

    def connection_status(self) -> str:
        try:
            self._client.head_bucket(Bucket=self._config.bucket)
        except (BotoCoreError, ClientError):
            return 'unavailable'
        return 'configured_service'

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
        if size_bytes < 0 or size_bytes > self.max_size_bytes:
            raise EvidenceUploadTooLarge(size_bytes)
        storage_key = self._storage_key(claim_id, evidence_id)
        metadata = self._metadata(claim_id, evidence_id, media_type, size_bytes)
        try:
            url = self._client.generate_presigned_url(
                'put_object',
                Params={
                    'Bucket': self._config.bucket,
                    'Key': storage_key,
                    'ContentType': media_type,
                    'Metadata': metadata,
                },
                ExpiresIn=self._config.presign_expiry_seconds,
                HttpMethod='PUT',
            )
        except (BotoCoreError, ClientError) as error:
            raise self._unavailable('create an upload target', error) from error
        return StoredUploadTarget(
            method='PUT',
            url=str(url),
            headers={
                'Content-Type': media_type,
                **{f'x-amz-meta-{key}': value for key, value in metadata.items()},
            },
            expires_at=now_utc() + timedelta(seconds=self._config.presign_expiry_seconds),
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
        staging_key = self._storage_key(claim_id, evidence_id)
        final_key = self._final_storage_key(claim_id, evidence_id, checksum)

        # A retry after the final copy (for example after a repository failure)
        # can recover from the immutable object without requiring staging bytes.
        try:
            self._verify_object(
                storage_key=final_key,
                evidence_id=evidence_id,
                claim_id=claim_id,
                checksum=checksum,
                media_type=media_type,
                size_bytes=size_bytes,
            )
            return StoredUpload(
                storage_key=final_key,
                checksum=checksum.lower(),
                source_id='s3_compatible_evidence_storage',
            )
        except EvidenceUploadNotFound:
            pass

        verified_checksum = self._verify_object(
            storage_key=staging_key,
            evidence_id=evidence_id,
            claim_id=claim_id,
            checksum=checksum,
            media_type=media_type,
            size_bytes=size_bytes,
        )
        try:
            self._client.copy_object(
                Bucket=self._config.bucket,
                Key=final_key,
                CopySource={'Bucket': self._config.bucket, 'Key': staging_key},
            )
            # Re-read the copied object so a concurrent staging overwrite cannot
            # bind the evidence record to bytes other than those just verified.
            self._verify_object(
                storage_key=final_key,
                evidence_id=evidence_id,
                claim_id=claim_id,
                checksum=verified_checksum,
                media_type=media_type,
                size_bytes=size_bytes,
            )
            self._client.delete_object(Bucket=self._config.bucket, Key=staging_key)
        except ClientError as error:
            raise self._unavailable('finalise the uploaded object', error) from error
        except BotoCoreError as error:
            raise self._unavailable('finalise the uploaded object', error) from error
        return StoredUpload(
            storage_key=final_key,
            checksum=verified_checksum,
            source_id='s3_compatible_evidence_storage',
        )

    def _verify_object(
        self,
        *,
        storage_key: str,
        evidence_id: str,
        claim_id: str,
        checksum: str,
        media_type: str,
        size_bytes: int,
    ) -> str:
        try:
            response = self._client.get_object(Bucket=self._config.bucket, Key=storage_key)
            body = response.get('Body')
            if body is None or not callable(getattr(body, 'read', None)):
                raise EvidenceUploadNotFound(evidence_id)
            try:
                metadata = {
                    str(key).lower(): str(value)
                    for key, value in (response.get('Metadata') or {}).items()
                }
                if (
                    response.get('ContentLength') != size_bytes
                    or response.get('ContentType') != media_type
                    or metadata.get('claim-id') != claim_id
                    or metadata.get('evidence-id') != evidence_id
                ):
                    raise EvidenceUploadNotFound(evidence_id)
                digest = sha256()
                actual_size = 0
                while chunk := body.read(64 * 1024):
                    if not isinstance(chunk, bytes):
                        raise EvidenceUploadNotFound(evidence_id)
                    digest.update(chunk)
                    actual_size += len(chunk)
                    if actual_size > size_bytes or actual_size > self.max_size_bytes:
                        raise EvidenceUploadNotFound(evidence_id)
            finally:
                close = getattr(body, 'close', None)
                if callable(close):
                    close()
        except ClientError as error:
            if self._not_found(error):
                raise EvidenceUploadNotFound(evidence_id) from error
            raise self._unavailable('verify the uploaded object', error) from error
        except BotoCoreError as error:
            raise self._unavailable('verify the uploaded object', error) from error

        if actual_size != size_bytes:
            raise EvidenceUploadNotFound(evidence_id)
        verified_checksum = f'sha256:{digest.hexdigest()}'
        if checksum.lower() != verified_checksum:
            raise EvidenceUploadNotFound(evidence_id)
        return verified_checksum
