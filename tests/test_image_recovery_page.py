"""Bounded recovery discovery contract with in-memory and Mongo mock providers."""

from datetime import UTC, datetime
from unittest.mock import Mock

import mongomock
import pytest

from backend.domain.models import EvidenceFileStatus, EvidenceRecord, EvidenceSource, EvidenceStatus
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository


@pytest.fixture(params=['fixture', 'mongodb_mock'])
def repository(request: pytest.FixtureRequest) -> FixtureRepository | MongoDBRepository:
    store = (
        FixtureRepository()
        if request.param == 'fixture'
        else MongoDBRepository(mongomock.MongoClient(), 'image_recovery_page')
    )
    now = datetime(2026, 9, 29, tzinfo=UTC)
    # Deliberately reverse insertion order. Discovery includes non-image / ready records;
    # eligibility is the service's responsibility and must not make database reads unbounded.
    for number in reversed(range(55)):
        record = EvidenceRecord(
            evidence_id=f'evd_{number:03d}',
            claim_id='clm_page',
            kind='photo',
            status=EvidenceStatus.RECEIVED,
            file_status=EvidenceFileStatus.READY if number % 2 else EvidenceFileStatus.PROCESSING,
            media_type='application/pdf' if number % 3 else 'image/png',
            source=EvidenceSource.CLAIMANT,
            created_at=now,
            updated_at=now,
        )
        if isinstance(store, FixtureRepository):
            store._evidence[record.evidence_id] = record
        else:
            store._collection.insert_one(
                {
                    **record.model_dump(mode='json'),
                    '_id': f'evidence:{record.evidence_id}',
                    'record_type': 'evidence',
                }
            )
    return store


def test_pages_resume_after_deleted_cursor_without_duplicates(
    repository: FixtureRepository | MongoDBRepository,
) -> None:
    first = repository.list_evidence_recovery_page(limit=10)
    cursor = first[-1].evidence_id
    if isinstance(repository, FixtureRepository):
        del repository._evidence[cursor]
        del repository._evidence['evd_010']
    else:
        repository._collection.delete_many(
            {'_id': {'$in': [f'evidence:{cursor}', 'evidence:evd_010']}}
        )
        repository._collection.insert_one({'_id': 'evidence_claim_link:unrelated'})
    identities = [record.evidence_id for record in first]
    while page := repository.list_evidence_recovery_page(cursor, limit=10):
        identities.extend(record.evidence_id for record in page)
        cursor = page[-1].evidence_id
    assert identities == [f'evd_{number:03d}' for number in range(55) if number != 10]
    assert repository.list_evidence_recovery_page(cursor) == []


@pytest.mark.parametrize(('limit', 'expected'), [(-1, 1), (0, 1), (1, 1), (10, 10), (100, 50)])
def test_page_limit_bounds(
    repository: FixtureRepository | MongoDBRepository, limit: int, expected: int
) -> None:
    page = repository.list_evidence_recovery_page(limit=limit)
    assert len(page) == expected
    assert page[0].evidence_id == 'evd_000'
    page[0].kind = 'caller mutation'
    assert repository.list_evidence_recovery_page(limit=1)[0].kind == 'photo'


def test_inconsistent_identity_cannot_repeat_a_cursor(
    repository: FixtureRepository | MongoDBRepository,
) -> None:
    if isinstance(repository, FixtureRepository):
        repository._evidence['evd_000'].evidence_id = 'evd_wrong'
    else:
        repository._collection.update_one(
            {'_id': 'evidence:evd_000'}, {'$set': {'evidence_id': 'evd_wrong'}}
        )
    with pytest.raises(ValueError, match='identity'):
        repository.list_evidence_recovery_page(limit=1)


def test_mongodb_discovery_uses_bounded_primary_index_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'image_recovery_query')
    cursor = Mock()
    cursor.hint.return_value = cursor
    cursor.sort.return_value = cursor
    cursor.limit.return_value = []
    find = Mock(return_value=cursor)
    monkeypatch.setattr(repository._collection, 'find', find)
    assert repository.list_evidence_recovery_page('evd_009', 100) == []
    find.assert_called_once_with({'_id': {'$gt': 'evidence:evd_009', '$lt': 'evidence;'}})
    cursor.hint.assert_called_once_with('_id_')
    cursor.sort.assert_called_once_with('_id', 1)
    cursor.limit.assert_called_once_with(50)
