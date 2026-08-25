from typing import Any, cast

from botocore.exceptions import BotoCoreError, ClientError


class KnowledgeObjectStoreUnavailable(RuntimeError):
    pass


class S3CompatibleKnowledgeObjectStore:
    def __init__(self, client: Any, bucket: str) -> None:
        self._client = client
        self._bucket = bucket

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
