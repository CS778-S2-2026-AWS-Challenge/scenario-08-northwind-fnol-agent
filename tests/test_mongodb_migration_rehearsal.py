from __future__ import annotations

import os
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

import pytest
from pymongo import MongoClient

from scripts.rehearse_mongodb_migration import (
    IDENTITY_FIELDS,
    RECONCILIATION_ISSUES,
    RECORD_MAPPINGS,
    SOURCE_HEAD,
    LocalTarget,
    MutationAction,
    MutationManifest,
    SnapshotMetadata,
    plan_record,
    read_snapshot,
    rehearse_anonymous_promotion,
    rehearse_mutation_manifest,
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
        event_type='claim.updated',
        subject={
            'subject_type': 'claim',
            'subject_id': 'clm_rehearsal',
            'claim_id': 'clm_rehearsal',
        },
        actor={'actor_id': 'staff_rehearsal', 'actor_type': 'staff'},
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
        evidence,
        task,
        task_link,
        second_idempotency,
        audit_event,
        realtime_sequence,
        realtime_event,
    ]


def _by_type(records: list[dict[str, Any]], record_type: str) -> dict[str, Any]:
    return next(record for record in records if record['record_type'] == record_type)


def _add_message_turn(records: list[dict[str, Any]]) -> None:
    records.extend(
        [
            _document(
                'message',
                'msg_rehearsal',
                message_id='msg_rehearsal',
                client_message_id='client-rehearsal',
                claim_id='clm_rehearsal',
                session_id='ses_rehearsal',
                customer_id='cus_rehearsal',
                created_at=NOW,
            ),
            _document(
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
            ),
        ]
    )


def _agent_turn_snapshot() -> list[dict[str, Any]]:
    records = _representative_snapshot()
    records = [
        record
        for record in records
        if record['record_type']
        not in {'evidence', 'external_task', 'external_task_evidence_link', 'audit_event'}
    ]
    _add_message_turn(records)
    records.append(
        _document(
            'turn_plan',
            'turn_rehearsal',
            turn_id='turn_rehearsal',
            claim_id='clm_rehearsal',
            session_id='ses_rehearsal',
            customer_id='cus_rehearsal',
            trigger_message_id='msg_rehearsal',
            created_at=NOW,
        )
    )
    return records


def _add_duplicate_message_turn_lookup(records: list[dict[str, Any]]) -> None:
    _add_message_turn(records)
    records.append(
        _document(
            'idempotency',
            'anonymous:browser:/messages:key-3',
            actor_id='anonymous:browser',
            route='/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
            key='key-3',
            payload={
                'actor_id': 'anonymous:browser',
                'route': '/api/v1/claims/clm_rehearsal/sessions/ses_rehearsal/messages',
                'key': 'key-3',
                'claim_id': 'clm_rehearsal',
                'message_id': 'msg_rehearsal',
            },
        )
    )


def _metadata(count: int) -> SnapshotMetadata:
    return SnapshotMetadata('northwind_test', 'northwind_records', '{"time": 1}', count)


def _finding_codes(report: Any) -> set[str]:
    return {finding.code for finding in report.findings}


def test_inventory_contains_every_approved_mongodb_record_type() -> None:
    assert len(IDENTITY_FIELDS) == 46
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
    (
        'claim_creation_operation',
        ('operation_id',),
        'claim_customer',
        'claim_child',
        {'claim_order', 'claim_creation_unique'},
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
        {
            'audit_subject_order',
            'audit_global_order',
            'audit_type_order',
            'audit_subject_type_order',
            'audit_actor_order',
        },
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
    identity = next(case[1] for case in MAPPING_CASES if case[0] == record_type)
    document: dict[str, Any] = {
        '_id': f'{record_type}:mapping-contract',
        'record_type': record_type,
        'active': True,
        'created_at': NOW,
        'updated_at': NOW,
        'started_at': NOW,
        'captured_at': NOW,
        'prepared_at': NOW,
        'received_at': NOW,
        'linked_at': NOW,
        'retrieved_at': NOW,
        'granted_at': NOW,
        'occurred_at': NOW,
        'claim_id': 'claim_id_mapping',
        'customer_id': 'customer_id_mapping',
        'staff_id': 'staff_id_mapping',
        'session_id': 'session_id_mapping',
        'turn_id': 'turn_id_mapping',
        'task_id': 'task_id_mapping',
        'evidence_id': 'evidence_id_mapping',
        'target_claim_id': 'target_claim_id_mapping',
        'trigger_message_id': 'trigger_message_id_mapping',
        'actor_id': 'actor_id_mapping',
        'route': 'route_mapping',
        'key': 'key_mapping',
        'message_id': 'message_id_mapping',
        'authorised_decision_id': 'decision_id_mapping',
    }
    for field in identity:
        document[field] = f'{field}_mapping'
    if record_type in {'message', 'staff_agent_message'}:
        document['client_message_id'] = 'client_message_id_mapping'
    if record_type == 'claim':
        document['staff_search'] = {
            'external_reference': 'EXT-123',
            'created_date': '2026-09-21',
            'incident_date': '2026-09-20',
            'product_family': 'motor',
            'lifecycle_state': 'collecting',
            'assignee_id': 'staff_mapping',
            'queue': 'needs_attention',
        }
    if record_type == 'session':
        document['status'] = 'active'
    if record_type == 'follow_up':
        document.update(
            {
                'status': 'pending',
                'purpose': 'resume_incomplete_claim',
                'source_session_id': 'source_session_mapping',
            }
        )
    if record_type == 'contents_item_evidence_association':
        document['item_id'] = 'item_mapping'
    if record_type == 'handoff':
        document['queue'] = 'needs_attention'
    if record_type == 'staff_action':
        document['assignee_id'] = 'staff_mapping'
    if record_type == 'collaboration_request':
        document['target_staff_id'] = 'staff_mapping'
    if record_type == 'audit_event':
        document.update(
            {
                'event_type': 'claim.updated',
                'subject': {
                    'subject_type': 'claim',
                    'subject_id': 'claim_id_mapping',
                    'claim_id': 'claim_id_mapping',
                },
                'actor': {'actor_id': 'staff_mapping'},
            }
        )
    if record_type == 'realtime_event':
        document['sequence'] = 1
    return document


def _contract_digest(*components: str) -> str:
    encoded = ''.join(f'{len(value.encode())}:{value}' for value in components)
    return sha256(encoded.encode()).hexdigest()


ASCENDING_TIME = '2026-09-21T06:00:00.000000Z'
REVERSE_TIME = '99998210029599999999'


def _expected_mapping_keys(
    record_type: str, identity_fields: tuple[str, ...]
) -> set[tuple[str, str, str]]:
    identity_values = tuple(f'{field}_mapping' for field in identity_fields)
    entity_id = (
        identity_values[0] if len(identity_values) == 1 else _contract_digest(*identity_values)
    )
    if record_type == 'realtime_sequence':
        return {('canonical', 'SYSTEM#REALTIME', 'COUNTER')}
    if record_type == 'realtime_event':
        return {('canonical', 'SYSTEM#REALTIME', 'EVENT#00000000000000000001#event_id_mapping')}
    if record_type == 'idempotency':
        canonical_pk = 'IDEMPOTENCY#' + _contract_digest(
            'actor_id_mapping', 'route_mapping', 'key_mapping'
        )
    else:
        canonical_pk = f'ENTITY#{record_type}#{entity_id}'
    expected = {('canonical', canonical_pk, 'META')}

    claim_order = {
        'session': 'STARTED_AT',
        'follow_up': 'CREATED_AT',
        'agent_decision': 'CREATED_AT',
        'claim_creation_operation': 'UPDATED_AT',
        'branch_evaluation': 'CREATED_AT',
        'runtime_trace': 'CREATED_AT',
        'runtime_work_item': 'UPDATED_AT',
        'claim_asset_snapshot': 'CAPTURED_AT',
        'contents_item_evidence_association': 'CREATED_AT',
        'evidence': 'UPDATED_AT',
        'external_task': 'CREATED_AT',
        'external_task_request': 'PREPARED_AT',
        'external_task_result': 'RECEIVED_AT',
        'external_task_evidence_link': 'LINKED_AT',
        'assessor_routing_operation': 'CREATED_AT',
        'handoff': 'CREATED_AT',
        'retrieval': 'RETRIEVED_AT',
        'review_signal': 'CREATED_AT',
        'signal_decision': 'CREATED_AT',
        'staff_action': 'CREATED_AT',
        'customer_update': 'CREATED_AT',
        'collaboration_request': 'CREATED_AT',
        'staff_agent_execution': 'CREATED_AT',
    }
    if record_type in claim_order:
        expected.add(
            (
                'claim_order',
                f'ACCESS#CLAIM#claim_id_mapping#{record_type}',
                f'{claim_order[record_type]}#{ASCENDING_TIME}#{entity_id}',
            )
        )

    if record_type == 'claim':
        claim_sk = f'UPDATED#{REVERSE_TIME}#claim_id_mapping'
        expected.update(
            {
                ('claim_owner', canonical_pk, 'OWNER'),
                ('customer_claim', 'ACCESS#CUSTOMER_CLAIMS#customer_id_mapping', claim_sk),
                ('global_claim', 'ACCESS#CLAIMS#ALL', claim_sk),
            }
        )
        search_values = {
            'claim_reference': ('claim_id_mapping', 'EXT-123'),
            'customer_reference': ('customer_id_mapping',),
            'external_reference': ('EXT-123',),
            'created_date': ('2026-09-21',),
            'incident_date': ('2026-09-20',),
            'product_family': ('motor',),
            'lifecycle_state': ('collecting',),
            'assignee_id': ('staff_mapping',),
            'queue': ('needs_attention',),
        }
        for field, values in search_values.items():
            for value in values:
                expected.add(
                    (
                        'claim_search',
                        f'ACCESS#CLAIM_SEARCH#{field}#{_contract_digest(value)}',
                        claim_sk,
                    )
                )
    elif record_type == 'session':
        expected.update(
            {
                (
                    'session_lookup',
                    'LOOKUP#CLAIM_SESSION#'
                    + _contract_digest('claim_id_mapping', 'session_id_mapping'),
                    'META',
                ),
                (
                    'session_search',
                    'ACCESS#CLAIM_SESSIONS_DATE#claim_id_mapping#2026-09-21',
                    f'STARTED#{REVERSE_TIME}#session_id_mapping',
                ),
                (
                    'session_search',
                    'ACCESS#CLAIM_SESSIONS_STATUS#claim_id_mapping#active',
                    f'STARTED#{REVERSE_TIME}#session_id_mapping',
                ),
            }
        )
    elif record_type == 'message':
        expected.update(
            {
                (
                    'session_order',
                    'ACCESS#SESSION#session_id_mapping#message',
                    f'CREATED#{ASCENDING_TIME}#message_id_mapping',
                ),
                (
                    'message_client_lookup',
                    'LOOKUP#MESSAGE_CLIENT#'
                    + _contract_digest('claim_id_mapping', 'client_message_id_mapping'),
                    'META',
                ),
            }
        )
    elif record_type == 'conversation_summary':
        expected.add(
            (
                'session_summary_order',
                'ACCESS#SESSION#session_id_mapping#conversation_summary',
                f'CREATED#{ASCENDING_TIME}#summary_id_mapping',
            )
        )
    elif record_type == 'follow_up':
        expected.update(
            {
                (
                    'open_purpose_lookup',
                    'UNIQUE#OPEN_FOLLOW_UP_PURPOSE#'
                    + _contract_digest('claim_id_mapping', 'resume_incomplete_claim'),
                    'META',
                ),
                (
                    'open_session_lookup',
                    'UNIQUE#OPEN_FOLLOW_UP_SESSION#'
                    + _contract_digest('claim_id_mapping', 'source_session_mapping'),
                    'META',
                ),
            }
        )
    elif record_type in {'agent_decision', 'runtime_trace', 'turn_plan'}:
        expected.add(
            (
                'trigger_lookup',
                'LOOKUP#TRIGGER#'
                + _contract_digest(
                    'claim_id_mapping',
                    'session_id_mapping',
                    'trigger_message_id_mapping',
                    record_type,
                ),
                'META',
            )
        )
    elif record_type == 'claim_creation_operation':
        expected.add(
            (
                'claim_creation_unique',
                'UNIQUE#CLAIM_CREATION_OPERATION_CLAIM#' + _contract_digest('claim_id_mapping'),
                'META',
            )
        )

    turn_access = {
        'turn_plan': 'turn_bundle',
        'agent_proposal': 'turn_bundle',
        'execution_plan': 'turn_bundle',
        'action_envelope': 'turn_order',
        'tool_result': 'turn_order',
        'turn_result': 'turn_bundle',
        'runtime_work_item': 'turn_order',
    }
    if record_type in turn_access:
        expected.add(
            (
                turn_access[record_type],
                f'ACCESS#TURN#turn_id_mapping#{record_type}',
                f'CREATED#{ASCENDING_TIME}#{entity_id}',
            )
        )

    if record_type in {'asset', 'policy', 'identity_document', 'payment_destination'}:
        for state, kind in (('ALL', 'customer_all'), ('ACTIVE', 'customer_active')):
            expected.add(
                (
                    kind,
                    f'ACCESS#CUSTOMER#customer_id_mapping#{record_type}#{state}',
                    f'UPDATED_AT#{ASCENDING_TIME}#{entity_id}',
                )
            )
    elif record_type == 'motor_other_driver':
        expected.add(
            (
                'claim_singleton',
                'UNIQUE#MOTOR_OTHER_DRIVER_CLAIM#' + _contract_digest('claim_id_mapping'),
                'META',
            )
        )
    elif record_type == 'contents_item_evidence_association':
        expected.update(
            {
                (
                    'contents_item_order',
                    'ACCESS#CLAIM_CONTENTS_ITEM#claim_id_mapping#item_mapping',
                    f'CREATED#{ASCENDING_TIME}#association_id_mapping',
                ),
                (
                    'contents_evidence_unique',
                    'UNIQUE#CONTENTS_ITEM_EVIDENCE#'
                    + _contract_digest('claim_id_mapping', 'item_mapping', 'evidence_id_mapping'),
                    'META',
                ),
            }
        )
    elif record_type == 'evidence':
        expected.add(
            (
                'customer_evidence',
                'ACCESS#CUSTOMER#customer_id_mapping#evidence#ALL',
                f'UPDATED_AT#{ASCENDING_TIME}#evidence_id_mapping',
            )
        )
    elif record_type == 'evidence_claim_link':
        expected.update(
            {
                (
                    'target_claim_order',
                    'ACCESS#CLAIM#target_claim_id_mapping#evidence_claim_link',
                    f'UPDATED_AT#{ASCENDING_TIME}#link_id_mapping',
                ),
                (
                    'evidence_claim_unique',
                    'UNIQUE#EVIDENCE_CLAIM_TARGET#'
                    + _contract_digest('target_claim_id_mapping', 'evidence_id_mapping'),
                    'META',
                ),
            }
        )
    elif record_type in {'external_task_request', 'external_task_evidence_link'}:
        expected.add(
            (
                'task_lookup',
                f'ACCESS#TASK#task_id_mapping#{record_type}',
                f'{claim_order[record_type]}#{ASCENDING_TIME}#{entity_id}',
            )
        )
        if record_type == 'external_task_request':
            expected.add(
                (
                    'task_unique',
                    'UNIQUE#EXTERNAL_TASK_REQUEST#' + _contract_digest('task_id_mapping'),
                    'META',
                )
            )
    elif record_type == 'external_task_result':
        expected.add(
            (
                'task_unique',
                'UNIQUE#EXTERNAL_TASK_RESULT#'
                + _contract_digest('claim_id_mapping', 'task_id_mapping'),
                'META',
            )
        )
    elif record_type == 'handoff':
        expected.add(
            (
                'handoff_queue',
                'ACCESS#HANDOFF_QUEUE#needs_attention',
                f'CREATED_AT#{ASCENDING_TIME}#handoff_id_mapping',
            )
        )
    elif record_type == 'staff_action':
        expected.add(
            (
                'assignee_order',
                'ACCESS#STAFF#staff_mapping#staff_action',
                f'CREATED_AT#{ASCENDING_TIME}#action_id_mapping',
            )
        )
    elif record_type == 'collaboration_request':
        expected.add(
            (
                'target_staff_order',
                'ACCESS#STAFF#staff_mapping#collaboration_request',
                f'CREATED_AT#{ASCENDING_TIME}#request_id_mapping',
            )
        )
    elif record_type == 'claim_coworker':
        for state, kind in (('ALL', 'claim_all'), ('ACTIVE', 'claim_active')):
            expected.add(
                (
                    kind,
                    f'ACCESS#CLAIM#claim_id_mapping#claim_coworker#{state}',
                    f'GRANTED_AT#{ASCENDING_TIME}#coworker_id_mapping',
                )
            )
    elif record_type == 'staff_presence':
        expected.add(
            (
                'staff_listing',
                'ACCESS#STAFF_PRESENCE#ALL',
                f'UPDATED#{REVERSE_TIME}#staff_id_mapping',
            )
        )
    elif record_type in {'staff_agent_session', 'staff_agent_execution'}:
        expected.add(
            (
                'staff_session_order',
                'ACCESS#STAFF_AGENT#staff_id_mapping#SESSIONS',
                f'UPDATED#{REVERSE_TIME}#session_id_mapping',
            )
        )
    elif record_type == 'staff_agent_message':
        expected.update(
            {
                (
                    'staff_message_order',
                    'ACCESS#STAFF_AGENT_SESSION#session_id_mapping#MESSAGES',
                    f'CREATED#{ASCENDING_TIME}#message_id_mapping',
                ),
                (
                    'staff_message_client_lookup',
                    'LOOKUP#STAFF_AGENT_CLIENT#'
                    + _contract_digest(
                        'staff_id_mapping', 'session_id_mapping', 'client_message_id_mapping'
                    ),
                    'META',
                ),
            }
        )
    elif record_type == 'audit_event':
        audit_sk = f'TIME#{ASCENDING_TIME}#event_id_mapping'
        expected.update(
            {
                (
                    'audit_subject_order',
                    'ACCESS#AUDIT_SUBJECT#'
                    + _contract_digest('claim', 'claim_id_mapping', 'claim_id_mapping'),
                    audit_sk,
                ),
                ('audit_global_order', 'ACCESS#AUDIT#ALL', audit_sk),
                (
                    'audit_type_order',
                    'ACCESS#AUDIT#EVENT_TYPE#' + _contract_digest('claim.updated'),
                    audit_sk,
                ),
                (
                    'audit_subject_type_order',
                    'ACCESS#AUDIT#SUBJECT_TYPE#' + _contract_digest('claim'),
                    audit_sk,
                ),
                (
                    'audit_actor_order',
                    'ACCESS#AUDIT#ACTOR#' + _contract_digest('staff_mapping'),
                    audit_sk,
                ),
            }
        )
    elif record_type == 'idempotency':
        expected.update(
            {
                (
                    'claim_actor_idempotency',
                    'ACCESS#CLAIM_IDEMPOTENCY#'
                    + _contract_digest('claim_id_mapping', 'actor_id_mapping'),
                    'RECORD#' + _contract_digest('route_mapping', 'key_mapping'),
                ),
                (
                    'message_turn_lookup',
                    'LOOKUP#MESSAGE_TURN_IDEMPOTENCY#'
                    + _contract_digest(
                        'actor_id_mapping',
                        'route_mapping',
                        'claim_id_mapping',
                        'message_id_mapping',
                    ),
                    'META',
                ),
            }
        )
    return expected


@pytest.mark.parametrize(
    ('record_type', 'identity_fields'),
    [(case[0], case[1]) for case in MAPPING_CASES],
)
def test_each_approved_record_emits_complete_exact_key_contract(
    record_type: str, identity_fields: tuple[str, ...]
) -> None:
    actual = {
        (item.item_kind, item.pk, item.sk) for item in plan_record(_mapping_document(record_type))
    }

    assert actual == _expected_mapping_keys(record_type, identity_fields)


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
    generation_items = [item for item in items if item.item_kind == 'claim_actor_generation']
    assert len(generation_items) == 1
    assert generation_items[0].payload['generation'] == 1
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
    assert customer_projection.payload['scope'] == {
        'customer_id': 'cus_rehearsal',
        'claim_id': 'clm_rehearsal',
    }
    assert report.atomic_evidence_level == 'not_reconstructable_from_final_snapshot'
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
            lambda records: _by_type(records, 'session').update(claim_id='clm_missing'),
            'DANGLING_CLAIM',
        ),
        (
            lambda records: _by_type(records, 'evidence').update(customer_id='cus_other'),
            'CROSS_OWNER_RECORD',
        ),
        (
            lambda records: records.append(
                {
                    **_by_type(records, 'external_task_evidence_link'),
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
    _by_type(documents, 'evidence')['content'] = {'type': 'text', 'text': 'x' * (301 * 1024)}

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is False
    assert 'OVERSIZED_ITEM' in _finding_codes(report)


def test_rehearsal_rejects_orphan_contents_item_evidence_association() -> None:
    documents = _representative_snapshot()
    _by_type(documents, 'claim')['contents_items'] = []
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
    _by_type(documents, 'claim').update(
        {
            'form': {'incident_location': None},
            'contents_items': [{'item_id': 'itm_one', 'description': None}],
            'external_service_consents': [],
        }
    )
    _by_type(documents, 'evidence')['material_history'] = []
    items, report = transform_snapshot(documents, _metadata(len(documents)))
    target = LocalTarget()
    target.apply(items)

    changed_source = deepcopy(documents)
    changed_source[0]['form']['incident_location'] = 'Auckland'

    assert report.completion_marker is True
    assert target.readback(documents) is True
    assert target.readback(changed_source) is False


def test_rehearsal_includes_merged_claim_creation_operation_contract() -> None:
    records = _agent_turn_snapshot()
    records.append(
        _document(
            'agent_decision',
            'dec_rehearsal',
            decision_id='dec_rehearsal',
            claim_id='clm_rehearsal',
            customer_id='cus_rehearsal',
            session_id='ses_rehearsal',
            trigger_message_id='msg_rehearsal',
            created_at=NOW,
        )
    )
    records.append(
        _document(
            'claim_creation_operation',
            'cco_rehearsal',
            operation_id='cco_rehearsal',
            claim_id='clm_rehearsal',
            customer_id='cus_rehearsal',
            authorised_decision_id='dec_rehearsal',
            authorised_revision=3,
            request_fingerprint='a' * 64,
            evidence_snapshot_fingerprint='b' * 64,
            route='standard_motor_intake',
            integration_source='insurer_core',
            status='prepared',
            created_at=NOW,
            updated_at=NOW,
        )
    )

    items, report = transform_snapshot(records, _metadata(len(records)))

    assert report.completion_marker is True
    item_keys = {f'{item.pk}|{item.sk}' for item in items}
    assert 'ENTITY#claim_creation_operation#cco_rehearsal|META' in item_keys
    assert (
        'UNIQUE#CLAIM_CREATION_OPERATION_CLAIM#' + _contract_digest('clm_rehearsal') + '|META'
        in item_keys
    )


def _action(
    action: str,
    key: str,
    *,
    condition: str | None = None,
    payload_size: int = 0,
) -> MutationAction:
    return MutationAction(
        action,
        f'MANIFEST#{key}',
        'META',
        {'value': 'x' * payload_size} if payload_size else {'ref': key},
        condition,
    )


FAMILY_ACTIONS = {
    'claim_creation': (
        _action('put', 'CLAIM'),
        _action('put', 'OWNER'),
        _action('put', 'SESSION'),
        _action('put', 'CUSTOMER_PROJECTION'),
        _action('put', 'GLOBAL_PROJECTION'),
        _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
        _action('put', 'REALTIME_EVENT', condition='attribute_not_exists(PK)'),
    ),
    'session_checkpoint': (
        _action('update', 'CLAIM', condition='revision = :expected'),
        _action('put', 'SESSION'),
        _action('put', 'FOLLOW_UP'),
        _action('put', 'IDEMPOTENCY', condition='attribute_not_exists(PK)'),
        _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
        _action('put', 'REALTIME_EVENT', condition='attribute_not_exists(PK)'),
    ),
    'claim_child': (
        _action('update', 'CLAIM', condition='revision = :expected'),
        _action('put', 'EVIDENCE'),
        _action('put', 'AUDIT', condition='attribute_not_exists(PK)'),
        _action('put', 'IDEMPOTENCY', condition='attribute_not_exists(PK)'),
        _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
        _action('put', 'REALTIME_EVENT', condition='attribute_not_exists(PK)'),
    ),
    'agent_turn': (
        _action('update', 'CLAIM', condition='revision = :expected'),
        _action('update', 'SESSION', condition='context_revision = :expected'),
        _action('put', 'USER_MESSAGE', condition='attribute_not_exists(PK)'),
        _action('put', 'AGENT_MESSAGE', condition='attribute_not_exists(PK)'),
        _action('put', 'TURN_PLAN', condition='attribute_not_exists(PK)'),
        _action('put', 'TURN_RESULT', condition='attribute_not_exists(PK)'),
        _action('put', 'IDEMPOTENCY', condition='attribute_not_exists(PK)'),
        _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
        _action('put', 'REALTIME_EVENT', condition='attribute_not_exists(PK)'),
    ),
    'staff_ownership': (
        _action('condition_check', 'STAFF_PRESENCE', condition='revision = :expected'),
        _action('update', 'CLAIM', condition='revision = :expected'),
        _action('put', 'STAFF_ACTION'),
        _action('put', 'AUDIT', condition='attribute_not_exists(PK)'),
        _action('put', 'IDEMPOTENCY', condition='attribute_not_exists(PK)'),
        _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
        _action('put', 'REALTIME_EVENT', condition='attribute_not_exists(PK)'),
    ),
    'retrieval_bundle': (
        _action('put', 'RETRIEVAL', condition='attribute_not_exists(PK)'),
        _action('put', 'REVIEW_SIGNAL', condition='attribute_not_exists(PK)'),
        _action('put', 'RETRIEVAL_PROJECTION'),
        _action('put', 'SIGNAL_PROJECTION'),
    ),
}


@pytest.mark.parametrize('family', sorted(FAMILY_ACTIONS))
def test_explicit_manifests_measure_current_atomic_family_actions(family: str) -> None:
    actions = FAMILY_ACTIONS[family]

    report = rehearse_mutation_manifest(MutationManifest(family, f'operation:{family}', actions))

    assert report.action_count == len(actions)
    assert report.action_count == len(report.action_keys)
    assert report.action_keys == tuple(
        f'{action.action.upper()}|{action.pk}|{action.sk}' for action in actions
    )
    assert report.within_limits is True


def test_final_snapshot_does_not_assign_global_counter_to_each_claim() -> None:
    documents = _representative_snapshot()
    _by_type(documents, 'realtime_sequence')['sequence'] = 2
    documents.extend(
        [
            _document(
                'claim',
                'clm_second',
                claim_id='clm_second',
                customer_id='cus_second',
                revision=1,
                created_at=NOW,
                updated_at=NOW,
            ),
            _document(
                'session',
                'ses_second',
                session_id='ses_second',
                claim_id='clm_second',
                customer_id='cus_second',
                context_revision=1,
                started_at=NOW,
            ),
            _document(
                'realtime_event',
                'rte_second',
                event_id='rte_second',
                sequence=2,
                claim_id='clm_second',
                customer_id='cus_second',
                occurred_at=NOW,
            ),
        ]
    )

    _, report = transform_snapshot(documents, _metadata(len(documents)))

    assert report.completion_marker is True
    assert report.atomic_evidence_level == 'not_reconstructable_from_final_snapshot'


def test_two_agent_turn_manifests_do_not_copy_cross_turn_records() -> None:
    first = rehearse_mutation_manifest(
        MutationManifest(
            'agent_turn',
            'turn:one',
            (
                _action('put', 'TURN_ONE_USER_MESSAGE'),
                _action('put', 'TURN_ONE_AGENT_MESSAGE'),
                _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
            ),
        )
    )
    second = rehearse_mutation_manifest(
        MutationManifest(
            'agent_turn',
            'turn:two',
            (
                _action('put', 'TURN_TWO_USER_MESSAGE'),
                _action('put', 'TURN_TWO_AGENT_MESSAGE'),
                _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
            ),
        )
    )

    first_messages = {key for key in first.action_keys if 'MESSAGE' in key}
    second_messages = {key for key in second.action_keys if 'MESSAGE' in key}
    assert first_messages.isdisjoint(second_messages)
    assert first.action_keys.count('UPDATE|MANIFEST#REALTIME_COUNTER|META') == 1
    assert second.action_keys.count('UPDATE|MANIFEST#REALTIME_COUNTER|META') == 1


def test_projection_replacement_counts_delete_and_put_actions() -> None:
    report = rehearse_mutation_manifest(
        MutationManifest(
            'claim_child',
            'claim:projection-change',
            (
                _action('delete', 'OLD_ORDER_PROJECTION', condition='attribute_exists(PK)'),
                _action('put', 'NEW_ORDER_PROJECTION'),
                _action('update', 'REALTIME_COUNTER', condition='sequence = :expected'),
            ),
        )
    )

    assert report.action_count == 3
    assert report.action_keys == (
        'DELETE|MANIFEST#OLD_ORDER_PROJECTION|META',
        'PUT|MANIFEST#NEW_ORDER_PROJECTION|META',
        'UPDATE|MANIFEST#REALTIME_COUNTER|META',
    )


@pytest.mark.parametrize(
    ('manifest', 'message'),
    [
        (
            MutationManifest('unknown', 'operation:unknown', (_action('put', 'ITEM'),)),
            'unsupported mutation family',
        ),
        (
            MutationManifest('claim_child', '', (_action('put', 'ITEM'),)),
            'requires an operation reference and actions',
        ),
        (
            MutationManifest('claim_child', 'operation:empty', ()),
            'requires an operation reference and actions',
        ),
        (
            MutationManifest(
                'claim_child', 'operation:unknown-action', (_action('merge', 'ITEM'),)
            ),
            'unsupported mutation action',
        ),
        (
            MutationManifest(
                'staff_ownership',
                'operation:missing-condition',
                (_action('condition_check', 'STAFF_PRESENCE'),),
            ),
            'condition_check requires a condition',
        ),
        (
            MutationManifest(
                'claim_child',
                'operation:duplicate-target',
                (
                    _action('delete', 'PROJECTION'),
                    _action('put', 'PROJECTION'),
                ),
            ),
            'targets one item more than once',
        ),
    ],
)
def test_explicit_manifest_rejects_invalid_operation_contracts(
    manifest: MutationManifest, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        rehearse_mutation_manifest(manifest)


def test_explicit_manifest_rejects_action_and_byte_limit_overflow() -> None:
    too_many = rehearse_mutation_manifest(
        MutationManifest(
            'agent_turn',
            'turn:too-many-actions',
            tuple(_action('put', f'ITEM_{index}') for index in range(101)),
        )
    )
    too_large = rehearse_mutation_manifest(
        MutationManifest(
            'agent_turn',
            'turn:too-large',
            tuple(_action('put', f'LARGE_{index}', payload_size=240 * 1024) for index in range(18)),
        )
    )

    assert too_many.action_count == 101
    assert too_many.within_limits is False
    assert too_large.action_count <= 100
    assert too_large.serialized_bytes > 4 * 1024 * 1024
    assert too_large.within_limits is False


@pytest.mark.parametrize(
    ('mutate', 'expected_code'),
    [
        (
            lambda records: _by_type(records, 'claim').update(revision=0),
            'INVALID_REVISION',
        ),
        (
            lambda records: _by_type(records, 'session').update(context_revision=4),
            'FUTURE_CONTEXT_REVISION',
        ),
        (
            lambda records: _by_type(records, 'idempotency').update(actor_id='authenticated:user'),
            'IDEMPOTENCY_ENVELOPE_MISMATCH',
        ),
        (
            _add_duplicate_message_turn_lookup,
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
    _add_message_turn(documents)
    _by_type(documents, 'claim')['customer_id'] = 'anonymous:browser'
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
    assert promotion.atomic_mutation.family == 'anonymous_promotion'
    assert promotion.atomic_mutation.action_count == 2 + 1 + 7
    assert promotion.atomic_mutation.action_count == len(promotion.atomic_mutation.action_keys)
    assert 'UPDATE|ENTITY#claim#clm_rehearsal|META' in promotion.atomic_mutation.action_keys
    assert (
        'DELETE|ACCESS#CUSTOMER_CLAIMS#anonymous:browser|'
        'UPDATED#99998210029599999999#clm_rehearsal' in promotion.atomic_mutation.action_keys
    )
    assert (
        'PUT|ACCESS#CUSTOMER_CLAIMS#customer:123|'
        'UPDATED#99998210029599999999#clm_rehearsal' in promotion.atomic_mutation.action_keys
    )
    assert 'UPDATE|SYSTEM#REALTIME|COUNTER' in promotion.atomic_mutation.action_keys
    assert any(
        key.startswith('PUT|LOOKUP#MESSAGE_TURN_IDEMPOTENCY#')
        for key in promotion.atomic_mutation.action_keys
    )
    assert promotion.atomic_mutation.within_limits is True

    promoted_documents = deepcopy(documents)
    _by_type(promoted_documents, 'claim')['customer_id'] = 'customer:123'
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
    _add_message_turn(documents)
    _by_type(documents, 'claim')['customer_id'] = 'anonymous:browser'
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
