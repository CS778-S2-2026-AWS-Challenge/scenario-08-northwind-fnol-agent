"""Rehearse the approved MongoDB-to-DynamoDB mapping without writing AWS data."""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from bson import ObjectId
from bson.timestamp import Timestamp
from pymongo import MongoClient
from pymongo.errors import PyMongoError
from pymongo.read_concern import ReadConcern

INVENTORY_VERSION = 'aws-migration-preparation@2d6499a7'
SOURCE_HEAD = '2d6499a7fb22a1e3a872f32241f8cdfa78e2dcf5'
RECONCILIATION_ISSUES = ('#984', '#985', '#986', '#987', '#786')
ITEM_BUDGET_BYTES = 300 * 1024
TRANSACTION_ACTION_LIMIT = 100
TRANSACTION_BUDGET_BYTES = 4 * 1024 * 1024
REVERSE_TIME_MAX = 99_999_999_999_999_999_999


@dataclass(frozen=True)
class RelationshipRule:
    """One executable source-record relationship."""

    field: str
    target_type: str
    target_field: str
    optional: bool = False
    same_claim: bool = True
    same_customer: bool = True


@dataclass(frozen=True)
class RecordMapping:
    """Executable migration contract for one approved MongoDB record type."""

    identity_fields: tuple[str, ...]
    ownership: str
    access_kinds: tuple[str, ...]
    order_fields: tuple[str, ...]
    uniqueness: tuple[tuple[str, ...], ...]
    mutation_family: str
    relationships: tuple[RelationshipRule, ...] = ()


def _rel(
    field: str,
    target_type: str,
    target_field: str,
    *,
    optional: bool = False,
    same_claim: bool = True,
    same_customer: bool = True,
) -> RelationshipRule:
    return RelationshipRule(field, target_type, target_field, optional, same_claim, same_customer)


CLAIM = _rel('claim_id', 'claim', 'claim_id')
SESSION = _rel('session_id', 'session', 'session_id')
TURN = _rel('turn_id', 'turn_plan', 'turn_id')
TASK = _rel('task_id', 'external_task', 'task_id')
EVIDENCE = _rel('evidence_id', 'evidence', 'evidence_id')
STAFF_SESSION = _rel(
    'session_id', 'staff_agent_session', 'session_id', same_claim=False, same_customer=False
)


def _mapping(
    identity: tuple[str, ...],
    ownership: str,
    access: tuple[str, ...],
    order: tuple[str, ...],
    uniqueness: tuple[tuple[str, ...], ...],
    family: str,
    *relationships: RelationshipRule,
) -> RecordMapping:
    return RecordMapping(identity, ownership, access, order, uniqueness, family, relationships)


RECORD_MAPPINGS: dict[str, RecordMapping] = {
    'claim': _mapping(
        ('claim_id',),
        'claim_owner',
        ('claim_owner', 'customer_claim', 'global_claim', 'claim_search'),
        ('updated_at',),
        (),
        'claim_creation',
    ),
    'session': _mapping(
        ('session_id',),
        'claim',
        ('claim_order', 'session_lookup', 'session_search'),
        ('started_at',),
        (),
        'session_checkpoint',
        CLAIM,
    ),
    'message': _mapping(
        ('message_id',),
        'claim_session',
        ('session_order', 'message_client_lookup'),
        ('created_at',),
        (('claim_id', 'client_message_id'),),
        'agent_turn',
        CLAIM,
        SESSION,
    ),
    'conversation_summary': _mapping(
        ('summary_id',),
        'claim_session',
        ('session_summary_order',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
    ),
    'follow_up': _mapping(
        ('follow_up_id',),
        'claim',
        ('claim_order', 'open_purpose_lookup', 'open_session_lookup'),
        ('created_at',),
        (('claim_id', 'purpose'), ('claim_id', 'source_session_id')),
        'session_checkpoint',
        CLAIM,
        _rel('source_session_id', 'session', 'session_id', optional=True),
    ),
    'agent_decision': _mapping(
        ('decision_id',),
        'claim_session',
        ('claim_order', 'trigger_lookup'),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
        _rel('trigger_message_id', 'message', 'message_id'),
    ),
    'claim_creation_operation': _mapping(
        ('operation_id',),
        'claim_customer',
        ('claim_order', 'claim_creation_unique'),
        ('updated_at',),
        (('claim_id',),),
        'claim_child',
        CLAIM,
        _rel('authorised_decision_id', 'agent_decision', 'decision_id'),
    ),
    'branch_evaluation': _mapping(
        ('evaluation_id',),
        'claim',
        ('claim_order',),
        ('created_at',),
        (),
        'session_checkpoint',
        CLAIM,
    ),
    'runtime_trace': _mapping(
        ('trace_id',),
        'claim_session',
        ('claim_order', 'trigger_lookup'),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
        _rel('trigger_message_id', 'message', 'message_id'),
    ),
    'turn_plan': _mapping(
        ('turn_id',),
        'claim_session',
        ('trigger_lookup', 'turn_bundle'),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
        _rel('trigger_message_id', 'message', 'message_id'),
    ),
    'agent_proposal': _mapping(
        ('proposal_id',),
        'claim_session_turn',
        ('turn_bundle',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
        TURN,
    ),
    'execution_plan': _mapping(
        ('execution_plan_id',),
        'claim_turn',
        ('turn_bundle',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        TURN,
    ),
    'action_envelope': _mapping(
        ('envelope_id',),
        'claim_turn',
        ('turn_order',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        TURN,
    ),
    'tool_result': _mapping(
        ('result_id',),
        'claim_turn',
        ('turn_order',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        TURN,
    ),
    'turn_result': _mapping(
        ('result_id',),
        'claim_session_turn',
        ('turn_bundle',),
        ('created_at',),
        (),
        'agent_turn',
        CLAIM,
        SESSION,
        TURN,
        _rel('trigger_message_id', 'message', 'message_id'),
        _rel('agent_message_id', 'message', 'message_id'),
        _rel('execution_plan_id', 'execution_plan', 'execution_plan_id'),
    ),
    'runtime_work_item': _mapping(
        ('work_item_id',),
        'claim_turn',
        ('claim_order', 'turn_order'),
        ('updated_at', 'created_at'),
        (),
        'agent_turn',
        CLAIM,
        TURN,
        _rel('session_id', 'session', 'session_id', optional=True),
    ),
    'asset': _mapping(
        ('asset_id',),
        'customer',
        ('customer_all', 'customer_active'),
        ('updated_at', 'created_at'),
        (),
        'claim_child',
    ),
    'claim_asset_snapshot': _mapping(
        ('snapshot_id',),
        'claim_customer',
        ('claim_order',),
        ('captured_at',),
        (),
        'claim_child',
        CLAIM,
        _rel('asset_id', 'asset', 'asset_id', same_claim=False),
    ),
    'motor_other_driver': _mapping(
        ('participant_id',),
        'claim_customer',
        ('claim_singleton',),
        ('created_at',),
        (('claim_id',),),
        'claim_child',
        CLAIM,
    ),
    'contents_item_evidence_association': _mapping(
        ('association_id',),
        'claim_customer_item',
        ('claim_order', 'contents_item_order', 'contents_evidence_unique'),
        ('created_at',),
        (('claim_id', 'item_id', 'evidence_id'),),
        'claim_child',
        CLAIM,
        EVIDENCE,
    ),
    'evidence': _mapping(
        ('evidence_id',),
        'claim_owner',
        ('claim_order', 'customer_evidence'),
        ('updated_at', 'created_at'),
        (),
        'claim_child',
        CLAIM,
    ),
    'evidence_claim_link': _mapping(
        ('link_id',),
        'cross_claim_customer',
        ('target_claim_order', 'evidence_claim_unique'),
        ('updated_at', 'created_at'),
        (('target_claim_id', 'evidence_id'),),
        'claim_child',
        _rel('source_claim_id', 'claim', 'claim_id', same_claim=False),
        _rel('target_claim_id', 'claim', 'claim_id', same_claim=False),
        EVIDENCE,
    ),
    'external_task': _mapping(
        ('task_id',), 'claim_customer', ('claim_order',), ('created_at',), (), 'claim_child', CLAIM
    ),
    'external_task_request': _mapping(
        ('request_id',),
        'claim_task_customer',
        ('claim_order', 'task_lookup', 'task_unique'),
        ('prepared_at',),
        (('task_id',),),
        'claim_child',
        CLAIM,
        TASK,
    ),
    'external_task_result': _mapping(
        ('result_id',),
        'claim_task_customer',
        ('claim_order', 'task_unique'),
        ('received_at',),
        (('claim_id', 'task_id'),),
        'claim_child',
        CLAIM,
        TASK,
    ),
    'external_task_evidence_link': _mapping(
        ('claim_id', 'evidence_id'),
        'claim_task_evidence',
        ('claim_order', 'task_lookup'),
        ('linked_at',),
        (('claim_id', 'evidence_id'),),
        'claim_child',
        CLAIM,
        TASK,
        EVIDENCE,
    ),
    'assessor_routing_operation': _mapping(
        ('operation_id',),
        'claim',
        ('claim_order',),
        ('created_at',),
        (),
        'claim_child',
        CLAIM,
        _rel('task_id', 'external_task', 'task_id', optional=True),
    ),
    'handoff': _mapping(
        ('handoff_id',),
        'claim_customer',
        ('claim_order', 'handoff_queue'),
        ('created_at',),
        (),
        'staff_ownership',
        CLAIM,
    ),
    'retrieval': _mapping(
        ('retrieval_id',),
        'claim_customer',
        ('claim_order',),
        ('retrieved_at', 'created_at'),
        (),
        'retrieval_bundle',
        CLAIM,
    ),
    'review_signal': _mapping(
        ('signal_id',),
        'claim_customer',
        ('claim_order',),
        ('created_at',),
        (),
        'retrieval_bundle',
        CLAIM,
    ),
    'signal_decision': _mapping(
        ('signal_decision_id',),
        'claim_staff',
        ('claim_order',),
        ('created_at',),
        (),
        'staff_ownership',
        CLAIM,
        _rel('signal_id', 'review_signal', 'signal_id', optional=True),
    ),
    'staff_action': _mapping(
        ('action_id',),
        'claim_staff',
        ('claim_order', 'assignee_order'),
        ('created_at',),
        (),
        'staff_ownership',
        CLAIM,
    ),
    'customer_update': _mapping(
        ('update_id',), 'claim', ('claim_order',), ('created_at',), (), 'staff_ownership', CLAIM
    ),
    'collaboration_request': _mapping(
        ('request_id',),
        'claim_staff',
        ('claim_order', 'target_staff_order'),
        ('created_at',),
        (),
        'staff_ownership',
        CLAIM,
    ),
    'claim_coworker': _mapping(
        ('coworker_id',),
        'claim_staff',
        ('claim_all', 'claim_active'),
        ('granted_at', 'created_at'),
        (),
        'staff_ownership',
        CLAIM,
    ),
    'staff_presence': _mapping(
        ('staff_id',), 'staff', ('staff_listing',), ('updated_at',), (), 'staff_ownership'
    ),
    'staff_agent_session': _mapping(
        ('session_id',),
        'staff',
        ('staff_session_order',),
        ('updated_at', 'created_at'),
        (),
        'staff_ownership',
    ),
    'staff_agent_message': _mapping(
        ('message_id',),
        'staff_session',
        ('staff_message_order', 'staff_message_client_lookup'),
        ('created_at',),
        (('staff_id', 'session_id', 'client_message_id'),),
        'staff_ownership',
        STAFF_SESSION,
    ),
    'staff_agent_execution': _mapping(
        ('execution_id',),
        'staff_session_claim',
        ('claim_order', 'staff_session_order'),
        ('created_at',),
        (),
        'staff_ownership',
        CLAIM,
        STAFF_SESSION,
        _rel(
            'message_id', 'staff_agent_message', 'message_id', same_claim=False, same_customer=False
        ),
    ),
    'audit_event': _mapping(
        ('event_id',),
        'audit_subject',
        (
            'audit_subject_order',
            'audit_global_order',
            'audit_type_order',
            'audit_subject_type_order',
            'audit_actor_order',
        ),
        ('created_at',),
        (),
        'staff_ownership',
        _rel('claim_id', 'claim', 'claim_id', optional=True),
    ),
    'realtime_sequence': _mapping((), 'system', (), (), (), 'claim_child'),
    'realtime_event': _mapping(
        ('event_id',),
        'system_event',
        ('realtime_order',),
        ('sequence',),
        (('sequence',),),
        'claim_child',
        _rel('claim_id', 'claim', 'claim_id', optional=True),
    ),
    'idempotency': _mapping(
        ('actor_id', 'route', 'key'),
        'actor_claim',
        ('claim_actor_idempotency', 'message_turn_lookup'),
        ('created_at',),
        (('actor_id', 'route', 'key'),),
        'session_checkpoint',
        _rel('claim_id', 'claim', 'claim_id', optional=True),
        _rel('session_id', 'session', 'session_id', optional=True),
        _rel('message_id', 'message', 'message_id', optional=True),
    ),
    'policy': _mapping(
        ('policy_id',),
        'customer',
        ('customer_all', 'customer_active'),
        ('created_at',),
        (),
        'claim_child',
    ),
    'identity_document': _mapping(
        ('identity_id',),
        'customer_protected',
        ('customer_all', 'customer_active'),
        ('created_at',),
        (),
        'claim_child',
    ),
    'payment_destination': _mapping(
        ('payment_destination_id',),
        'customer_protected',
        ('customer_all', 'customer_active'),
        ('created_at',),
        (),
        'claim_child',
    ),
}

IDENTITY_FIELDS = {
    record_type: mapping.identity_fields for record_type, mapping in RECORD_MAPPINGS.items()
}

ADAPTER_ONLY_FIELDS = frozenset({'_id', 'staff_search', 'realtime_order'})
CLAIM_SCOPED_EXCEPTIONS = frozenset({'claim', 'audit_event', 'realtime_event', 'idempotency'})
ORDER_FIELDS = {
    record_type: mapping.order_fields for record_type, mapping in RECORD_MAPPINGS.items()
}


@dataclass(frozen=True)
class SnapshotMetadata:
    """Non-secret coordinates for one MongoDB snapshot read."""

    database: str
    collection: str
    operation_time: str
    record_count: int


@dataclass(frozen=True)
class RehearsalFinding:
    """One fail-closed source or transformation finding."""

    code: str
    record_type: str
    source_ref: str
    detail: str


@dataclass(frozen=True)
class AtomicMutationReport:
    """Preflight result for one reconstructed atomic mutation."""

    family: str
    scope_ref: str
    action_count: int
    serialized_bytes: int
    within_limits: bool
    source_refs: tuple[str, ...]
    item_keys: tuple[str, ...]


@dataclass(frozen=True)
class RehearsalReport:
    """Safe summary of a local-only transformation and readback run."""

    evidence_level: str
    source_head: str
    inventory_version: str
    reconciliation_issues: tuple[str, ...]
    snapshot: SnapshotMetadata
    snapshot_fingerprint: str
    source_counts: dict[str, int]
    first_pass: dict[str, int]
    second_pass: dict[str, int]
    target_item_count: int
    atomic_mutations: tuple[AtomicMutationReport, ...]
    completion_marker: bool
    findings: tuple[RehearsalFinding, ...]


@dataclass(frozen=True)
class PlannedItem:
    """One deterministic target item used only by the local rehearsal."""

    pk: str
    sk: str
    record_type: str
    item_kind: str
    source_ref: str
    fingerprint: str
    payload: dict[str, Any]


@dataclass(frozen=True)
class PromotionRehearsal:
    """Local-only target metadata for one anonymous Claim-owner promotion."""

    items: tuple[PlannedItem, ...]
    restored_source_ref: str
    atomic_mutation: AtomicMutationReport


class LocalTarget:
    """In-memory readback target that classifies repeat writes deterministically."""

    def __init__(self) -> None:
        self._items: dict[tuple[str, str], PlannedItem] = {}

    @property
    def item_count(self) -> int:
        return len(self._items)

    def apply(self, items: Sequence[PlannedItem]) -> Counter[str]:
        results: Counter[str] = Counter()
        for item in items:
            key = (item.pk, item.sk)
            current = self._items.get(key)
            if current is None:
                self._items[key] = item
                results['migrated'] += 1
            elif current.fingerprint == item.fingerprint and current == item:
                results['unchanged'] += 1
            else:
                results['conflict'] += 1
        return results

    def stored_items(self) -> tuple[PlannedItem, ...]:
        """Return a deterministic snapshot of the local target."""

        return tuple(self._items[key] for key in sorted(self._items))

    def readback(self, documents: Sequence[Mapping[str, Any]]) -> bool:
        """Rehydrate source-domain records and verify payload plus projections."""

        rehydrated = _rehydrate_target(self.stored_items())
        expected = {
            _source_ref(document): _source_domain_record(document) for document in documents
        }
        if rehydrated != expected:
            return False
        for document in documents:
            record_type = str(document['record_type'])
            canonical = next(
                (
                    item
                    for item in self._items.values()
                    if item.source_ref == _source_ref(document) and item.item_kind == 'canonical'
                ),
                None,
            )
            if canonical is None:
                return False
            expected_refs = _reference_items(document, record_type, canonical)
            if any(self._items.get((item.pk, item.sk)) != item for item in expected_refs):
                return False
        return True


def _normalise(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, list | tuple):
        return [_normalise(item) for item in value]
    if isinstance(value, datetime):
        timestamp = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        return timestamp.astimezone(UTC).isoformat().replace('+00:00', 'Z')
    if isinstance(value, Timestamp):
        return {'time': value.time, 'increment': value.inc}
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, bytes):
        return {'sha256': sha256(value).hexdigest(), 'size_bytes': len(value)}
    return value


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalise(value), sort_keys=True, separators=(',', ':'), ensure_ascii=True
    ).encode()


def _digest(*components: str) -> str:
    encoded = ''.join(f'{len(value.encode())}:{value}' for value in components)
    return sha256(encoded.encode()).hexdigest()


def _source_ref(document: Mapping[str, Any]) -> str:
    return _digest(str(document.get('record_type', 'unknown')), str(document.get('_id', '')))[:16]


def _field(document: Mapping[str, Any], name: str) -> Any:
    value = document.get(name)
    nested = document.get('payload')
    if value is None and isinstance(nested, Mapping):
        value = nested.get(name)
    return value


def _source_domain_record(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: _normalise(value)
        for key, value in document.items()
        if key not in ADAPTER_ONLY_FIELDS and key != 'record_type'
    }


def _rehydrate_target(items: Sequence[PlannedItem]) -> dict[str, dict[str, Any]]:
    claim_owners = {
        item.pk: item.payload.get('owner_customer_id')
        for item in items
        if item.item_kind == 'claim_owner'
    }
    grouped: dict[str, list[PlannedItem]] = {}
    for item in items:
        if item.item_kind in {'canonical', 'fragment'}:
            grouped.setdefault(item.source_ref, []).append(item)
    rehydrated: dict[str, dict[str, Any]] = {}
    for source_ref, source_items in grouped.items():
        canonical = next((item for item in source_items if item.item_kind == 'canonical'), None)
        if canonical is None:
            continue
        payload = dict(canonical.payload)
        collection_presence = payload.pop('_migration_collections_present', [])
        owner_ref = payload.pop('owner_ref', None)
        if isinstance(owner_ref, str) and owner_ref.startswith('claim:'):
            owner_pk = f'ENTITY#claim#{owner_ref.removeprefix("claim:")}'
            owner = claim_owners.get(owner_pk)
            if owner is not None:
                payload['customer_id'] = owner
        if canonical.record_type == 'claim':
            if 'form' in collection_presence:
                payload['form'] = {
                    item.payload['field_code']: item.payload['value']
                    for item in source_items
                    if item.sk.startswith('FORM#')
                }
            if 'contents_items' in collection_presence:
                payload['contents_items'] = [
                    item.payload['value']
                    for item in sorted(source_items, key=lambda value: value.sk)
                    if item.sk.startswith('CONTENTS#')
                ]
            if 'external_service_consents' in collection_presence:
                payload['external_service_consents'] = [
                    item.payload['value']
                    for item in sorted(source_items, key=lambda value: value.sk)
                    if item.sk.startswith('CONSENT#')
                ]
        elif canonical.record_type == 'evidence' and 'material_history' in collection_presence:
            payload['material_history'] = [
                item.payload['value']
                for item in sorted(source_items, key=lambda value: value.sk)
                if item.sk.startswith('MATERIAL_VERSION#')
            ]
        rehydrated[source_ref] = _normalise(payload)
    return rehydrated


def _timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        timestamp = value
    elif isinstance(value, str):
        try:
            timestamp = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError as error:
            raise ValueError('ordering timestamp is invalid') from error
    else:
        raise ValueError('ordering timestamp is missing or invalid')
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return timestamp.astimezone(UTC)


def _ascending_time(value: Any) -> str:
    return _timestamp(value).isoformat(timespec='microseconds').replace('+00:00', 'Z')


def _reverse_time(value: Any) -> str:
    timestamp = _timestamp(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    elapsed = timestamp - epoch
    epoch_microseconds = (
        elapsed.days * 86_400_000_000 + elapsed.seconds * 1_000_000 + elapsed.microseconds
    )
    if epoch_microseconds < 0 or epoch_microseconds > REVERSE_TIME_MAX:
        raise ValueError('ordering timestamp is outside the supported range')
    return f'{REVERSE_TIME_MAX - epoch_microseconds:020d}'


def _identity(document: Mapping[str, Any], record_type: str) -> tuple[str, ...]:
    if record_type == 'realtime_sequence':
        return ('global',)
    values = tuple(_field(document, field) for field in IDENTITY_FIELDS[record_type])
    if any(not isinstance(value, str) or not value for value in values):
        raise ValueError('authoritative identity is missing or invalid')
    return values


def _canonical_items(
    document: Mapping[str, Any], record_type: str, identity: tuple[str, ...]
) -> list[PlannedItem]:
    payload = {
        key: _normalise(value)
        for key, value in document.items()
        if key not in ADAPTER_ONLY_FIELDS and key != 'record_type'
    }
    claim_id = _field(document, 'claim_id')
    if isinstance(claim_id, str) and record_type not in CLAIM_SCOPED_EXCEPTIONS:
        payload.pop('customer_id', None)
        payload['owner_ref'] = f'claim:{claim_id}'
    if record_type == 'idempotency':
        pk = f'IDEMPOTENCY#{_digest(*identity)}'
    elif record_type == 'realtime_sequence':
        pk = 'SYSTEM#REALTIME'
    elif record_type == 'realtime_event':
        sequence = _field(document, 'sequence')
        if not isinstance(sequence, int) or sequence < 1:
            raise ValueError('realtime sequence is missing or invalid')
        pk = 'SYSTEM#REALTIME'
        return [
            _planned_item(
                pk,
                f'EVENT#{sequence:020d}#{identity[0]}',
                record_type,
                'canonical',
                document,
                payload,
            )
        ]
    else:
        encoded_identity = identity[0] if len(identity) == 1 else _digest(*identity)
        pk = f'ENTITY#{record_type}#{encoded_identity}'
    sk = 'COUNTER' if record_type == 'realtime_sequence' else 'META'
    fragments: list[tuple[str, dict[str, Any]]] = []
    if record_type == 'claim':
        collection_presence = [
            field
            for field in ('form', 'contents_items', 'external_service_consents')
            if field in payload
        ]
        form = payload.pop('form', {})
        contents = payload.pop('contents_items', [])
        consents = payload.pop('external_service_consents', [])
        if collection_presence:
            payload['_migration_collections_present'] = collection_presence
        if (
            not isinstance(form, Mapping)
            or not isinstance(contents, list)
            or not isinstance(consents, list)
        ):
            raise ValueError('Claim collection fields have invalid persisted shapes')
        fragments.extend(
            (f'FORM#{field}', {'field_code': field, 'value': value})
            for field, value in form.items()
        )
        fragments.extend(
            (f'CONTENTS#{item.get("item_id", "")!s}', {'value': item})
            for item in contents
            if isinstance(item, Mapping) and item.get('item_id')
        )
        fragments.extend(
            (f'CONSENT#{consent.get("consent_ref", "")!s}', {'value': consent})
            for consent in consents
            if isinstance(consent, Mapping) and consent.get('consent_ref')
        )
        if len(fragments) != len(form) + len(contents) + len(consents):
            raise ValueError('Claim collection item identity is missing')
    elif record_type == 'evidence':
        history_present = 'material_history' in payload
        history = payload.pop('material_history', [])
        if history_present:
            payload['_migration_collections_present'] = ['material_history']
        if not isinstance(history, list):
            raise ValueError('Evidence material history has an invalid persisted shape')
        fragments.extend(
            (f'MATERIAL_VERSION#{version.get("version", "")!s}', {'value': version})
            for version in history
            if isinstance(version, Mapping) and version.get('version')
        )
        if len(fragments) != len(history):
            raise ValueError('Evidence material history version is missing')
    return [
        _planned_item(pk, sk, record_type, 'canonical', document, payload),
        *[
            _planned_item(pk, fragment_sk, record_type, 'fragment', document, fragment_payload)
            for fragment_sk, fragment_payload in sorted(fragments)
        ],
    ]


def _planned_item(
    pk: str,
    sk: str,
    record_type: str,
    item_kind: str,
    document: Mapping[str, Any],
    payload: dict[str, Any],
    *,
    source_ref: str | None = None,
) -> PlannedItem:
    content = {'pk': pk, 'sk': sk, 'record_type': record_type, 'payload': payload}
    return PlannedItem(
        pk=pk,
        sk=sk,
        record_type=record_type,
        item_kind=item_kind,
        source_ref=source_ref or _source_ref(document),
        fingerprint=sha256(_json_bytes(content)).hexdigest(),
        payload=payload,
    )


def _reference_items(
    document: Mapping[str, Any], record_type: str, canonical: PlannedItem
) -> list[PlannedItem]:
    mapping = RECORD_MAPPINGS[record_type]
    items: list[PlannedItem] = []
    for kind in mapping.access_kinds:
        items.extend(_build_access_items(document, record_type, canonical, kind))
    return items


def _required_text(document: Mapping[str, Any], field: str) -> str:
    value = _field(document, field)
    if not isinstance(value, str) or not value:
        raise ValueError(f'{field} is required for target access projection')
    return value


def _projection_item(
    document: Mapping[str, Any],
    canonical: PlannedItem,
    kind: str,
    pk: str,
    sk: str,
    scope: Mapping[str, Any],
) -> PlannedItem:
    return _planned_item(
        pk,
        sk,
        canonical.record_type,
        kind,
        document,
        {
            'canonical_pk': canonical.pk,
            'canonical_sk': canonical.sk,
            'scope': dict(scope),
        },
    )


def _record_identity_text(document: Mapping[str, Any], record_type: str) -> str:
    identity = _identity(document, record_type)
    return identity[0] if len(identity) == 1 else _digest(*identity)


def _claim_search_values(document: Mapping[str, Any]) -> dict[str, str]:
    claim_id = _required_text(document, 'claim_id')
    values = {
        'claim_reference': claim_id,
        'customer_reference': _required_text(document, 'customer_id'),
    }
    search = document.get('staff_search')
    if not isinstance(search, Mapping):
        search = {}
    for field in (
        'external_reference',
        'created_date',
        'incident_date',
        'product_family',
        'lifecycle_state',
        'assignee_id',
        'queue',
    ):
        value = search.get(field)
        if value is not None and str(value):
            values[field] = str(value)
    external = values.get('external_reference')
    if external is not None:
        values['claim_reference_external'] = external
    return values


def _build_access_items(
    document: Mapping[str, Any],
    record_type: str,
    canonical: PlannedItem,
    kind: str,
) -> list[PlannedItem]:
    entity_id = _record_identity_text(document, record_type)
    order_field, order_value = _order_coordinate(document, record_type)
    claim_id = _field(document, 'claim_id')
    customer_id = _field(document, 'customer_id')
    if kind == 'realtime_order':
        return []
    if kind == 'claim_owner':
        return [
            _planned_item(
                canonical.pk,
                'OWNER',
                record_type,
                kind,
                document,
                {'owner_customer_id': _required_text(document, 'customer_id')},
            )
        ]
    if kind == 'customer_claim':
        pk = f'ACCESS#CUSTOMER_CLAIMS#{_required_text(document, "customer_id")}'
        sk = f'UPDATED#{_reverse_time(_field(document, "updated_at"))}#{entity_id}'
        return [
            _projection_item(
                document,
                canonical,
                kind,
                pk,
                sk,
                {'customer_id': customer_id, 'claim_id': claim_id},
            )
        ]
    if kind == 'global_claim':
        sk = f'UPDATED#{_reverse_time(_field(document, "updated_at"))}#{entity_id}'
        return [
            _projection_item(
                document, canonical, kind, 'ACCESS#CLAIMS#ALL', sk, {'claim_id': claim_id}
            )
        ]
    if kind == 'claim_search':
        sk = f'UPDATED#{_reverse_time(_field(document, "updated_at"))}#{entity_id}'
        output: list[PlannedItem] = []
        for field, value in sorted(_claim_search_values(document).items()):
            public_field = 'claim_reference' if field == 'claim_reference_external' else field
            pk = f'ACCESS#CLAIM_SEARCH#{public_field}#{_digest(value)}'
            output.append(
                _projection_item(
                    document,
                    canonical,
                    kind,
                    pk,
                    sk,
                    {'field': public_field, 'value': value, 'claim_id': claim_id},
                )
            )
        return output
    if kind == 'claim_order':
        claim = _required_text(document, 'claim_id')
        pk = f'ACCESS#CLAIM#{claim}#{record_type}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'claim_id': claim})]
    if kind in {'session_order', 'session_summary_order'}:
        session = _required_text(document, 'session_id')
        pk = f'ACCESS#SESSION#{session}#{record_type}'
        sk = f'CREATED#{_ascending_time(_field(document, "created_at"))}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'session_id': session})]
    if kind in {'turn_order', 'turn_bundle'}:
        turn = _required_text(document, 'turn_id')
        pk = f'ACCESS#TURN#{turn}#{record_type}'
        sk = f'CREATED#{_ascending_time(_field(document, "created_at"))}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'turn_id': turn})]
    if kind in {'customer_all', 'customer_active'}:
        if kind == 'customer_active' and (
            _field(document, 'active') is False
            or _field(document, 'status') in {'inactive', 'revoked', 'closed'}
        ):
            return []
        customer = _required_text(document, 'customer_id')
        state = 'ACTIVE' if kind == 'customer_active' else 'ALL'
        configured_field = (
            'updated_at' if _field(document, 'updated_at') is not None else 'created_at'
        )
        configured_time = _ascending_time(_field(document, configured_field))
        pk = f'ACCESS#CUSTOMER#{customer}#{record_type}#{state}'
        sk = f'{configured_field.upper()}#{configured_time}#{entity_id}'
        return [
            _projection_item(
                document, canonical, kind, pk, sk, {'customer_id': customer, 'state': state}
            )
        ]
    if kind == 'staff_session_order':
        staff = _required_text(document, 'staff_id')
        session = _required_text(document, 'session_id')
        pk = f'ACCESS#STAFF_AGENT#{staff}#SESSIONS'
        sk = f'UPDATED#{_reverse_time(_field(document, "updated_at"))}#{session}'
        return [_projection_item(document, canonical, kind, pk, sk, {'staff_id': staff})]
    if kind == 'staff_message_order':
        session = _required_text(document, 'session_id')
        message = _required_text(document, 'message_id')
        pk = f'ACCESS#STAFF_AGENT_SESSION#{session}#MESSAGES'
        sk = f'CREATED#{_ascending_time(_field(document, "created_at"))}#{message}'
        return [_projection_item(document, canonical, kind, pk, sk, {'session_id': session})]
    if kind == 'claim_actor_idempotency':
        claim = _required_text(document, 'claim_id')
        actor = _required_text(document, 'actor_id')
        route = _required_text(document, 'route')
        key = _required_text(document, 'key')
        pk = f'ACCESS#CLAIM_IDEMPOTENCY#{_digest(claim, actor)}'
        sk = f'RECORD#{_digest(route, key)}'
        return [
            _projection_item(
                document,
                canonical,
                kind,
                pk,
                sk,
                {'claim_id': claim, 'actor_id': actor, 'route': route, 'key': key},
            )
        ]
    return _build_exact_lookup_or_special_access(
        document, record_type, canonical, kind, entity_id, order_field, order_value
    )


def _lookup_item(
    document: Mapping[str, Any],
    canonical: PlannedItem,
    kind: str,
    lookup_type: str,
    components: Sequence[str],
    scope: Mapping[str, Any],
) -> PlannedItem:
    pk = f'LOOKUP#{lookup_type}#{_digest(*components)}'
    return _projection_item(document, canonical, kind, pk, 'META', scope)


def _unique_item(
    document: Mapping[str, Any],
    canonical: PlannedItem,
    kind: str,
    constraint: str,
    components: Sequence[str],
    scope: Mapping[str, Any],
) -> PlannedItem:
    pk = f'UNIQUE#{constraint}#{_digest(*components)}'
    return _projection_item(document, canonical, kind, pk, 'META', scope)


def _build_exact_lookup_or_special_access(
    document: Mapping[str, Any],
    record_type: str,
    canonical: PlannedItem,
    kind: str,
    entity_id: str,
    order_field: str,
    order_value: str,
) -> list[PlannedItem]:
    claim = _field(document, 'claim_id')
    session = _field(document, 'session_id')
    if kind == 'message_client_lookup':
        client = _field(document, 'client_message_id')
        if not isinstance(client, str) or not client:
            return []
        claim_text = _required_text(document, 'claim_id')
        return [
            _lookup_item(
                document,
                canonical,
                kind,
                'MESSAGE_CLIENT',
                (claim_text, client),
                {'claim_id': claim_text, 'client_message_id': client},
            )
        ]
    if kind == 'staff_message_client_lookup':
        client = _field(document, 'client_message_id')
        if not isinstance(client, str) or not client:
            return []
        staff = _required_text(document, 'staff_id')
        session_text = _required_text(document, 'session_id')
        return [
            _lookup_item(
                document,
                canonical,
                kind,
                'STAFF_AGENT_CLIENT',
                (staff, session_text, client),
                {'staff_id': staff, 'session_id': session_text, 'client_message_id': client},
            )
        ]
    if kind == 'message_turn_lookup':
        message = _field(document, 'message_id')
        if not isinstance(message, str) or not message:
            return []
        actor = _required_text(document, 'actor_id')
        route = _required_text(document, 'route')
        claim_text = _required_text(document, 'claim_id')
        pk = f'LOOKUP#MESSAGE_TURN_IDEMPOTENCY#{_digest(actor, route, claim_text, message)}'
        return [
            _projection_item(
                document,
                canonical,
                kind,
                pk,
                'META',
                {'actor_id': actor, 'route': route, 'claim_id': claim_text, 'message_id': message},
            )
        ]
    if kind == 'session_lookup':
        claim_text = _required_text(document, 'claim_id')
        session_text = _required_text(document, 'session_id')
        return [
            _lookup_item(
                document,
                canonical,
                kind,
                'CLAIM_SESSION',
                (claim_text, session_text),
                {'claim_id': claim_text, 'session_id': session_text},
            )
        ]
    if kind == 'session_search':
        claim_text = _required_text(document, 'claim_id')
        session_text = _required_text(document, 'session_id')
        started = _timestamp(_field(document, 'started_at'))
        reverse_started = _reverse_time(started)
        sk = f'STARTED#{reverse_started}#{session_text}'
        date_value = started.date().isoformat()
        output = [
            _projection_item(
                document,
                canonical,
                kind,
                f'ACCESS#CLAIM_SESSIONS_DATE#{claim_text}#{date_value}',
                sk,
                {'claim_id': claim_text, 'started_date': date_value},
            )
        ]
        status = _field(document, 'status')
        if status is not None and str(status):
            output.append(
                _projection_item(
                    document,
                    canonical,
                    kind,
                    f'ACCESS#CLAIM_SESSIONS_STATUS#{claim_text}#{status}',
                    sk,
                    {'claim_id': claim_text, 'status': str(status)},
                )
            )
        return output
    if kind == 'trigger_lookup':
        trigger = _required_text(document, 'trigger_message_id')
        components = (str(claim or ''), str(session or ''), trigger, record_type)
        return [
            _lookup_item(
                document,
                canonical,
                kind,
                'TRIGGER',
                components,
                {
                    'claim_id': claim,
                    'session_id': session,
                    'trigger_message_id': trigger,
                    'record_type': record_type,
                },
            )
        ]
    uniqueness: dict[str, tuple[str, tuple[str, ...], dict[str, Any]]] = {}
    if kind == 'claim_singleton':
        claim_text = _required_text(document, 'claim_id')
        uniqueness[kind] = ('MOTOR_OTHER_DRIVER_CLAIM', (claim_text,), {'claim_id': claim_text})
    elif kind == 'contents_evidence_unique':
        values = tuple(
            _required_text(document, field) for field in ('claim_id', 'item_id', 'evidence_id')
        )
        uniqueness[kind] = (
            'CONTENTS_ITEM_EVIDENCE',
            values,
            {'claim_id': values[0], 'item_id': values[1], 'evidence_id': values[2]},
        )
    elif kind == 'evidence_claim_unique':
        values = tuple(
            _required_text(document, field) for field in ('target_claim_id', 'evidence_id')
        )
        uniqueness[kind] = (
            'EVIDENCE_CLAIM_TARGET',
            values,
            {'target_claim_id': values[0], 'evidence_id': values[1]},
        )
    elif kind == 'task_unique':
        task = _required_text(document, 'task_id')
        constraint = (
            'EXTERNAL_TASK_REQUEST'
            if record_type == 'external_task_request'
            else 'EXTERNAL_TASK_RESULT'
        )
        task_values = (
            (task,)
            if record_type == 'external_task_request'
            else (_required_text(document, 'claim_id'), task)
        )
        uniqueness[kind] = (constraint, task_values, {'task_id': task, 'claim_id': claim})
    elif kind == 'claim_creation_unique':
        claim_text = _required_text(document, 'claim_id')
        uniqueness[kind] = (
            'CLAIM_CREATION_OPERATION_CLAIM',
            (claim_text,),
            {'claim_id': claim_text},
        )
    elif kind in {'open_purpose_lookup', 'open_session_lookup'}:
        status = str(_field(document, 'status') or '')
        if status not in {'open', 'pending', 'blocked'}:
            return []
        claim_text = _required_text(document, 'claim_id')
        field = 'purpose' if kind == 'open_purpose_lookup' else 'source_session_id'
        value = _field(document, field)
        if not isinstance(value, str) or not value:
            return []
        constraint = 'OPEN_FOLLOW_UP_PURPOSE' if field == 'purpose' else 'OPEN_FOLLOW_UP_SESSION'
        uniqueness[kind] = (constraint, (claim_text, value), {'claim_id': claim_text, field: value})
    if kind in uniqueness:
        constraint, unique_components, scope = uniqueness[kind]
        return [_unique_item(document, canonical, kind, constraint, unique_components, scope)]
    if kind == 'contents_item_order':
        claim_text = _required_text(document, 'claim_id')
        item = _required_text(document, 'item_id')
        pk = f'ACCESS#CLAIM_CONTENTS_ITEM#{claim_text}#{item}'
        sk = f'CREATED#{_ascending_time(_field(document, "created_at"))}#{entity_id}'
        return [
            _projection_item(
                document, canonical, kind, pk, sk, {'claim_id': claim_text, 'item_id': item}
            )
        ]
    if kind == 'target_claim_order':
        target = _required_text(document, 'target_claim_id')
        pk = f'ACCESS#CLAIM#{target}#{record_type}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'target_claim_id': target})]
    if kind == 'task_lookup':
        task = _required_text(document, 'task_id')
        pk = f'ACCESS#TASK#{task}#{record_type}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'task_id': task})]
    if kind == 'customer_evidence':
        customer = _required_text(document, 'customer_id')
        pk = f'ACCESS#CUSTOMER#{customer}#evidence#ALL'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'customer_id': customer})]
    if kind in {'claim_all', 'claim_active'}:
        if kind == 'claim_active' and _field(document, 'active') is False:
            return []
        claim_text = _required_text(document, 'claim_id')
        state = 'ACTIVE' if kind == 'claim_active' else 'ALL'
        pk = f'ACCESS#CLAIM#{claim_text}#{record_type}#{state}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [
            _projection_item(
                document, canonical, kind, pk, sk, {'claim_id': claim_text, 'state': state}
            )
        ]
    if kind == 'staff_listing':
        staff = _required_text(document, 'staff_id')
        sk = f'UPDATED#{_reverse_time(_field(document, "updated_at"))}#{staff}'
        return [
            _projection_item(
                document, canonical, kind, 'ACCESS#STAFF_PRESENCE#ALL', sk, {'staff_id': staff}
            )
        ]
    if kind in {'assignee_order', 'target_staff_order'}:
        field = 'assignee_id' if kind == 'assignee_order' else 'target_staff_id'
        staff = _field(document, field)
        if not isinstance(staff, str) or not staff:
            return []
        pk = f'ACCESS#STAFF#{staff}#{record_type}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {field: staff})]
    if kind == 'handoff_queue':
        queue = _field(document, 'queue')
        if not isinstance(queue, str) or not queue:
            return []
        pk = f'ACCESS#HANDOFF_QUEUE#{queue}'
        sk = f'{order_field.upper()}#{order_value}#{entity_id}'
        return [_projection_item(document, canonical, kind, pk, sk, {'queue': queue})]
    if kind.startswith('audit_'):
        return _build_audit_access_items(document, canonical, kind, entity_id)
    raise ValueError(f'unsupported access projection kind: {kind}')


def _build_audit_access_items(
    document: Mapping[str, Any], canonical: PlannedItem, kind: str, event_id: str
) -> list[PlannedItem]:
    created = _ascending_time(_field(document, 'created_at'))
    sk = f'TIME#{created}#{event_id}'
    subject = _field(document, 'subject')
    actor = _field(document, 'actor')
    if kind == 'audit_subject_order':
        if not isinstance(subject, Mapping):
            raise ValueError('Audit subject is required for subject projection')
        values = (
            str(subject.get('subject_type') or ''),
            str(subject.get('subject_id') or ''),
            str(subject.get('claim_id') or ''),
        )
        if not values[0] or not values[1]:
            raise ValueError('Audit subject identity is incomplete')
        pk = f'ACCESS#AUDIT_SUBJECT#{_digest(*values)}'
        return [
            _projection_item(
                document,
                canonical,
                kind,
                pk,
                sk,
                {'subject_type': values[0], 'subject_id': values[1], 'claim_id': values[2] or None},
            )
        ]
    if kind == 'audit_global_order':
        return [_projection_item(document, canonical, kind, 'ACCESS#AUDIT#ALL', sk, {})]
    if kind == 'audit_type_order':
        field = 'event_type'
        filter_name = 'EVENT_TYPE'
    elif kind == 'audit_subject_type_order':
        field = 'subject_type'
        filter_name = 'SUBJECT_TYPE'
    else:
        field = 'actor_id'
        filter_name = 'ACTOR'
    value = _field(document, field)
    if field == 'subject_type' and isinstance(subject, Mapping):
        value = subject.get('subject_type')
    if field == 'actor_id' and isinstance(actor, Mapping):
        value = actor.get('actor_id')
    if not isinstance(value, str) or not value:
        return []
    pk = f'ACCESS#AUDIT#{filter_name}#{_digest(value)}'
    return [_projection_item(document, canonical, kind, pk, sk, {field: value})]


def _order_coordinate(document: Mapping[str, Any], record_type: str) -> tuple[str, str]:
    for field in ORDER_FIELDS.get(record_type, ('created_at', 'updated_at')):
        value = _field(document, field)
        if value is not None:
            if field == 'sequence':
                if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                    raise ValueError('ordering sequence is missing or invalid')
                return field, f'{value:020d}'
            return field, _ascending_time(value)
    return 'identity', _source_ref(document)


def plan_record(document: Mapping[str, Any]) -> list[PlannedItem]:
    """Build every canonical, fragment, and access item for one approved record.

    Args:
        document: One source MongoDB record from the consistent snapshot.

    Returns:
        The deterministic local target write plan for that source record.

    Raises:
        ValueError: The record type, identity, shape, or ordering is invalid.
    """

    record_type = str(document.get('record_type', 'unknown'))
    if record_type not in RECORD_MAPPINGS:
        raise ValueError('record type is not allowlisted')
    canonical_items = _canonical_items(document, record_type, _identity(document, record_type))
    return [
        *canonical_items,
        *_reference_items(document, record_type, canonical_items[0]),
    ]


def _idempotency_generation_items(
    documents: Sequence[Mapping[str, Any]],
) -> list[PlannedItem]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = {}
    for document in documents:
        if document.get('record_type') != 'idempotency':
            continue
        claim_id = _field(document, 'claim_id')
        actor_id = _field(document, 'actor_id')
        if isinstance(claim_id, str) and claim_id and isinstance(actor_id, str) and actor_id:
            grouped.setdefault((claim_id, actor_id), []).append(document)
    items: list[PlannedItem] = []
    for (claim_id, actor_id), records in sorted(grouped.items()):
        pk = f'IDEMPOTENCY_ACTOR#{_digest(claim_id, actor_id)}'
        payload = {
            'claim_id': claim_id,
            'actor_id': actor_id,
            'generation': len(records),
            'retired': False,
        }
        items.append(
            _planned_item(
                pk,
                'STATE',
                'idempotency',
                'claim_actor_generation',
                records[0],
                payload,
                source_ref=_digest(pk, 'STATE')[:16],
            )
        )
    return items


def rehearse_anonymous_promotion(
    documents: Sequence[Mapping[str, Any]],
    *,
    claim_id: str,
    anonymous_actor: str,
    authenticated_actor: str,
    route: str,
    message_id: str,
    retry_key: str,
) -> PromotionRehearsal:
    """Rehearse #991 aliases and historical-turn lookup without changing source data."""

    claim = next(
        (
            document
            for document in documents
            if document.get('record_type') == 'claim' and _field(document, 'claim_id') == claim_id
        ),
        None,
    )
    if claim is None or _field(claim, 'customer_id') != anonymous_actor:
        raise ValueError('anonymous Claim ownership is absent or stale')
    if not authenticated_actor or authenticated_actor == anonymous_actor:
        raise ValueError('authenticated actor must be a distinct non-empty identity')
    selected = [
        document
        for document in documents
        if document.get('record_type') == 'idempotency'
        and _field(document, 'claim_id') == claim_id
        and _field(document, 'actor_id') == anonymous_actor
    ]
    if not selected:
        raise ValueError('Claim has no anonymous idempotency records to promote')
    source_turn = next(
        (
            document
            for document in selected
            if _field(document, 'route') == route and _field(document, 'message_id') == message_id
        ),
        None,
    )
    if source_turn is None or retry_key == _field(source_turn, 'key'):
        raise ValueError('different-key historical message turn is absent')

    output: list[PlannedItem] = []
    occupied: set[tuple[str, str]] = set()
    restored_source_ref = _source_ref(source_turn)
    for document in sorted(selected, key=_source_ref):
        source_actor = str(_field(document, 'actor_id'))
        source_route = str(_field(document, 'route'))
        source_key = str(_field(document, 'key'))
        canonical_pk = f'IDEMPOTENCY#{_digest(source_actor, source_route, source_key)}'
        alias_pk = f'IDEMPOTENCY#{_digest(authenticated_actor, source_route, source_key)}'
        collision = any(
            candidate.get('record_type') == 'idempotency'
            and _field(candidate, 'actor_id') == authenticated_actor
            and _field(candidate, 'route') == source_route
            and _field(candidate, 'key') == source_key
            for candidate in documents
        )
        if collision or (alias_pk, 'META') in occupied:
            raise ValueError('authenticated exact-key alias collides')
        occupied.add((alias_pk, 'META'))
        output.append(
            _planned_item(
                alias_pk,
                'META',
                'idempotency',
                'promotion_alias',
                document,
                {
                    'canonical_pk': canonical_pk,
                    'canonical_sk': 'META',
                    'claim_id': claim_id,
                    'authenticated_actor_id': authenticated_actor,
                    'original_actor_id': source_actor,
                    'route': source_route,
                    'key': source_key,
                    'request_fingerprint': _field(document, 'request_fingerprint'),
                },
            )
        )
        source_message_id = _field(document, 'message_id')
        if isinstance(source_message_id, str) and source_message_id:
            lookup_pk = 'LOOKUP#MESSAGE_TURN_IDEMPOTENCY#' + _digest(
                authenticated_actor, source_route, claim_id, source_message_id
            )
            if (lookup_pk, 'META') in occupied:
                raise ValueError('authenticated message-turn lookup collides')
            occupied.add((lookup_pk, 'META'))
            output.append(
                _planned_item(
                    lookup_pk,
                    'META',
                    'idempotency',
                    'promotion_message_turn_lookup',
                    document,
                    {
                        'canonical_pk': canonical_pk,
                        'canonical_sk': 'META',
                        'claim_id': claim_id,
                        'authenticated_actor_id': authenticated_actor,
                        'original_actor_id': source_actor,
                        'route': source_route,
                        'message_id': source_message_id,
                        'request_fingerprint': _field(document, 'request_fingerprint'),
                        'message_turn_kind': _field(document, 'message_turn_kind'),
                        'message_turn_revision': _field(document, 'message_turn_revision'),
                    },
                )
            )
    state_pk = f'IDEMPOTENCY_ACTOR#{_digest(claim_id, anonymous_actor)}'
    output.append(
        _planned_item(
            state_pk,
            'STATE',
            'idempotency',
            'promotion_retirement',
            claim,
            {
                'claim_id': claim_id,
                'actor_id': anonymous_actor,
                'generation': len(selected),
                'retired': True,
                'retired_to_actor_id': authenticated_actor,
            },
            source_ref=_digest(state_pk, 'STATE')[:16],
        )
    )
    matching_lookup = next(
        (
            item
            for item in output
            if item.item_kind == 'promotion_message_turn_lookup'
            and item.payload['route'] == route
            and item.payload['message_id'] == message_id
        ),
        None,
    )
    if matching_lookup is None or matching_lookup.source_ref != restored_source_ref:
        raise ValueError('authenticated historical message turn cannot be restored')
    base_actions = (
        'claim_meta_update',
        'claim_owner_update',
        'old_customer_projection_delete',
        'new_customer_projection_put',
        'realtime_counter_update',
        'realtime_event_put',
    )
    serialized_bytes = sum(len(_json_bytes(asdict(item))) for item in output) + sum(
        len(_json_bytes({'action': action, 'claim_id': claim_id})) for action in base_actions
    )
    action_count = len(output) + len(base_actions)
    atomic_mutation = AtomicMutationReport(
        'anonymous_promotion',
        f'claim:{claim_id}',
        action_count,
        serialized_bytes,
        action_count <= TRANSACTION_ACTION_LIMIT and serialized_bytes <= TRANSACTION_BUDGET_BYTES,
        tuple(sorted({_source_ref(claim), *(_source_ref(record) for record in selected)})),
        tuple(
            [
                *(f'{item.pk}|{item.sk}' for item in output),
                *(f'ACTION|{action}' for action in base_actions),
            ]
        ),
    )
    if not atomic_mutation.within_limits:
        raise ValueError('anonymous promotion exceeds the target transaction budget')
    return PromotionRehearsal(tuple(output), restored_source_ref, atomic_mutation)


def _relationship_findings(documents: Sequence[Mapping[str, Any]]) -> list[RehearsalFinding]:
    indexes: dict[tuple[str, str], dict[str, Mapping[str, Any]]] = {}
    for record_type, record_mapping in RECORD_MAPPINGS.items():
        fields = set(record_mapping.identity_fields)
        for candidate in RECORD_MAPPINGS.values():
            for relationship in candidate.relationships:
                if relationship.target_type == record_type:
                    fields.add(relationship.target_field)
        for field in fields:
            index: dict[str, Mapping[str, Any]] = {}
            for document in documents:
                if document.get('record_type') != record_type:
                    continue
                value = _field(document, field)
                if isinstance(value, str) and value:
                    index[value] = document
            indexes[(record_type, field)] = index
    claims = indexes[('claim', 'claim_id')]
    findings: list[RehearsalFinding] = []
    for document in documents:
        record_type = str(document.get('record_type', 'unknown'))
        mapping = RECORD_MAPPINGS.get(record_type)
        if mapping is None:
            continue
        revision = _field(document, 'revision')
        if revision is not None and (
            isinstance(revision, bool) or not isinstance(revision, int) or revision < 1
        ):
            findings.append(
                _finding('INVALID_REVISION', document, 'revision must be a positive integer')
            )
        if record_type == 'idempotency':
            nested = document.get('payload')
            if isinstance(nested, Mapping):
                for field in ('actor_id', 'route', 'key'):
                    if field in document and field in nested and document[field] != nested[field]:
                        findings.append(
                            _finding(
                                'IDEMPOTENCY_ENVELOPE_MISMATCH',
                                document,
                                f'{field} differs between envelope and payload',
                            )
                        )
        claim_id = _field(document, 'claim_id')
        if isinstance(claim_id, str) and record_type != 'claim':
            claim = claims.get(claim_id)
            if claim is None:
                findings.append(_finding('DANGLING_CLAIM', document, 'parent Claim is absent'))
            else:
                owner = _field(document, 'customer_id')
                claim_owner = _field(claim, 'customer_id')
                if owner is not None and owner != claim_owner:
                    findings.append(
                        _finding(
                            'CROSS_OWNER_RECORD', document, 'customer differs from Claim owner'
                        )
                    )
                context_revision = _field(document, 'context_revision')
                claim_revision = _field(claim, 'revision')
                if (
                    isinstance(context_revision, int)
                    and not isinstance(context_revision, bool)
                    and isinstance(claim_revision, int)
                    and not isinstance(claim_revision, bool)
                    and context_revision > claim_revision
                ):
                    findings.append(
                        _finding(
                            'FUTURE_CONTEXT_REVISION',
                            document,
                            'record context revision exceeds its Claim revision',
                        )
                    )
        for relationship in mapping.relationships:
            source_value = _field(document, relationship.field)
            if source_value is None and relationship.optional:
                continue
            if not isinstance(source_value, str) or not source_value:
                findings.append(
                    _finding(
                        'MISSING_RELATIONSHIP',
                        document,
                        f'{relationship.field} must identify {relationship.target_type}',
                    )
                )
                continue
            target = indexes[(relationship.target_type, relationship.target_field)].get(
                source_value
            )
            if target is None:
                findings.append(
                    _finding(
                        'DANGLING_RELATIONSHIP',
                        document,
                        f'{relationship.field} does not resolve to {relationship.target_type}',
                    )
                )
                continue
            target_claim = _field(target, 'claim_id')
            if relationship.target_type == 'claim':
                target_claim = _field(target, 'claim_id')
            if (
                relationship.same_claim
                and isinstance(claim_id, str)
                and isinstance(target_claim, str)
                and target_claim != claim_id
            ):
                findings.append(
                    _finding(
                        'CROSS_SCOPE_RELATIONSHIP',
                        document,
                        f'{relationship.field} resolves outside the Claim scope',
                    )
                )
            owner = _field(document, 'customer_id')
            target_owner = _field(target, 'customer_id')
            if (
                relationship.same_customer
                and isinstance(owner, str)
                and isinstance(target_owner, str)
                and owner != target_owner
            ):
                findings.append(
                    _finding(
                        'CROSS_OWNER_RELATIONSHIP',
                        document,
                        f'{relationship.field} resolves outside the customer scope',
                    )
                )
            if relationship.target_type == 'staff_agent_session' and _field(
                target, 'staff_id'
            ) != _field(document, 'staff_id'):
                findings.append(
                    _finding(
                        'CROSS_SCOPE_RELATIONSHIP',
                        document,
                        f'{relationship.field} resolves outside the staff scope',
                    )
                )
        if record_type == 'contents_item_evidence_association':
            claim = claims.get(str(claim_id))
            contents = _field(claim or {}, 'contents_items') or []
            item_id = _field(document, 'item_id')
            if not any(
                isinstance(item, Mapping) and item.get('item_id') == item_id for item in contents
            ):
                findings.append(
                    _finding(
                        'DANGLING_CONTENTS_ITEM', document, 'Contents item is absent from Claim'
                    )
                )
        if record_type == 'evidence_claim_link':
            evidence = indexes[('evidence', 'evidence_id')].get(
                str(_field(document, 'evidence_id'))
            )
            if evidence is not None and _field(evidence, 'claim_id') != _field(
                document, 'source_claim_id'
            ):
                findings.append(
                    _finding(
                        'CROSS_SCOPE_RELATIONSHIP',
                        document,
                        'Evidence does not belong to the source Claim',
                    )
                )
        if record_type == 'review_signal':
            source_refs = _field(document, 'source_refs')
            retrieval_ids = indexes[('retrieval', 'retrieval_id')]
            linked = [
                retrieval_ids[value]
                for value in source_refs or []
                if isinstance(value, str) and value in retrieval_ids
            ]
            if not linked or any(_field(value, 'claim_id') != claim_id for value in linked):
                findings.append(
                    _finding(
                        'DANGLING_RETRIEVAL',
                        document,
                        'Review Signal has no same-Claim Retrieval source',
                    )
                )
        if record_type == 'audit_event':
            subject = _field(document, 'subject')
            subject_claim = subject.get('claim_id') if isinstance(subject, Mapping) else None
            if subject_claim is not None and str(subject_claim) not in claims:
                findings.append(
                    _finding('DANGLING_AUDIT_SCOPE', document, 'Audit Claim subject is absent')
                )
    return findings


def _uniqueness_findings(documents: Sequence[Mapping[str, Any]]) -> list[RehearsalFinding]:
    seen: dict[tuple[str, tuple[Any, ...]], Mapping[str, Any]] = {}
    unique_tuples: dict[tuple[str, tuple[Any, ...]], Mapping[str, Any]] = {}
    message_turns: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    findings: list[RehearsalFinding] = []
    for document in documents:
        record_type = str(document.get('record_type', 'unknown'))
        identity = tuple(_field(document, field) for field in IDENTITY_FIELDS.get(record_type, ()))
        lookup = (record_type, identity)
        if lookup in seen:
            findings.append(_finding('DUPLICATE_IDENTITY', document, 'authoritative tuple repeats'))
        else:
            seen[lookup] = document
        mapping = RECORD_MAPPINGS.get(record_type)
        for fields in mapping.uniqueness if mapping is not None else ():
            if record_type == 'follow_up' and _field(document, 'status') not in {
                'open',
                'pending',
                'blocked',
            }:
                continue
            unique_identity = tuple(_field(document, field) for field in fields)
            if all(value is not None and value != '' for value in unique_identity):
                unique_lookup = (record_type, unique_identity)
                if unique_lookup in unique_tuples:
                    findings.append(
                        _finding(
                            'DUPLICATE_UNIQUE_TUPLE',
                            document,
                            f'unique fields {fields!r} repeat',
                        )
                    )
                else:
                    unique_tuples[unique_lookup] = document
        if record_type == 'idempotency':
            message_turn = (
                str(_field(document, 'actor_id') or ''),
                str(_field(document, 'route') or ''),
                str(_field(document, 'claim_id') or ''),
                str(_field(document, 'message_id') or ''),
            )
            if all(message_turn):
                if message_turn in message_turns:
                    findings.append(
                        _finding(
                            'DUPLICATE_MESSAGE_TURN_LOOKUP',
                            document,
                            'message-turn lookup tuple repeats',
                        )
                    )
                else:
                    message_turns[message_turn] = document
    return findings


def _realtime_findings(documents: Sequence[Mapping[str, Any]]) -> list[RehearsalFinding]:
    events = [doc for doc in documents if doc.get('record_type') == 'realtime_event']
    raw_sequences = [_field(event, 'sequence') for event in events]
    if not raw_sequences:
        return []
    if any(
        isinstance(sequence, bool) or not isinstance(sequence, int) for sequence in raw_sequences
    ):
        return [_finding('INVALID_REALTIME_SEQUENCE', events[0], 'sequence must be an integer')]
    sequences = sorted(raw_sequences)
    expected = list(range(1, sequences[-1] + 1))
    if sequences != expected:
        return [_finding('REALTIME_SEQUENCE_GAP', events[0], 'global sequence is not contiguous')]
    return []


@dataclass(frozen=True)
class _AtomicOperation:
    family: str
    scope_ref: str
    documents: tuple[Mapping[str, Any], ...]


_CLAIM_CHILD_TYPES = frozenset(
    {
        'asset',
        'claim_asset_snapshot',
        'motor_other_driver',
        'contents_item_evidence_association',
        'evidence',
        'evidence_claim_link',
        'external_task',
        'external_task_request',
        'external_task_result',
        'external_task_evidence_link',
        'assessor_routing_operation',
        'policy',
        'identity_document',
        'payment_destination',
        'claim_creation_operation',
    }
)
_AGENT_TURN_TYPES = frozenset(
    {
        'message',
        'agent_decision',
        'handoff',
        'evidence',
        'branch_evaluation',
        'runtime_trace',
        'turn_plan',
        'agent_proposal',
        'execution_plan',
        'action_envelope',
        'tool_result',
        'turn_result',
        'runtime_work_item',
    }
)
_STAFF_MUTATION_TYPES = frozenset(
    {
        'staff_action',
        'collaboration_request',
        'claim_coworker',
        'customer_update',
        'signal_decision',
        'handoff',
        'staff_agent_execution',
    }
)


def _records_of_type(
    documents: Sequence[Mapping[str, Any]], record_types: frozenset[str]
) -> list[Mapping[str, Any]]:
    return [document for document in documents if document.get('record_type') in record_types]


def _reconstruct_claim_operations(
    claim: Mapping[str, Any], scoped: Sequence[Mapping[str, Any]]
) -> tuple[list[_AtomicOperation], list[RehearsalFinding]]:
    claim_id = _required_text(claim, 'claim_id')
    operations: list[_AtomicOperation] = []
    findings: list[RehearsalFinding] = []
    sessions = _records_of_type(scoped, frozenset({'session'}))
    realtime = _records_of_type(scoped, frozenset({'realtime_sequence', 'realtime_event'}))
    active_session_id = _field(claim, 'active_session_id')
    if isinstance(active_session_id, str) and active_session_id:
        active = [
            record for record in sessions if _field(record, 'session_id') == active_session_id
        ]
        if len(active) != 1:
            findings.append(
                _finding(
                    'AMBIGUOUS_ATOMIC_MUTATION',
                    claim,
                    'Claim creation cannot resolve exactly one active Session',
                )
            )
        else:
            operations.append(
                _AtomicOperation(
                    'claim_creation', f'claim:{claim_id}', tuple([claim, active[0], *realtime])
                )
            )
    checkpoint = _records_of_type(scoped, frozenset({'follow_up', 'branch_evaluation'}))
    if checkpoint:
        supporting = _records_of_type(
            scoped, frozenset({'session', 'idempotency', 'realtime_sequence', 'realtime_event'})
        )
        operations.append(
            _AtomicOperation(
                'session_checkpoint',
                f'claim:{claim_id}',
                tuple([claim, *supporting, *checkpoint]),
            )
        )
    children = _records_of_type(scoped, _CLAIM_CHILD_TYPES)
    if children:
        supporting = _records_of_type(
            scoped,
            frozenset(
                {'session', 'idempotency', 'audit_event', 'realtime_sequence', 'realtime_event'}
            ),
        )
        operations.append(
            _AtomicOperation(
                'claim_child', f'claim:{claim_id}', tuple([claim, *supporting, *children])
            )
        )
    for turn in _records_of_type(scoped, frozenset({'turn_plan'})):
        turn_id = _required_text(turn, 'turn_id')
        turn_records = [
            record
            for record in _records_of_type(scoped, _AGENT_TURN_TYPES)
            if record.get('record_type')
            in {
                'message',
                'agent_decision',
                'handoff',
                'evidence',
                'branch_evaluation',
                'runtime_trace',
            }
            or _field(record, 'turn_id') == turn_id
        ]
        supporting = _records_of_type(
            scoped, frozenset({'session', 'idempotency', 'realtime_sequence', 'realtime_event'})
        )
        operations.append(
            _AtomicOperation(
                'agent_turn', f'turn:{turn_id}', tuple([claim, *supporting, *turn_records])
            )
        )
    staff_records = _records_of_type(scoped, _STAFF_MUTATION_TYPES)
    if staff_records:
        supporting = _records_of_type(
            scoped, frozenset({'idempotency', 'audit_event', 'realtime_sequence', 'realtime_event'})
        )
        operations.append(
            _AtomicOperation(
                'staff_ownership', f'claim:{claim_id}', tuple([claim, *supporting, *staff_records])
            )
        )
    return operations, findings


def _reconstruct_atomic_operations(
    documents: Sequence[Mapping[str, Any]],
) -> tuple[list[_AtomicOperation], list[RehearsalFinding]]:
    operations: list[_AtomicOperation] = []
    findings: list[RehearsalFinding] = []
    claims = [document for document in documents if document.get('record_type') == 'claim']
    for claim in claims:
        claim_id = _required_text(claim, 'claim_id')
        scoped = [
            document
            for document in documents
            if _field(document, 'claim_id') == claim_id
            or document.get('record_type') == 'realtime_sequence'
        ]
        claim_operations, claim_findings = _reconstruct_claim_operations(claim, scoped)
        operations.extend(claim_operations)
        findings.extend(claim_findings)
    for retrieval in _records_of_type(documents, frozenset({'retrieval'})):
        retrieval_id = _required_text(retrieval, 'retrieval_id')
        claim_id = _required_text(retrieval, 'claim_id')
        signals = [
            document
            for document in documents
            if document.get('record_type') == 'review_signal'
            and _field(document, 'claim_id') == claim_id
            and retrieval_id in (_field(document, 'source_refs') or [])
        ]
        operations.append(
            _AtomicOperation(
                'retrieval_bundle', f'retrieval:{retrieval_id}', tuple([retrieval, *signals])
            )
        )
    assigned = {id(document) for operation in operations for document in operation.documents}
    for document in documents:
        record_type = str(document.get('record_type', ''))
        if id(document) in assigned or record_type not in RECORD_MAPPINGS:
            continue
        mapping = RECORD_MAPPINGS[record_type]
        if mapping.mutation_family == 'claim_child' and isinstance(
            _field(document, 'customer_id'), str
        ):
            operations.append(
                _AtomicOperation(
                    'claim_child',
                    f'source:{_source_ref(document)}',
                    (document,),
                )
            )
            assigned.add(id(document))
        elif mapping.mutation_family == 'staff_ownership' and record_type in {
            'staff_presence',
            'staff_agent_session',
            'staff_agent_message',
        }:
            operations.append(
                _AtomicOperation(
                    'staff_ownership',
                    f'source:{_source_ref(document)}',
                    (document,),
                )
            )
            assigned.add(id(document))
        else:
            findings.append(
                _finding(
                    'UNRECONSTRUCTED_ATOMIC_MUTATION',
                    document,
                    'record cannot be assigned to one approved atomic boundary',
                )
            )
    ambiguous_types = {
        'idempotency',
        'audit_event',
        'realtime_sequence',
        'realtime_event',
        'handoff',
        'evidence',
        'branch_evaluation',
    }
    for document in documents:
        if document.get('record_type') not in ambiguous_types:
            continue
        memberships = [
            operation
            for operation in operations
            if any(candidate is document for candidate in operation.documents)
        ]
        if len(memberships) > 1:
            findings.append(
                _finding(
                    'AMBIGUOUS_ATOMIC_MUTATION',
                    document,
                    'shared record maps to multiple reconstructed operations',
                )
            )
    return operations, findings


def _operation_items(
    operation: _AtomicOperation, items: Sequence[PlannedItem]
) -> list[PlannedItem]:
    source_refs = {_source_ref(document) for document in operation.documents}
    selected = [item for item in items if item.source_ref in source_refs]
    idempotency_scopes = {
        (_field(document, 'claim_id'), _field(document, 'actor_id'))
        for document in operation.documents
        if document.get('record_type') == 'idempotency'
    }
    selected.extend(
        item
        for item in items
        if item.item_kind == 'claim_actor_generation'
        and (item.payload.get('claim_id'), item.payload.get('actor_id')) in idempotency_scopes
    )
    return selected


def _atomic_mutation_reports(
    documents: Sequence[Mapping[str, Any]], items: Sequence[PlannedItem]
) -> tuple[tuple[AtomicMutationReport, ...], list[RehearsalFinding]]:
    operations, findings = _reconstruct_atomic_operations(documents)
    documents_by_ref = {_source_ref(document): document for document in documents}
    reports: list[AtomicMutationReport] = []
    for operation in sorted(operations, key=lambda value: (value.family, value.scope_ref)):
        source_refs = {_source_ref(document) for document in operation.documents}
        mutation_items = _operation_items(operation, items)
        action_count = len(mutation_items)
        serialized_bytes = sum(len(_json_bytes(asdict(item))) for item in mutation_items)
        within_limits = (
            action_count <= TRANSACTION_ACTION_LIMIT
            and serialized_bytes <= TRANSACTION_BUDGET_BYTES
        )
        reports.append(
            AtomicMutationReport(
                operation.family,
                operation.scope_ref,
                action_count,
                serialized_bytes,
                within_limits,
                tuple(sorted(source_refs)),
                tuple(sorted(f'{item.pk}|{item.sk}' for item in mutation_items)),
            )
        )
        if within_limits:
            continue
        source = documents_by_ref[next(iter(source_refs))]
        if action_count > TRANSACTION_ACTION_LIMIT:
            findings.append(
                _finding(
                    'ATOMIC_ACTION_LIMIT',
                    source,
                    f'{operation.family} requires {action_count} actions; limit is 100',
                )
            )
        if serialized_bytes > TRANSACTION_BUDGET_BYTES:
            findings.append(
                _finding(
                    'ATOMIC_BYTE_LIMIT',
                    source,
                    f'{operation.family} requires {serialized_bytes} bytes; limit is 4 MiB',
                )
            )
    return tuple(reports), findings


def _finding(code: str, document: Mapping[str, Any], detail: str) -> RehearsalFinding:
    return RehearsalFinding(
        code, str(document.get('record_type', 'unknown')), _source_ref(document), detail
    )


def transform_snapshot(
    documents: Sequence[Mapping[str, Any]], metadata: SnapshotMetadata
) -> tuple[list[PlannedItem], RehearsalReport]:
    """Transform and validate one consistent MongoDB snapshot.

    Args:
        documents: Documents read from one MongoDB snapshot transaction.
        metadata: Non-secret coordinates for that snapshot.

    Returns:
        Planned local target items and a safe rehearsal report.
    """

    findings: list[RehearsalFinding] = []
    items: list[PlannedItem] = []
    transformed_documents: list[Mapping[str, Any]] = []
    ordered_documents = sorted(
        documents,
        key=lambda document: (
            str(document.get('record_type', 'unknown')),
            _source_ref(document),
        ),
    )
    if not ordered_documents:
        findings.append(
            RehearsalFinding(
                'EMPTY_SNAPSHOT',
                'snapshot',
                'snapshot',
                'source snapshot contains no records',
            )
        )
    if metadata.record_count != len(documents):
        findings.append(
            RehearsalFinding(
                'SNAPSHOT_COUNT_MISMATCH',
                'snapshot',
                'snapshot',
                'snapshot metadata count differs from the read documents',
            )
        )
    source_counts = Counter(str(doc.get('record_type', 'unknown')) for doc in ordered_documents)
    for document in ordered_documents:
        record_type = str(document.get('record_type', 'unknown'))
        if record_type not in IDENTITY_FIELDS:
            findings.append(
                _finding('UNKNOWN_RECORD_TYPE', document, 'record type is not allowlisted')
            )
            continue
        try:
            planned = plan_record(document)
        except (TypeError, ValueError) as error:
            findings.append(_finding('INVALID_IDENTITY', document, str(error)))
            continue
        transformed_documents.append(document)
        for item in planned:
            if len(_json_bytes(asdict(item))) > ITEM_BUDGET_BYTES:
                findings.append(
                    RehearsalFinding(
                        'OVERSIZED_ITEM',
                        record_type,
                        item.source_ref,
                        'target item exceeds 300 KiB',
                    )
                )
            else:
                items.append(item)
    for item in _idempotency_generation_items(ordered_documents):
        if len(_json_bytes(asdict(item))) > ITEM_BUDGET_BYTES:
            findings.append(
                RehearsalFinding(
                    'OVERSIZED_ITEM',
                    item.record_type,
                    item.source_ref,
                    'target item exceeds 300 KiB',
                )
            )
        else:
            items.append(item)
    findings.extend(_relationship_findings(ordered_documents))
    findings.extend(_uniqueness_findings(ordered_documents))
    findings.extend(_realtime_findings(ordered_documents))
    atomic_mutations, atomic_findings = _atomic_mutation_reports(transformed_documents, items)
    findings.extend(atomic_findings)

    target = LocalTarget()
    first = target.apply(items)
    second = target.apply(items)
    if (
        first.get('conflict')
        or second.get('conflict')
        or not target.readback(transformed_documents)
    ):
        findings.append(
            RehearsalFinding('READBACK_CONFLICT', 'target', 'target', 'readback differs')
        )
    snapshot_fingerprint = sha256(_json_bytes(ordered_documents)).hexdigest()
    report = RehearsalReport(
        evidence_level='local_mongodb_rehearsal_only',
        source_head=SOURCE_HEAD,
        inventory_version=INVENTORY_VERSION,
        reconciliation_issues=RECONCILIATION_ISSUES,
        snapshot=metadata,
        snapshot_fingerprint=snapshot_fingerprint,
        source_counts=dict(sorted(source_counts.items())),
        first_pass=dict(sorted(first.items())),
        second_pass=dict(sorted(second.items())),
        target_item_count=target.item_count,
        atomic_mutations=atomic_mutations,
        completion_marker=not findings,
        findings=tuple(findings),
    )
    return items, report


def read_snapshot(
    client: MongoClient[Any], database: str, collection: str
) -> tuple[list[dict[str, Any]], SnapshotMetadata]:
    """Read one MongoDB collection from a consistent snapshot transaction.

    Args:
        client: Configured MongoDB client connected to a replica set.
        database: Source database name.
        collection: Source collection name.

    Returns:
        Snapshot documents and non-secret snapshot coordinates.

    Raises:
        RuntimeError: MongoDB cannot provide one snapshot transaction.
    """

    try:
        with client.start_session() as session:
            session.start_transaction(read_concern=ReadConcern('snapshot'))
            documents = list(client[database][collection].find({}, session=session))
            operation_time = _normalise(session.operation_time)
            session.abort_transaction()
    except (PyMongoError, ValueError, TypeError) as error:
        raise RuntimeError('MongoDB could not provide a consistent source snapshot.') from error
    return documents, SnapshotMetadata(
        database=database,
        collection=collection,
        operation_time=json.dumps(operation_time, sort_keys=True),
        record_count=len(documents),
    )


def _report_json(report: RehearsalReport) -> str:
    return json.dumps(_normalise(asdict(report)), indent=2, sort_keys=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--uri-env', default='NORTHWIND_MONGODB_URI')
    parser.add_argument(
        '--database', default=os.getenv('NORTHWIND_MONGODB_DATABASE', 'northwind_fnol')
    )
    parser.add_argument(
        '--collection', default=os.getenv('NORTHWIND_MONGODB_COLLECTION', 'northwind_records')
    )
    args = parser.parse_args(argv)
    uri = os.getenv(args.uri_env)
    if not uri:
        parser.error(f'{args.uri_env} must name a configured MongoDB connection URI')
    client: MongoClient[Any] = MongoClient(uri, serverSelectionTimeoutMS=5000)
    try:
        documents, metadata = read_snapshot(client, args.database, args.collection)
        _, report = transform_snapshot(documents, metadata)
        print(_report_json(report))
        return 0 if report.completion_marker else 2
    finally:
        client.close()


if __name__ == '__main__':
    raise SystemExit(main())
