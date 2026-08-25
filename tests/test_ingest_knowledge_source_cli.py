import json
from pathlib import Path

import pytest

from scripts.ingest_knowledge_source import (
    IngestionRequest,
    load_approved_sources,
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
