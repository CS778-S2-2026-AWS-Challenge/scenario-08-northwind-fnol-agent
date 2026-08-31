import json
from datetime import datetime
from pathlib import Path
from typing import Any

from backend.domain.knowledge import KnowledgePublicationStatus, KnowledgeSource
from backend.services.knowledge_ingestion import (
    KnowledgeManifestError,
    validate_manifest_source,
)

APPROVED_KNOWLEDGE_MANIFEST = (
    Path(__file__).resolve().parents[2] / 'config' / 'knowledge-sources.json'
)


def _optional_datetime(value: object) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value or value != value.strip():
        raise KnowledgeManifestError(
            'Knowledge manifest effective dates must be null or canonical datetime strings.'
        )
    try:
        return datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise KnowledgeManifestError(
            'Knowledge manifest effective dates must be valid ISO 8601 datetime strings.'
        ) from None


def load_approved_sources(
    path: Path = APPROVED_KNOWLEDGE_MANIFEST,
) -> dict[tuple[str, str], KnowledgeSource]:
    """Load and validate the repository-controlled knowledge source manifest."""

    try:
        value: Any = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise KnowledgeManifestError('Knowledge source manifest cannot be read.') from None
    if not isinstance(value, dict) or not isinstance(value.get('documents'), list):
        raise KnowledgeManifestError('Knowledge source manifest must contain a documents list.')
    sources: dict[tuple[str, str], KnowledgeSource] = {}
    for position, entry in enumerate(value['documents'], start=1):
        if not isinstance(entry, dict):
            raise KnowledgeManifestError(
                f'Knowledge source manifest entry {position} must be an object.'
            )
        try:
            source = KnowledgeSource(
                document_id=entry['document_id'],
                source_key=entry['source_key'],
                title=entry['title'],
                document_type=entry['document_type'],
                version=entry['version'],
                source_uri=entry['source_uri'],
                jurisdiction=entry['jurisdiction'],
                insurer=entry.get('insurer'),
                product=entry.get('product'),
                effective_from=_optional_datetime(entry.get('effective_from')),
                effective_to=_optional_datetime(entry.get('effective_to')),
                authority=entry['authority'],
                visibility=entry['visibility'],
                publication_status=KnowledgePublicationStatus(entry['publication_status']),
                expected_checksum=entry.get('checksum_sha256'),
            )
            validate_manifest_source(source)
        except KnowledgeManifestError:
            raise
        except (KeyError, TypeError, ValueError):
            raise KnowledgeManifestError(
                f'Knowledge source manifest entry {position} is invalid.'
            ) from None
        identity = (source.document_id, source.version)
        if identity in sources:
            raise KnowledgeManifestError('Knowledge source manifest contains a duplicate identity.')
        sources[identity] = source
    return sources
