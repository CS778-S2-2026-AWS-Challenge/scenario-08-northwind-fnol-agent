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
    RECORD_MAPPINGS,
    SOURCE_HEAD,
    LocalTarget,
    SnapshotMetadata,
    plan_record,
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


MAPPING_CASES = [
    (
        'claim',
        ('claim_id',),
        'claim_owner',
        'claim_creation',
        {'claim_owner', 'customer_claim', 'global_claim', 'claim_search'},
    ),
    (
        'session',
        ('session_id',),
        'claim',
        'session_checkpoint',
        {'claim_order', 'session_lookup', 'session_search'},
    ),
    (
        'message',
        ('message_id',),
        'claim_session',
        'agent_turn',
        {'session_order', 'message_client_lookup'},
    ),
    (
        'conversation_summary',
        ('summary_id',),
        'claim_session',
        'agent_turn',
        {'session_summary_order'},
    ),
    (
        'follow_up',
        ('follow_up_id',),
        'claim',
        'session_checkpoint',
        {'claim_order', 'open_purpose_lookup', 'open_session_lookup'},
    ),
    (
        'agent_decision',
        ('decision_id',),
        'claim_session',
        'agent_turn',
        {'claim_order', 'trigger_lookup'},
    ),
    ('branch_evaluation', ('evaluation_id',), 'claim', 'session_checkpoint', {'claim_order'}),
    (
        'runtime_trace',
        ('trace_id',),
        'claim_session',
        'agent_turn',
        {'claim_order', 'trigger_lookup'},
    ),
    (
        'turn_plan',
        ('turn_id',),
        'claim_session',
        'agent_turn',
        {'trigger_lookup', 'turn_bundle'},
    ),
    ('agent_proposal', ('proposal_id',), 'claim_session_turn', 'agent_turn', {'turn_bundle'}),
    ('execution_plan', ('execution_plan_id',), 'claim_turn', 'agent_turn', {'turn_bundle'}),
    ('action_envelope', ('envelope_id',), 'claim_turn', 'agent_turn', {'turn_order'}),
    ('tool_result', ('result_id',), 'claim_turn', 'agent_turn', {'turn_order'}),
    ('turn_result', ('result_id',), 'claim_session_turn', 'agent_turn', {'turn_bundle'}),
    (
        'runtime_work_item',
        ('work_item_id',),
        'claim_turn',
        'agent_turn',
        {'claim_order', 'turn_order'},
    ),
    ('asset', ('asset_id',), 'customer', 'claim_child', {'customer_all', 'customer_active'}),
    (
        'claim_asset_snapshot',
        ('snapshot_id',),
        'claim_customer',
        'claim_child',
        {'claim_order'},
    ),
    (
        'motor_other_driver',
        ('participant_id',),
        'claim_customer',
        'claim_child',
        {'claim_singleton'},
    ),
    (
        'contents_item_evidence_association',
        ('association_id',),
        'claim_customer_item',
        'claim_child',
        {'claim_order', 'contents_item_order', 'contents_evidence_unique'},
    ),
    (
        'evidence',
        ('evidence_id',),
        'claim_owner',
        'claim_child',
        {'claim_order', 'customer_evidence'},
    ),
    (
        'evidence_claim_link',
        ('link_id',),
        'cross_claim_customer',
        'claim_child',
        {'target_claim_order', 'evidence_claim_unique'},
    ),
    ('external_task', ('task_id',), 'claim_customer', 'claim_child', {'claim_order'}),
    (
        'external_task_request',
        ('request_id',),
        'claim_task_customer',
        'claim_child',
        {'claim_order', 'task_lookup', 'task_unique'},
    ),
    (
        'external_task_result',
        ('result_id',),
        'claim_task_customer',
        'claim_child',
        {'claim_order', 'task_unique'},
    ),
    (
        'external_task_evidence_link',
        ('claim_id', 'evidence_id'),
        'claim_task_evidence',
        'claim_child',
        {'claim_order', 'task_lookup'},
    ),
    ('assessor_routing_operation', ('operation_id',), 'claim', 'claim_child', {'claim_order'}),
    (
        'handoff',
        ('handoff_id',),
        'claim_customer',
        'staff_ownership',
        {'claim_order', 'handoff_queue'},
    ),
    ('retrieval', ('retrieval_id',), 'claim_customer', 'retrieval_bundle', {'claim_order'}),
    ('review_signal', ('signal_id',), 'claim_customer', 'retrieval_bundle', {'claim_order'}),
    (
        'signal_decision',
        ('signal_decision_id',),
        'claim_staff',
        'staff_ownership',
        {'claim_order'},
    ),
    (
        'staff_action',
        ('action_id',),
        'claim_staff',
        'staff_ownership',
        {'claim_order', 'assignee_order'},
    ),
    ('customer_update', ('update_id',), 'claim', 'staff_ownership', {'claim_order'}),
    (
        'collaboration_request',
        ('request_id',),
        'claim_staff',
        'staff_ownership',
        {'claim_order', 'target_staff_order'},
    ),
    (
        'claim_coworker',
        ('coworker_id',),
        'claim_staff',
        'staff_ownership',
        {'claim_all', 'claim_active'},
    ),
    ('staff_presence', ('staff_id',), 'staff', 'staff_ownership', {'staff_listing'}),
    (
        'staff_agent_session',
        ('session_id',),
        'staff',
        'staff_ownership',
        {'staff_session_order'},
    ),
    (
        'staff_agent_message',
        ('message_id',),
        'staff_session',
        'staff_ownership',
        {'staff_message_order', 'staff_message_client_lookup'},
    ),
    (
        'staff_agent_execution',
        ('execution_id',),
        'staff_session_claim',
        'staff_ownership',
        {'claim_order', 'staff_session_order'},
    ),
    (
        'audit_event',
        ('event_id',),
        'audit_subject',
        'staff_ownership',
        {'audit_subject_order', 'audit_global_order', 'audit_type_order', 'audit_actor_order'},
    ),
    ('realtime_sequence', (), 'system', 'claim_child', set()),
    ('realtime_event', ('event_id',), 'system_event', 'claim_child', {'realtime_order'}),
    (
        'idempotency',
        ('actor_id', 'route', 'key'),
        'actor_claim',
        'session_checkpoint',
        {'claim_actor_idempotency', 'message_turn_lookup'},
    ),
    ('policy', ('policy_id',), 'customer', 'claim_child', {'customer_all', 'customer_active'}),
    (
        'identity_document',
        ('identity_id',),
        'customer_protected',
        'claim_child',
        {'customer_all', 'customer_active'},
    ),
    (
        'payment_destination',
        ('payment_destination_id',),
        'customer_protected',
        'claim_child',
        {'customer_all', 'customer_active'},
    ),
]


def _mapping_document(record_type: str) -> dict[str, Any]:
    mapping = RECORD_MAPPINGS[record_type]
    document: dict[str, Any] = {
        '_id': f'{record_type}:mapping-contract',
        'record_type': record_type,
        'active': True,
        'created_at': NOW,
        'updated_at': NOW,
    }
    for field in mapping.identity_fields:
        document[field] = f'{field}_mapping'
    for relationship in mapping.relationships:
        if relationship.optional and relationship.field not in {'message_id'}:
            continue
        document.setdefault(relationship.field, f'{relationship.field}_mapping')
    if 'claim' in mapping.ownership or any(
        relationship.target_type == 'claim' for relationship in mapping.relationships
    ):
        document.setdefault('claim_id', 'claim_id_mapping')
    if 'customer' in mapping.ownership or mapping.ownership == 'claim_owner':
        document['customer_id'] = 'customer_id_mapping'
    if 'staff' in mapping.ownership:
        document['staff_id'] = 'staff_id_mapping'
    for order_field in mapping.order_fields:
        document[order_field] = 1 if order_field == 'sequence' else NOW
    if record_type in {'message', 'staff_agent_message'}:
        document['client_message_id'] = 'client_message_id_mapping'
    if record_type == 'realtime_event':
        document['sequence'] = 1
    return document


@pytest.mark.parametrize(
    'family',
    sorted({case[3] for case in MAPPING_CASES}),
)
def test_each_approved_record_has_executable_mapping_semantics(
    family: str,
) -> None:
    cases = [case for case in MAPPING_CASES if case[3] == family]

    for record_type, identity, ownership, _, required_access in cases:
        mapping = RECORD_MAPPINGS[record_type]
        assert mapping.identity_fields == identity
        assert mapping.ownership == ownership
        assert mapping.mutation_family == family
        assert set(mapping.access_kinds) == required_access
        assert IDENTITY_FIELDS[record_type] == mapping.identity_fields
        planned = plan_record(_mapping_document(record_type))
        emitted_access = {item.item_kind for item in planned if item.item_kind != 'canonical'}
        assert required_access - {'realtime_order'} <= emitted_access
        if record_type == 'realtime_event':
            assert planned[0].pk == 'SYSTEM#REALTIME'
            assert planned[0].sk.startswith('EVENT#')


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
    assert customer_projection.payload['canonical_pk'] == 'ENTITY#claim#clm_rehearsal'
    assert customer_projection.payload['customer_id'] == 'cus_rehearsal'
    assert customer_projection.payload['claim_id'] == 'clm_rehearsal'
    assert customer_projection.payload['order_field'] == 'updated_at'
    assert report.atomic_mutations
    assert all(mutation.within_limits for mutation in report.atomic_mutations)
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


def test_rehearsal_rejects_orphan_contents_item_evidence_association() -> None:
    documents = _representative_snapshot()
    documents[0]['contents_items'] = []
    documents.append(
        _document(
            'contents_item_evidence_association',
            'assoc_orphan',
            association_id='assoc_orphan',
            claim_id='clm_rehearsal',
            customer_id='cus_rehearsal',
            item_id='item_missing',
            evidence_id='evd_rehearsal',
            created_at=NOW,
        )
    )

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'DANGLING_CONTENTS_ITEM' in _finding_codes(report)


def _add_cross_owner_asset(records: list[dict[str, Any]]) -> None:
    records.extend(
        [
            _document(
                'asset',
                'ast_other',
                asset_id='ast_other',
                customer_id='cus_other',
                active=True,
                updated_at=NOW,
            ),
            _document(
                'claim_asset_snapshot',
                'snap_wrong_owner',
                snapshot_id='snap_wrong_owner',
                asset_id='ast_other',
                claim_id='clm_rehearsal',
                customer_id='cus_rehearsal',
                captured_at=NOW,
            ),
        ]
    )


def _add_orphan_runtime_turn(records: list[dict[str, Any]]) -> None:
    records.append(
        _document(
            'tool_result',
            'res_orphan',
            result_id='res_orphan',
            turn_id='turn_missing',
            claim_id='clm_rehearsal',
            customer_id='cus_rehearsal',
            created_at=NOW,
        )
    )


def _add_cross_staff_message(records: list[dict[str, Any]]) -> None:
    records.extend(
        [
            _document(
                'staff_agent_session',
                'staff_session',
                session_id='staff_session',
                staff_id='staff_one',
                updated_at=NOW,
            ),
            _document(
                'staff_agent_message',
                'staff_message',
                message_id='staff_message',
                session_id='staff_session',
                staff_id='staff_two',
                client_message_id='staff_client',
                created_at=NOW,
            ),
        ]
    )


def _add_orphan_review_signal(records: list[dict[str, Any]]) -> None:
    records.append(
        _document(
            'review_signal',
            'sig_orphan',
            signal_id='sig_orphan',
            claim_id='clm_rehearsal',
            customer_id='cus_rehearsal',
            source_refs=['ret_missing'],
            created_at=NOW,
        )
    )


def _add_orphan_audit_scope(records: list[dict[str, Any]]) -> None:
    records.append(
        _document(
            'audit_event',
            'aud_orphan',
            event_id='aud_orphan',
            subject={'claim_id': 'clm_missing'},
            created_at=NOW,
        )
    )


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (_add_cross_owner_asset, 'CROSS_OWNER_RELATIONSHIP'),
        (_add_orphan_runtime_turn, 'DANGLING_RELATIONSHIP'),
        (_add_cross_staff_message, 'CROSS_SCOPE_RELATIONSHIP'),
        (_add_orphan_review_signal, 'DANGLING_RETRIEVAL'),
        (_add_orphan_audit_scope, 'DANGLING_AUDIT_SCOPE'),
    ],
)
def test_rehearsal_fails_closed_across_relationship_families(
    mutate: Any, expected_code: str
) -> None:
    documents = _representative_snapshot()
    mutate(documents)

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert expected_code in _finding_codes(report)


def test_reverse_readback_preserves_fragments_nulls_and_empty_collections() -> None:
    documents = _representative_snapshot()
    documents[0].update(
        {
            'form': {'incident_location': None},
            'contents_items': [{'item_id': 'itm_one', 'description': None}],
            'external_service_consents': [],
        }
    )
    documents[3]['material_history'] = []
    items, report = transform_snapshot(documents, _metadata(len(documents)))
    target = LocalTarget()
    target.apply(items)

    changed_source = deepcopy(documents)
    changed_source[0]['form']['incident_location'] = 'Auckland'

    assert report.completion_marker is True
    assert target.readback(documents) is True
    assert target.readback(changed_source) is False


def test_rehearsal_rejects_atomic_action_limit() -> None:
    documents = _representative_snapshot()
    message = documents[2]
    documents.remove(message)
    for index in range(40):
        documents.append(
            {
                **message,
                '_id': f'message:msg_{index}',
                'message_id': f'msg_{index}',
                'client_message_id': f'client_{index}',
            }
        )

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'ATOMIC_ACTION_LIMIT' in _finding_codes(report)
    agent_turn = next(
        mutation for mutation in report.atomic_mutations if mutation.family == 'agent_turn'
    )
    assert agent_turn.action_count > 100
    assert agent_turn.within_limits is False


def test_rehearsal_rejects_atomic_serialized_byte_limit() -> None:
    documents = _representative_snapshot()
    message = documents[2]
    documents.remove(message)
    for index in range(18):
        documents.append(
            {
                **message,
                '_id': f'message:large_{index}',
                'message_id': f'msg_large_{index}',
                'client_message_id': f'client_large_{index}',
                'content': {'type': 'text', 'text': 'x' * (240 * 1024)},
            }
        )

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'ATOMIC_BYTE_LIMIT' in _finding_codes(report)
    agent_turn = next(
        mutation for mutation in report.atomic_mutations if mutation.family == 'agent_turn'
    )
    assert agent_turn.action_count <= 100
    assert agent_turn.serialized_bytes > 4 * 1024 * 1024


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
    assert target.readback(documents) is True


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
    assert target.stored_items() == (original,)


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
