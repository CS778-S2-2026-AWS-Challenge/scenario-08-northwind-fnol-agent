from typing import Any

import mongomock
import pytest

from scripts.backfill_terminal_dispositions import backfill_terminal_dispositions


def _collection() -> Any:
    return mongomock.MongoClient().northwind.northwind_records


def _seed_legacy_claim(collection: Any, *, decision: bool = True) -> None:
    collection.insert_one(
        {
            '_id': 'claim:clm_legacy',
            'record_type': 'claim',
            'claim_id': 'clm_legacy',
            'customer_id': 'cus_legacy',
            'revision': 5,
            'claim_state': {'workflow_state': 'created'},
            'external_claim_source_revision': 2,
            'external_claim': {
                'external_claim_id': 'ext_legacy',
                'claim_number': 'NWF-LEGACY',
                'creation_status': 'created',
                'created_at': '2026-09-10T23:42:38Z',
            },
            'terminal_disposition': None,
            'updated_at': '2026-09-10T23:43:00Z',
        }
    )
    if decision:
        collection.insert_one(
            {
                '_id': 'agent_decision:dec_creation',
                'record_type': 'agent_decision',
                'decision_id': 'dec_creation',
                'claim_id': 'clm_legacy',
                'customer_id': 'cus_legacy',
                'action': 'CREATE_CLAIM',
                'reason_codes': ['CLAIM_CREATION_AUTHORISED'],
                'authority': {'outcome': 'authorised'},
                'resulting_revision': 2,
                'created_at': '2026-09-10T23:42:30Z',
            }
        )


def test_dry_run_reports_eligible_claim_without_writing() -> None:
    collection = _collection()
    _seed_legacy_claim(collection)

    report = backfill_terminal_dispositions(collection)

    assert report['mode'] == 'dry_run'
    assert report['eligible'] == ['clm_legacy']
    assert report['applied'] == []
    assert collection.find_one({'claim_id': 'clm_legacy'})['terminal_disposition'] is None


def test_apply_preserves_claim_revision_and_is_idempotent() -> None:
    collection = _collection()
    _seed_legacy_claim(collection)

    report = backfill_terminal_dispositions(collection, apply=True)

    assert report['applied'] == ['clm_legacy']
    stored = collection.find_one({'claim_id': 'clm_legacy'})
    assert stored['revision'] == 5
    assert stored['updated_at'] == '2026-09-10T23:43:00Z'
    assert stored['terminal_disposition'] == {
        'value': 'completed',
        'reason_code': 'CLAIM_CREATED',
        'source_refs': ['dec_creation', 'ext_legacy'],
        'recorded_by': {
            'actor_type': 'system',
            'actor_id': 'claims_service_integration',
        },
        'recorded_at': '2026-09-10T23:42:38Z',
        'recorded_revision': 3,
    }
    replay = backfill_terminal_dispositions(collection, apply=True)
    assert replay['candidate_count'] == 0
    assert replay['applied'] == []


@pytest.mark.parametrize(
    ('mutation', 'reason'),
    [
        ('missing_decision', 'Exactly one matching authorised'),
        ('missing_reference', 'external_claim reference is missing'),
        ('future_creation', 'external Claim time exceeds'),
    ],
)
def test_invalid_provenance_is_rejected(mutation: str, reason: str) -> None:
    collection = _collection()
    _seed_legacy_claim(collection, decision=mutation != 'missing_decision')
    if mutation == 'missing_reference':
        collection.update_one(
            {'claim_id': 'clm_legacy'},
            {
                '$set': {
                    'external_claim.external_claim_id': None,
                    'external_claim.claim_number': None,
                }
            },
        )
    if mutation == 'future_creation':
        collection.update_one(
            {'claim_id': 'clm_legacy'},
            {'$set': {'external_claim.created_at': '2026-09-11T00:00:00Z'}},
        )

    report = backfill_terminal_dispositions(collection, apply=True)

    assert report['applied'] == []
    assert reason in report['rejected'][0]['reason']
    assert collection.find_one({'claim_id': 'clm_legacy'})['terminal_disposition'] is None


def test_concurrent_claim_change_prevents_backfill(monkeypatch: pytest.MonkeyPatch) -> None:
    collection = _collection()
    _seed_legacy_claim(collection)
    update_one = collection.update_one

    def race_then_update(query: dict[str, object], update: dict[str, object]) -> Any:
        update_one({'claim_id': 'clm_legacy'}, {'$inc': {'revision': 1}})
        return update_one(query, update)

    monkeypatch.setattr(collection, 'update_one', race_then_update)

    report = backfill_terminal_dispositions(collection, apply=True)

    assert report['conflicts'] == ['clm_legacy']
    assert collection.find_one({'claim_id': 'clm_legacy'})['terminal_disposition'] is None
