import os
from dataclasses import dataclass
from typing import Any, cast

import boto3
from botocore.config import Config as BotoClientConfig
from botocore.exceptions import BotoCoreError, ClientError


class KnowledgeObjectStoreUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class S3CompatibleKnowledgeConfig:
    endpoint_url: str
    access_key_id: str
    secret_access_key: str
    bucket: str = 'northwind-knowledge'
    region: str = 'us-east-1'

    @classmethod
    def from_environment(cls) -> 'S3CompatibleKnowledgeConfig':
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
            raise ValueError(f'Missing knowledge-storage settings: {", ".join(missing)}.')
        return cls(
            endpoint_url=required['NORTHWIND_OBJECT_STORAGE_ENDPOINT'] or '',
            access_key_id=required['NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'] or '',
            secret_access_key=required['NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'] or '',
            bucket=os.getenv('NORTHWIND_KNOWLEDGE_BUCKET', 'northwind-knowledge'),
            region=os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1'),
        )


class S3CompatibleKnowledgeObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_config(cls, config: S3CompatibleKnowledgeConfig) -> 'S3CompatibleKnowledgeObjectStore':
        client = boto3.client(
            's3',
            endpoint_url=config.endpoint_url,
            aws_access_key_id=config.access_key_id,
            aws_secret_access_key=config.secret_access_key,
            region_name=config.region,
            config=BotoClientConfig(signature_version='s3v4'),
        )
        return cls(client, config.bucket)

    def read(self, key: str) -> bytes | None:
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=key)
            return cast(bytes, response['Body'].read())
        except ClientError as error:
            if error.response.get('Error', {}).get('Code') in {'404', 'NoSuchKey'}:
                return None
            raise KnowledgeObjectStoreUnavailable(
                'Knowledge object store is unavailable.'
            ) from error
        except BotoCoreError as error:
            raise KnowledgeObjectStoreUnavailable(
                'Knowledge object store is unavailable.'
            ) from error

    def write(self, key: str, data: bytes, *, content_type: str, metadata: dict[str, str]) -> None:
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=metadata,
            )
        except (BotoCoreError, ClientError) as error:
            raise KnowledgeObjectStoreUnavailable(
                'Knowledge object store is unavailable.'
            ) from error
