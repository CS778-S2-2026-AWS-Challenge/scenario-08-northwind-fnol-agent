from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest
from pymongo import MongoClient

from scripts.rehearse_mongodb_migration import (
    IDENTITY_FIELDS,
    RECONCILIATION_ISSUES,
    SOURCE_HEAD,
    LocalTarget,
    SnapshotMetadata,
    read_snapshot,
    rehearse_anonymous_promotion,
    transform_snapshot,
)

NOW = datetime(2026, 9, 21, 6, 0, tzinfo=UTC)


def _document(record_type: str, identifier: str, **values: Any) -> dict[str, Any]:
    return {'_id': f'{record_type}:{identifier}', 'record_type': record_type, **values}


def _representative_snapshot() -> list[dict[str, Any]]:
    claim = _document(
        'claim',
        'clm_rehearsal',
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
        revision=3,
        audit_provenance={'source': 'synthetic-rehearsal'},
        created_at=NOW,
        updated_at=NOW,
    )
    session = _document(
        'session',
        'ses_rehearsal',
        session_id='ses_rehearsal',
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
        context_revision=3,
        started_at=NOW,
    )
    message = _document(
        'message',
        'msg_rehearsal',
        message_id='msg_rehearsal',
        client_message_id='client-rehearsal',
        claim_id='clm_rehearsal',
        session_id='ses_rehearsal',
        customer_id='cus_rehearsal',
        created_at=NOW,
    )
    evidence = _document(
        'evidence',
        'evd_rehearsal',
        evidence_id='evd_rehearsal',
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
        revision=1,
    )
    task = _document(
        'external_task',
        'tsk_rehearsal',
        task_id='tsk_rehearsal',
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
    )
    task_link = _document(
        'external_task_evidence_link',
        'clm_rehearsal:evd_rehearsal',
        task_id='tsk_rehearsal',
        evidence_id='evd_rehearsal',
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
        linked_at=NOW,
    )
    idempotency = _document(
        'idempotency',
        'anonymous:browser:/messages:key-1',
        actor_id='anonymous:browser',
        route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
        key='key-1',
        payload={
            'actor_id': 'anonymous:browser',
            'route': '/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
            'key': 'key-1',
            'request_fingerprint': 'fingerprint-1',
            'claim_id': 'clm_rehearsal',
            'session_id': 'ses_rehearsal',
            'message_id': 'msg_rehearsal',
            'message_turn_kind': 'runtime',
            'message_turn_revision': 3,
        },
    )
    second_idempotency = _document(
        'idempotency',
        'anonymous:browser:/claim:key-2',
        actor_id='anonymous:browser',
        route='/api/v1/claims/clm_rehearsal',
        key='key-2',
        payload={
            'actor_id': 'anonymous:browser',
            'route': '/api/v1/claims/clm_rehearsal',
            'key': 'key-2',
            'request_fingerprint': 'fingerprint-2',
            'claim_id': 'clm_rehearsal',
        },
    )
    audit_event = _document(
        'audit_event',
        'aud_rehearsal',
        event_id='aud_rehearsal',
        claim_id='clm_rehearsal',
        action='claim.updated',
        provenance={'source': 'synthetic-rehearsal'},
        created_at=NOW,
    )
    realtime_sequence = _document('realtime_sequence', 'global', sequence=1)
    realtime_event = _document(
        'realtime_event',
        'rte_rehearsal',
        event_id='rte_rehearsal',
        sequence=1,
        claim_id='clm_rehearsal',
        customer_id='cus_rehearsal',
        occurred_at=NOW,
    )
    return [
        claim,
        session,
        message,
        evidence,
        task,
        task_link,
        idempotency,
        second_idempotency,
        audit_event,
        realtime_sequence,
        realtime_event,
    ]


def _metadata(count: int) -> SnapshotMetadata:
    return SnapshotMetadata('northwind_test', 'northwind_records', '{"time": 1}', count)


def _finding_codes(report: Any) -> set[str]:
    return {finding.code for finding in report.findings}


def test_inventory_contains_every_approved_mongodb_record_type() -> None:
    assert len(IDENTITY_FIELDS) == 45
    assert 'CustomerAccountRecord' not in IDENTITY_FIELDS
    assert 'claim' in IDENTITY_FIELDS
    assert 'external_task_evidence_link' in IDENTITY_FIELDS


def test_rehearsal_transforms_reads_back_and_repeats_without_duplicates() -> None:
    documents = _representative_snapshot()

    items, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is True
    assert report.first_pass == {'migrated': len(items)}
    assert report.second_pass == {'unchanged': len(items)}
    assert report.target_item_count == len(items)
    assert report.evidence_level == 'local_mongodb_rehearsal_only'
    assert report.source_head == SOURCE_HEAD
    assert report.reconciliation_issues == RECONCILIATION_ISSUES
    assert any(item.item_kind == 'message_turn_lookup' for item in items)
    generation_items = [item for item in items if item.item_kind == 'claim_actor_generation']
    assert len(generation_items) == 1
    assert generation_items[0].payload['generation'] == 2
    claim_item = next(
        item for item in items if item.record_type == 'claim' and item.item_kind == 'canonical'
    )
    assert claim_item.payload['revision'] == 3
    assert claim_item.payload['audit_provenance'] == {'source': 'synthetic-rehearsal'}
    session_item = next(
        item for item in items if item.record_type == 'session' and item.item_kind == 'canonical'
    )
    assert session_item.payload['owner_ref'] == 'claim:clm_rehearsal'
    assert 'customer_id' not in session_item.payload
    customer_projection = next(item for item in items if item.item_kind == 'customer_claim')
    assert customer_projection.sk.startswith('UPDATED#999982')
    assert customer_projection.payload == {
        'canonical_pk': 'ENTITY#claim#clm_rehearsal',
        'canonical_sk': 'META',
        'customer_id': 'cus_rehearsal',
        'claim_id': 'clm_rehearsal',
    }
    assert any(
        item.record_type == 'external_task_evidence_link'
        and item.pk.startswith('ENTITY#external_task_evidence_link#')
        for item in items
    )


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda records: records.append(_document('invented_record', 'one', invented_id='one')),
            'UNKNOWN_RECORD_TYPE',
        ),
        (
            lambda records: records.__setitem__(1, {**records[1], 'claim_id': 'clm_missing'}),
            'DANGLING_CLAIM',
        ),
        (
            lambda records: records.__setitem__(2, {**records[2], 'customer_id': 'cus_other'}),
            'CROSS_OWNER_RECORD',
        ),
        (
            lambda records: records.append(
                {
                    **records[5],
                    '_id': 'external_task_evidence_link:duplicate',
                    'task_id': 'tsk_other',
                }
            ),
            'DUPLICATE_IDENTITY',
        ),
        (
            lambda records: records.append(
                _document(
                    'realtime_event',
                    'rte_gap',
                    event_id='rte_gap',
                    sequence=3,
                    claim_id='clm_rehearsal',
                    customer_id='cus_rehearsal',
                )
            ),
            'REALTIME_SEQUENCE_GAP',
        ),
    ],
)
def test_rehearsal_fails_closed_for_invalid_source_graph(mutate: Any, expected_code: str) -> None:
    documents = _representative_snapshot()
    mutate(documents)

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert expected_code in _finding_codes(report)


def test_rehearsal_rejects_oversized_target_item() -> None:
    documents = _representative_snapshot()
    documents[2]['content'] = {'type': 'text', 'text': 'x' * (301 * 1024)}

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'OVERSIZED_ITEM' in _finding_codes(report)


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda records: records.__setitem__(0, {**records[0], 'revision': 0}),
            'INVALID_REVISION',
        ),
        (
            lambda records: records.__setitem__(1, {**records[1], 'context_revision': 4}),
            'FUTURE_CONTEXT_REVISION',
        ),
        (
            lambda records: records[6].__setitem__('actor_id', 'authenticated:user'),
            'IDEMPOTENCY_ENVELOPE_MISMATCH',
        ),
        (
            lambda records: records.append(
                _document(
                    'idempotency',
                    'anonymous:browser:/messages:key-3',
                    actor_id='anonymous:browser',
                    route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
                    key='key-3',
                    payload={
                        'claim_id': 'clm_rehearsal',
                        'message_id': 'msg_rehearsal',
                    },
                )
            ),
            'DUPLICATE_MESSAGE_TURN_LOOKUP',
        ),
    ],
)
def test_rehearsal_validates_revision_and_idempotency_integrity(
    mutate: Any, expected_code: str
) -> None:
    documents = _representative_snapshot()
    mutate(documents)

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert expected_code in _finding_codes(report)


def test_rehearsal_rejects_snapshot_count_mismatch() -> None:
    documents = _representative_snapshot()

    _, report = transform_snapshot(documents, _metadata(len(documents) + 1))

    assert report.completion_marker is False
    assert 'SNAPSHOT_COUNT_MISMATCH' in _finding_codes(report)


def test_rehearsal_is_deterministic_when_mongodb_return_order_changes() -> None:
    documents = _representative_snapshot()

    items, report = transform_snapshot(documents, _metadata(len(documents)))
    reversed_items, reversed_report = transform_snapshot(
        list(reversed(documents)), _metadata(len(documents))
    )

    assert reversed_items == items
    assert reversed_report.snapshot_fingerprint == report.snapshot_fingerprint


def test_rehearsal_fails_closed_for_empty_snapshot() -> None:
    _, report = transform_snapshot([], _metadata(0))

    assert report.completion_marker is False
    assert 'EMPTY_SNAPSHOT' in _finding_codes(report)


def test_rehearsal_reports_non_integer_realtime_sequence() -> None:
    documents = _representative_snapshot()
    documents[-1]['sequence'] = 'invalid'

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'INVALID_REALTIME_SEQUENCE' in _finding_codes(report)


def test_local_target_resumes_partial_run_without_duplicates() -> None:
    documents = _representative_snapshot()
    items, _ = transform_snapshot(documents, _metadata(len(documents)))
    split = len(items) // 2
    target = LocalTarget()

    first = target.apply(items[:split])
    resumed = target.apply(items)

    assert first == {'migrated': split}
    assert resumed == {'migrated': len(items) - split, 'unchanged': split}
    assert target.item_count == len(items)
    assert target.readback(items) is True


def test_local_target_reports_changed_authoritative_item_as_conflict() -> None:
    documents = _representative_snapshot()
    items, _ = transform_snapshot(documents, _metadata(len(documents)))
    target = LocalTarget()
    original = items[0]
    changed = replace(
        original,
        fingerprint='different-content-fingerprint',
        payload={**original.payload, 'changed': True},
    )

    assert target.apply([original]) == {'migrated': 1}
    assert target.apply([changed]) == {'conflict': 1}
    assert target.readback([original]) is True


def test_anonymous_promotion_restores_historical_turn_without_child_rewrite() -> None:
    documents = _representative_snapshot()
    documents[0]['customer_id'] = 'anonymous:browser'
    for document in documents:
        if document.get('customer_id') == 'cus_rehearsal':
            document['customer_id'] = 'anonymous:browser'
    before_items, _ = transform_snapshot(documents, _metadata(len(documents)))

    promotion = rehearse_anonymous_promotion(
        documents,
        claim_id='clm_rehearsal',
        anonymous_actor='anonymous:browser',
        authenticated_actor='customer:123',
        route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
        message_id='msg_rehearsal',
        retry_key='different-key',
    )

    assert [item.item_kind for item in promotion.items].count('promotion_alias') == 2
    lookup = next(
        item for item in promotion.items if item.item_kind == 'promotion_message_turn_lookup'
    )
    assert lookup.payload['message_turn_kind'] == 'runtime'
    assert lookup.payload['message_turn_revision'] == 3
    assert lookup.source_ref == promotion.restored_source_ref
    retirement = next(item for item in promotion.items if item.item_kind == 'promotion_retirement')
    assert retirement.payload['generation'] == 2
    assert retirement.payload['retired_to_actor_id'] == 'customer:123'

    promoted_documents = deepcopy(documents)
    promoted_documents[0]['customer_id'] = 'customer:123'
    after_items, _ = transform_snapshot(promoted_documents, _metadata(len(promoted_documents)))
    before_session = next(
        item
        for item in before_items
        if item.record_type == 'session' and item.item_kind == 'canonical'
    )
    after_session = next(
        item
        for item in after_items
        if item.record_type == 'session' and item.item_kind == 'canonical'
    )
    assert after_session == before_session


def test_anonymous_promotion_rejects_authenticated_alias_collision() -> None:
    documents = _representative_snapshot()
    documents[0]['customer_id'] = 'anonymous:browser'
    documents.append(
        _document(
            'idempotency',
            'customer:123:/messages:key-1',
            actor_id='customer:123',
            route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
            key='key-1',
            payload={'claim_id': 'clm_rehearsal'},
        )
    )

    with pytest.raises(ValueError, match='exact-key alias collides'):
        rehearse_anonymous_promotion(
            documents,
            claim_id='clm_rehearsal',
            anonymous_actor='anonymous:browser',
            authenticated_actor='customer:123',
            route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
            message_id='msg_rehearsal',
            retry_key='different-key',
        )


@pytest.mark.integration
def test_snapshot_reader_uses_real_mongodb_transaction() -> None:
    uri = os.getenv('NORTHWIND_MONGODB_URI')
    if not uri:
        pytest.skip('NORTHWIND_MONGODB_URI is not configured.')
    client: MongoClient[Any] = MongoClient(uri, serverSelectionTimeoutMS=5000)
    database = 'northwind_migration_rehearsal_test'
    collection = 'northwind_records'
    try:
        client.drop_database(database)
        client[database][collection].insert_many(_representative_snapshot())

        documents, metadata = read_snapshot(client, database, collection)
        _, report = transform_snapshot(documents, metadata)

        assert metadata.record_count == len(_representative_snapshot())
        assert report.completion_marker is True
    finally:
        client.drop_database(database)
        client.close()
