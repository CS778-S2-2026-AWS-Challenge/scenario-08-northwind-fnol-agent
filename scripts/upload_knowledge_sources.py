import argparse
import os
import sys
from hashlib import sha256
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.domain.knowledge import KnowledgeSource
from scripts.ingest_knowledge_source import load_approved_sources, required_environment


def approved_source_files(
    source_directory: Path,
    sources: list[KnowledgeSource],
) -> list[tuple[KnowledgeSource, Path]]:
    resolved: list[tuple[KnowledgeSource, Path]] = []
    for source in sources:
        path = source_directory / Path(source.source_key).name
        try:
            payload = path.read_bytes()
        except OSError:
            raise ValueError(f'Approved source file is unavailable: {path.name}') from None
        checksum = sha256(payload).hexdigest()
        if checksum != source.expected_checksum:
            raise ValueError(f'Approved source checksum does not match the manifest: {path.name}')
        resolved.append((source, path))
    return resolved


def ensure_bucket(client: Any, bucket: str) -> None:
    try:
        client.head_bucket(Bucket=bucket)
    except ClientError as error:
        status = error.response.get('ResponseMetadata', {}).get('HTTPStatusCode')
        if status != 404:
            raise
        client.create_bucket(Bucket=bucket)


def main() -> None:
    parser = argparse.ArgumentParser(
        description='Upload checksum-verified approved knowledge sources.'
    )
    parser.add_argument(
        'source_directory',
        type=Path,
        help='Directory containing the approved source Markdown files.',
    )
    arguments = parser.parse_args()
    sources = list(load_approved_sources().values())
    files = approved_source_files(arguments.source_directory, sources)
    client = boto3.client(
        's3',
        endpoint_url=required_environment('NORTHWIND_OBJECT_STORAGE_ENDPOINT'),
        aws_access_key_id=required_environment('NORTHWIND_OBJECT_STORAGE_ACCESS_KEY_ID'),
        aws_secret_access_key=required_environment('NORTHWIND_OBJECT_STORAGE_SECRET_ACCESS_KEY'),
        region_name=os.getenv('NORTHWIND_OBJECT_STORAGE_REGION', 'us-east-1'),
    )
    bucket = os.getenv('NORTHWIND_KNOWLEDGE_BUCKET', 'northwind-knowledge')
    ensure_bucket(client, bucket)
    for source, path in files:
        client.upload_file(
            str(path),
            bucket,
            source.source_key,
            ExtraArgs={'ContentType': 'text/markdown'},
        )
        print(f'uploaded: document={source.document_id} version={source.version}')


if __name__ == '__main__':
    main()
