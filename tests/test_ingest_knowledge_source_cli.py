import json
from pathlib import Path

import pytest

from backend.services.knowledge_ingestion import KnowledgeManifestError
from backend.services.knowledge_manifest import load_approved_sources
from scripts.ingest_knowledge_source import (
    IngestionRequest,
    load_request,
    resolve_source,
)


def write_json(path: Path, value: object) -> Path:
    path.write_text(json.dumps(value), encoding='utf-8')
    return path


def test_identity_only_request_resolves_the_controlled_manifest(tmp_path: Path) -> None:
    manifest = load_approved_sources()
    document_id, version = next(iter(manifest))
    request = load_request(
        write_json(
            tmp_path / 'request.json',
            {'document_id': document_id, 'version': version},
        )
    )

    source = resolve_source(request, manifest)

    assert source == manifest[(request.document_id, request.version)]
    assert source.expected_checksum


def test_request_cannot_supply_governed_metadata(tmp_path: Path) -> None:
    path = write_json(
        tmp_path / 'request.json',
        {
            'document_id': 'nw-motor-2026-1',
            'version': 'MVP-2026.1',
            'publication_status': 'approved',
        },
    )

    with pytest.raises(ValueError, match='only document_id and version'):
        load_request(path)


def test_unknown_identity_cannot_resolve_from_manifest() -> None:
    with pytest.raises(ValueError, match='not registered'):
        resolve_source(IngestionRequest('unknown', 'MVP-2026.1'), load_approved_sources())


@pytest.mark.parametrize(
    ('field', 'value', 'message'),
    [
        ('source_key', 'knowledge/policies/policy.pdf', 'Markdown source'),
        ('source_uri', '', 'source_uri'),
        ('jurisdiction', '', 'jurisdiction'),
        ('jurisdiction', ' NZ ', 'canonical text'),
        ('authority', '', 'authority'),
        ('visibility', 'claimant_only', 'visibility'),
        ('visibility', ' customer_and_staff ', 'canonical text'),
        ('product', None, 'insurer and product'),
        ('effective_to', '2025-12-31T00:00:00Z', 'later than'),
        ('effective_from', {'year': 2026}, 'effective dates'),
        ('effective_from', 0, 'effective dates'),
        ('effective_from', False, 'effective dates'),
        ('effective_from', [], 'effective dates'),
        ('effective_from', ' 2026-01-01T00:00:00Z ', 'effective dates'),
        ('checksum_sha256', 'bad-digest', 'SHA-256'),
    ],
)
def test_manifest_loader_rejects_invalid_governed_entries(
    tmp_path: Path,
    field: str,
    value: object,
    message: str,
) -> None:
    manifest_path = Path('config/knowledge-sources.json')
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    manifest['documents'][0][field] = value

    with pytest.raises(KnowledgeManifestError, match=message):
        load_approved_sources(write_json(tmp_path / 'manifest.json', manifest))
