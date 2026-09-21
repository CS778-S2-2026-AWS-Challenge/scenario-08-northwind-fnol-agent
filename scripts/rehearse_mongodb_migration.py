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

INVENTORY_VERSION = 'aws-migration-preparation@57100bcd'
SOURCE_HEAD = '57100bcdff6b5184be6990cfd1aefaf729bdabe0'
RECONCILIATION_ISSUES = ('#984', '#985', '#986', '#987', '#786')
ITEM_BUDGET_BYTES = 300 * 1024
REVERSE_TIME_MAX = 99_999_999_999_999_999_999

IDENTITY_FIELDS: dict[str, tuple[str, ...]] = {
    'claim': ('claim_id',),
    'session': ('session_id',),
    'message': ('message_id',),
    'conversation_summary': ('summary_id',),
    'follow_up': ('follow_up_id',),
    'agent_decision': ('decision_id',),
    'branch_evaluation': ('evaluation_id',),
    'runtime_trace': ('trace_id',),
    'turn_plan': ('turn_id',),
    'agent_proposal': ('proposal_id',),
    'execution_plan': ('execution_plan_id',),
    'action_envelope': ('envelope_id',),
    'tool_result': ('result_id',),
    'turn_result': ('result_id',),
    'runtime_work_item': ('work_item_id',),
    'asset': ('asset_id',),
    'claim_asset_snapshot': ('snapshot_id',),
    'motor_other_driver': ('participant_id',),
    'contents_item_evidence_association': ('association_id',),
    'evidence': ('evidence_id',),
    'evidence_claim_link': ('link_id',),
    'external_task': ('task_id',),
    'external_task_request': ('request_id',),
    'external_task_result': ('result_id',),
    'external_task_evidence_link': ('claim_id', 'evidence_id'),
    'assessor_routing_operation': ('operation_id',),
    'handoff': ('handoff_id',),
    'retrieval': ('retrieval_id',),
    'review_signal': ('signal_id',),
    'signal_decision': ('signal_decision_id',),
    'staff_action': ('action_id',),
    'customer_update': ('update_id',),
    'collaboration_request': ('request_id',),
    'claim_coworker': ('coworker_id',),
    'staff_presence': ('staff_id',),
    'staff_agent_session': ('session_id',),
    'staff_agent_message': ('message_id',),
    'staff_agent_execution': ('execution_id',),
    'audit_event': ('event_id',),
    'realtime_sequence': (),
    'realtime_event': ('event_id',),
    'idempotency': ('actor_id', 'route', 'key'),
    'policy': ('policy_id',),
    'identity_document': ('identity_id',),
    'payment_destination': ('payment_destination_id',),
}

ADAPTER_ONLY_FIELDS = frozenset({'_id', 'staff_search', 'realtime_order'})
CLAIM_SCOPED_EXCEPTIONS = frozenset({'claim', 'audit_event', 'realtime_event', 'idempotency'})
ORDER_FIELDS: dict[str, tuple[str, ...]] = {
    'session': ('started_at',),
    'message': ('created_at',),
    'conversation_summary': ('created_at',),
    'follow_up': ('created_at',),
    'agent_decision': ('created_at',),
    'branch_evaluation': ('created_at',),
    'runtime_trace': ('created_at',),
    'turn_plan': ('created_at',),
    'agent_proposal': ('created_at',),
    'execution_plan': ('created_at',),
    'action_envelope': ('created_at',),
    'tool_result': ('created_at',),
    'turn_result': ('created_at',),
    'runtime_work_item': ('updated_at', 'created_at'),
    'claim_asset_snapshot': ('captured_at',),
    'contents_item_evidence_association': ('created_at',),
    'evidence': ('updated_at', 'created_at'),
    'external_task': ('created_at',),
    'external_task_request': ('prepared_at',),
    'external_task_result': ('received_at',),
    'external_task_evidence_link': ('linked_at',),
    'assessor_routing_operation': ('created_at',),
    'handoff': ('created_at',),
    'retrieval': ('retrieved_at', 'created_at'),
    'review_signal': ('created_at',),
    'signal_decision': ('created_at',),
    'staff_action': ('created_at',),
    'customer_update': ('created_at',),
    'collaboration_request': ('created_at',),
    'claim_coworker': ('granted_at', 'created_at'),
    'staff_agent_execution': ('created_at',),
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

    def readback(self, items: Sequence[PlannedItem]) -> bool:
        return all(self._items.get((item.pk, item.sk)) == item for item in items)


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
        form = payload.pop('form', {})
        contents = payload.pop('contents_items', [])
        consents = payload.pop('external_service_consents', [])
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
        history = payload.pop('material_history', [])
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
    references: list[tuple[str, str, str]] = []
    claim_id = _field(document, 'claim_id')
    customer_id = _field(document, 'customer_id')
    if record_type == 'claim' and isinstance(customer_id, str):
        references.append((canonical.pk, 'OWNER', 'claim_owner'))
        updated_at = _reverse_time(_field(document, 'updated_at'))
        references.append(
            (
                f'ACCESS#CUSTOMER_CLAIMS#{customer_id}',
                f'UPDATED#{updated_at}#{claim_id}',
                'customer_claim',
            )
        )
    elif isinstance(claim_id, str) and record_type not in CLAIM_SCOPED_EXCEPTIONS:
        order_field, order_value = _order_coordinate(document, record_type)
        references.append(
            (
                f'ACCESS#CLAIM#{claim_id}#{record_type}',
                f'{order_field.upper()}#{order_value}#{canonical.pk}',
                'claim_order',
            )
        )
    if record_type == 'evidence_claim_link':
        references.append(
            (
                'UNIQUE#EVIDENCE_CLAIM_LINK#'
                + _digest(
                    str(_field(document, 'target_claim_id')), str(_field(document, 'evidence_id'))
                ),
                'META',
                'tuple_unique',
            )
        )
    if record_type == 'idempotency':
        actor = str(_field(document, 'actor_id'))
        route = str(_field(document, 'route'))
        key = str(_field(document, 'key'))
        references.extend(
            [
                (
                    f'ACCESS#CLAIM_IDEMPOTENCY#{_digest(str(claim_id), actor)}',
                    f'RECORD#{_digest(route, key)}',
                    'claim_actor_idempotency',
                ),
            ]
        )
        message_id = _field(document, 'message_id')
        if isinstance(message_id, str) and message_id:
            references.append(
                (
                    'LOOKUP#MESSAGE_TURN_IDEMPOTENCY#'
                    + _digest(actor, route, str(claim_id), message_id),
                    'META',
                    'message_turn_lookup',
                )
            )
    items: list[PlannedItem] = []
    for pk, sk, kind in references:
        payload: dict[str, Any] = {
            'canonical_pk': canonical.pk,
            'canonical_sk': canonical.sk,
        }
        if kind == 'claim_owner':
            payload = {'owner_customer_id': customer_id}
        elif kind == 'customer_claim':
            payload.update({'customer_id': customer_id, 'claim_id': claim_id})
        elif kind == 'claim_order':
            payload.update({'claim_id': claim_id, 'record_type': record_type})
        elif kind == 'claim_actor_idempotency':
            payload.update(
                {
                    'claim_id': claim_id,
                    'actor_id': _field(document, 'actor_id'),
                    'route': _field(document, 'route'),
                    'key': _field(document, 'key'),
                }
            )
        elif kind == 'message_turn_lookup':
            payload.update(
                {
                    'claim_id': claim_id,
                    'actor_id': _field(document, 'actor_id'),
                    'route': _field(document, 'route'),
                    'message_id': _field(document, 'message_id'),
                }
            )
        items.append(
            _planned_item(
                pk,
                sk,
                record_type,
                kind,
                document,
                payload,
            )
        )
    return items


def _order_coordinate(document: Mapping[str, Any], record_type: str) -> tuple[str, str]:
    for field in ORDER_FIELDS.get(record_type, ('created_at', 'updated_at')):
        value = _field(document, field)
        if value is not None:
            return field, _ascending_time(value)
    return 'identity', _source_ref(document)


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


def _relationship_findings(documents: Sequence[Mapping[str, Any]]) -> list[RehearsalFinding]:
    claims = {
        str(_field(doc, 'claim_id')): doc for doc in documents if doc.get('record_type') == 'claim'
    }
    sessions = {
        str(_field(doc, 'session_id')): doc
        for doc in documents
        if doc.get('record_type') == 'session'
    }
    evidence = {
        str(_field(doc, 'evidence_id')): doc
        for doc in documents
        if doc.get('record_type') == 'evidence'
    }
    tasks = {
        str(_field(doc, 'task_id')): doc
        for doc in documents
        if doc.get('record_type') == 'external_task'
    }
    turns = {
        str(_field(doc, 'turn_id')): doc
        for doc in documents
        if doc.get('record_type') == 'turn_plan'
    }
    retrievals = {
        str(_field(doc, 'retrieval_id')): doc
        for doc in documents
        if doc.get('record_type') == 'retrieval'
    }
    staff_sessions = {
        str(_field(doc, 'session_id')): doc
        for doc in documents
        if doc.get('record_type') == 'staff_agent_session'
    }
    findings: list[RehearsalFinding] = []
    for document in documents:
        record_type = str(document.get('record_type', 'unknown'))
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
        session_id = _field(document, 'session_id')
        if isinstance(session_id, str) and record_type not in {
            'session',
            'staff_agent_session',
            'staff_agent_message',
            'staff_agent_execution',
        }:
            session = sessions.get(session_id)
            if session is None or _field(session, 'claim_id') != claim_id:
                findings.append(
                    _finding('DANGLING_SESSION', document, 'Claim Session is absent or mislinked')
                )
        task_id = _field(document, 'task_id')
        if isinstance(task_id, str) and record_type != 'external_task':
            task = tasks.get(task_id)
            if task is None or _field(task, 'claim_id') != claim_id:
                findings.append(
                    _finding('DANGLING_TASK', document, 'external task is absent or mislinked')
                )
        if record_type in {
            'agent_proposal',
            'execution_plan',
            'action_envelope',
            'tool_result',
            'turn_result',
            'runtime_work_item',
        }:
            turn = turns.get(str(_field(document, 'turn_id')))
            if turn is None or _field(turn, 'claim_id') != claim_id:
                findings.append(
                    _finding('DANGLING_TURN', document, 'Runtime turn is absent or mislinked')
                )
        if record_type == 'review_signal':
            retrieval = retrievals.get(str(_field(document, 'retrieval_id')))
            if retrieval is None or _field(retrieval, 'claim_id') != claim_id:
                findings.append(
                    _finding('DANGLING_RETRIEVAL', document, 'Retrieval is absent or mislinked')
                )
        if record_type in {'staff_agent_message', 'staff_agent_execution'}:
            staff_session = staff_sessions.get(str(session_id))
            if staff_session is None or _field(staff_session, 'staff_id') != _field(
                document, 'staff_id'
            ):
                findings.append(
                    _finding(
                        'DANGLING_STAFF_SESSION',
                        document,
                        'Staff Agent Session is absent or mislinked',
                    )
                )
        if record_type in {'external_task_evidence_link', 'evidence_claim_link'}:
            held = evidence.get(str(_field(document, 'evidence_id')))
            expected_claim = (
                _field(document, 'target_claim_id')
                if record_type == 'evidence_claim_link'
                else claim_id
            )
            if held is None or (
                record_type == 'external_task_evidence_link'
                and _field(held, 'claim_id') != expected_claim
            ):
                findings.append(
                    _finding('DANGLING_EVIDENCE', document, 'Evidence is absent or mislinked')
                )
            if record_type == 'evidence_claim_link' and str(expected_claim) not in claims:
                findings.append(
                    _finding('DANGLING_TARGET_CLAIM', document, 'target Claim is absent')
                )
    return findings


def _uniqueness_findings(documents: Sequence[Mapping[str, Any]]) -> list[RehearsalFinding]:
    seen: dict[tuple[str, tuple[Any, ...]], Mapping[str, Any]] = {}
    unique_tuples: dict[tuple[str, tuple[Any, ...]], Mapping[str, Any]] = {}
    message_turns: dict[tuple[str, str, str, str], Mapping[str, Any]] = {}
    findings: list[RehearsalFinding] = []
    unique_fields: dict[str, tuple[str, ...]] = {
        'evidence_claim_link': ('target_claim_id', 'evidence_id'),
        'external_task_evidence_link': ('claim_id', 'evidence_id'),
        'contents_item_evidence_association': ('claim_id', 'item_id', 'evidence_id'),
        'external_task_result': ('claim_id', 'task_id'),
        'external_task_request': ('task_id',),
        'motor_other_driver': ('claim_id',),
        'message': ('claim_id', 'client_message_id'),
        'staff_agent_message': ('staff_id', 'session_id', 'client_message_id'),
        'realtime_event': ('sequence',),
    }
    for document in documents:
        record_type = str(document.get('record_type', 'unknown'))
        identity = tuple(_field(document, field) for field in IDENTITY_FIELDS.get(record_type, ()))
        lookup = (record_type, identity)
        if lookup in seen:
            findings.append(_finding('DUPLICATE_IDENTITY', document, 'authoritative tuple repeats'))
        else:
            seen[lookup] = document
        fields = unique_fields.get(record_type)
        if fields is not None:
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
        if record_type == 'follow_up' and _field(document, 'status') == 'open':
            for fields in (('claim_id', 'purpose'), ('claim_id', 'source_session_id')):
                unique_identity = tuple(_field(document, field) for field in fields)
                if not all(value is not None and value != '' for value in unique_identity):
                    continue
                unique_lookup = (f'{record_type}:{fields!r}', unique_identity)
                if unique_lookup in unique_tuples:
                    findings.append(
                        _finding(
                            'DUPLICATE_OPEN_FOLLOW_UP',
                            document,
                            f'open FollowUp fields {fields!r} repeat',
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
            canonical_items = _canonical_items(
                document, record_type, _identity(document, record_type)
            )
            canonical = canonical_items[0]
            planned = [*canonical_items, *_reference_items(document, record_type, canonical)]
        except (TypeError, ValueError) as error:
            findings.append(_finding('INVALID_IDENTITY', document, str(error)))
            continue
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

    target = LocalTarget()
    first = target.apply(items)
    second = target.apply(items)
    if first.get('conflict') or second.get('conflict') or not target.readback(items):
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
