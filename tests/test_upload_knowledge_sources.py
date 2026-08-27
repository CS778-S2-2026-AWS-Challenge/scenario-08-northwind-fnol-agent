from hashlib import sha256
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from backend.domain.knowledge import KnowledgePublicationStatus, KnowledgeSource
from scripts.upload_knowledge_sources import approved_source_files, ensure_bucket


def source(checksum: str) -> KnowledgeSource:
    return KnowledgeSource(
        document_id='nw-policy-motor',
        source_key='knowledge/policies/policy.md',
        title='Policy',
        document_type='synthetic_policy_wording',
        version='MVP-2026.1',
        source_uri='northwind://synthetic-policy/motor/MVP-2026.1',
        jurisdiction='NZ',
        insurer='Northwind Insurance',
        product='motor',
        effective_from=None,
        effective_to=None,
        authority='northwind_synthetic_demo',
        visibility='customer_and_staff',
        publication_status=KnowledgePublicationStatus.APPROVED,
        expected_checksum=checksum,
    )


def test_approved_source_files_accept_manifest_checksum(tmp_path: Path) -> None:
    payload = b'# Synthetic policy\n'
    path = tmp_path / 'policy.md'
    path.write_bytes(payload)

    files = approved_source_files(tmp_path, [source(sha256(payload).hexdigest())])

    assert files == [(source(sha256(payload).hexdigest()), path)]


def test_approved_source_files_reject_checksum_mismatch(tmp_path: Path) -> None:
    (tmp_path / 'policy.md').write_bytes(b'changed')

    with pytest.raises(ValueError, match='checksum does not match'):
        approved_source_files(tmp_path, [source('0' * 64)])


class BucketClient:
    def __init__(self, status: int | None) -> None:
        self.status = status
        self.created: list[str] = []

    def head_bucket(self, *, Bucket: str) -> None:
        if self.status is not None:
            raise ClientError(
                {
                    'Error': {'Code': str(self.status), 'Message': 'bounded test error'},
                    'ResponseMetadata': {'HTTPStatusCode': self.status},
                },
                'HeadBucket',
            )

    def create_bucket(self, *, Bucket: str) -> None:
        self.created.append(Bucket)


def test_ensure_bucket_creates_only_when_missing() -> None:
    client = BucketClient(404)

    ensure_bucket(client, 'knowledge')

    assert client.created == ['knowledge']


def test_ensure_bucket_preserves_provider_failure() -> None:
    with pytest.raises(ClientError):
        ensure_bucket(BucketClient(503), 'knowledge')
