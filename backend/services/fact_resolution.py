"""Source-preserving resolution of new claimant assertions against Claim facts."""

import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    AssertionRelation,
    ContentsItem,
    ContentsItemAssertion,
    FactAssertion,
    FactPrecision,
    FactResolutionState,
    FormSource,
    FormStatus,
    MessageRecord,
    NeededFor,
    ProposedContentsItem,
    ProposedFormChange,
    StructuredFormField,
)
from backend.repositories.protocols import PersistenceRepository

_CORRECTION_PATTERN = re.compile(
    r'\b(?:actually|correction|correct that|i mean|rather than|instead(?: of)?|'
    r'not\s+.+\s+but|sorry[, ]+(?:it|the))\b',
    re.IGNORECASE,
)
_APPROXIMATE_PATTERN = re.compile(
    r'\b(?:about|around|approximately|roughly|maybe|perhaps|i think|ish)\b',
    re.IGNORECASE,
)
_RANGE_PATTERN = re.compile(r'\b(?:between|from)\b.+\b(?:and|to)\b', re.IGNORECASE)


def infer_precision(field_code: str, value: Any, reported_text: str | None) -> FactPrecision:
    """Preserve the precision that a claimant actually supplied."""

    if field_code != 'incident.occurred_at':
        return FactPrecision.EXACT
    if isinstance(value, dict):
        raw = value.get('precision')
        if isinstance(raw, str):
            try:
                return FactPrecision(raw)
            except ValueError:
                pass
    text = reported_text or (value if isinstance(value, str) else '')
    if not text.strip():
        return FactPrecision.UNKNOWN
    if _RANGE_PATTERN.search(text):
        return FactPrecision.RANGE
    if _APPROXIMATE_PATTERN.search(text):
        return FactPrecision.APPROXIMATE
    return FactPrecision.EXACT


def _normalise(value: Any) -> str:
    if isinstance(value, str):
        return ' '.join(value.split()).casefold()
    return json.dumps(value, sort_keys=True, separators=(',', ':'), default=str).casefold()


def _legacy_assertion(field_code: str, field: StructuredFormField) -> FactAssertion:
    return FactAssertion(
        assertion_id=f'ast_legacy_{field_code.replace(".", "_")}',
        normalized_value=field.value,
        source_refs=list(field.source_refs),
        status=field.status,
        precision=infer_precision(field_code, field.value, None),
        created_at=field.updated_at,
    )


def _relation(
    field_code: str,
    existing: StructuredFormField,
    proposal: ProposedFormChange,
    message_text: str | None,
    explicit_correction: bool,
) -> AssertionRelation:
    if _normalise(existing.value) == _normalise(proposal.value):
        return AssertionRelation.EQUIVALENT
    if existing.status is not FormStatus.CONFIRMED:
        return AssertionRelation.REFINEMENT
    if explicit_correction or (message_text and _CORRECTION_PATTERN.search(message_text)):
        return AssertionRelation.CORRECTION
    existing_precision = (
        infer_precision(field_code, existing.value, None)
        if field_code == 'incident.occurred_at' and not existing.assertions
        else existing.precision
    )
    if (
        existing_precision
        in {
            FactPrecision.APPROXIMATE,
            FactPrecision.RANGE,
            FactPrecision.PARTIAL,
        }
        and proposal.precision is FactPrecision.EXACT
    ):
        return AssertionRelation.REFINEMENT
    return AssertionRelation.MATERIAL_CONFLICT


def resolve_form_change(
    *,
    field_code: str,
    existing: StructuredFormField | None,
    proposal: ProposedFormChange,
    source_ref: str,
    message_text: str | None,
    timestamp: datetime,
    accepted_status: FormStatus,
    updated_by: ActorReference,
    explicit_correction: bool = False,
) -> StructuredFormField:
    """Resolve one proposal while retaining every source-linked assertion."""

    precision = (
        proposal.precision
        if proposal.precision is not FactPrecision.EXACT
        else infer_precision(field_code, proposal.value, proposal.reported_text or message_text)
    )
    relation = (
        AssertionRelation.INITIAL
        if existing is None
        else proposal.relation
        or _relation(
            field_code,
            existing,
            proposal.model_copy(update={'precision': precision}),
            message_text,
            explicit_correction,
        )
    )
    assertion = FactAssertion(
        assertion_id=new_id('ast'),
        reported_text=proposal.reported_text or message_text,
        normalized_value=proposal.value,
        source_refs=[source_ref],
        relation=relation,
        status=accepted_status,
        precision=precision,
        reason_code=(
            'MATERIAL_VALUE_CONFLICT' if relation is AssertionRelation.MATERIAL_CONFLICT else None
        ),
        created_at=timestamp,
    )
    history = [] if existing is None else list(existing.assertions)
    if existing is not None and not history:
        history.append(_legacy_assertion(field_code, existing))

    if relation is AssertionRelation.EQUIVALENT and existing is not None:
        if (
            existing.resolution_state is FactResolutionState.CLARIFICATION_REQUIRED
            and accepted_status is FormStatus.CONFIRMED
        ):
            current_id = existing.current_assertion_id or history[-1].assertion_id
            resolved_history = [
                item.model_copy(
                    update={
                        'status': (
                            FormStatus.CONFIRMED
                            if item.assertion_id == current_id
                            else FormStatus.SUPERSEDED
                            if item.status is FormStatus.DISPUTED
                            else item.status
                        )
                    }
                )
                for item in history
            ]
            return existing.model_copy(
                update={
                    'source_refs': list(dict.fromkeys([*existing.source_refs, source_ref])),
                    'status': FormStatus.CONFIRMED,
                    'resolution_state': FactResolutionState.RESOLVED,
                    'assertions': [*resolved_history, assertion],
                    'current_assertion_id': current_id,
                    'updated_at': timestamp,
                    'updated_by': updated_by,
                }
            )
        return existing.model_copy(
            update={
                'source_refs': list(dict.fromkeys([*existing.source_refs, source_ref])),
                'assertions': [*history, assertion],
                'current_assertion_id': existing.current_assertion_id or history[-1].assertion_id,
                'updated_at': timestamp,
                'updated_by': updated_by,
            }
        )

    if relation is AssertionRelation.MATERIAL_CONFLICT and existing is not None:
        return existing.model_copy(
            update={
                'source_refs': list(dict.fromkeys([*existing.source_refs, source_ref])),
                'status': FormStatus.DISPUTED,
                'resolution_state': FactResolutionState.CLARIFICATION_REQUIRED,
                'assertions': [
                    *history,
                    assertion.model_copy(update={'status': FormStatus.DISPUTED}),
                ],
                'current_assertion_id': existing.current_assertion_id or history[-1].assertion_id,
                'updated_at': timestamp,
                'updated_by': updated_by,
            }
        )

    if existing is not None:
        current_id = existing.current_assertion_id or history[-1].assertion_id
        history = [
            item.model_copy(update={'status': FormStatus.SUPERSEDED})
            if item.assertion_id == current_id or item.status is FormStatus.DISPUTED
            else item
            for item in history
        ]
    resolution = (
        FactResolutionState.RESOLVED
        if accepted_status is FormStatus.CONFIRMED
        else FactResolutionState.NEEDS_CONFIRMATION
    )
    return StructuredFormField(
        value=proposal.value,
        source=proposal.source,
        source_refs=[source_ref],
        status=accepted_status,
        needed_for=proposal.needed_for,
        confidence=proposal.confidence,
        resolution_state=resolution,
        precision=precision,
        current_assertion_id=assertion.assertion_id,
        assertions=[*history, assertion],
        updated_at=timestamp,
        updated_by=updated_by,
    )


def confirm_form_field(
    field: StructuredFormField,
    *,
    timestamp: datetime,
    updated_by: ActorReference,
) -> StructuredFormField:
    """Confirm the current assertion without dropping its history."""

    current_id = field.current_assertion_id
    assertions = [
        item.model_copy(update={'status': FormStatus.CONFIRMED})
        if current_id is not None and item.assertion_id == current_id
        else item
        for item in field.assertions
    ]
    return field.model_copy(
        update={
            'status': FormStatus.CONFIRMED,
            'resolution_state': FactResolutionState.RESOLVED,
            'confidence': 1.0,
            'assertions': assertions,
            'updated_at': timestamp,
            'updated_by': updated_by,
        }
    )


def _contents_values(item: ContentsItem | ProposedContentsItem) -> tuple[object, ...]:
    return (
        _normalise(item.description),
        _normalise(item.category),
        item.quantity,
        item.loss_type,
        item.ownership,
        item.estimated_value,
    )


def _legacy_contents_assertion(item: ContentsItem) -> ContentsItemAssertion:
    return ContentsItemAssertion(
        assertion_id=f'ast_legacy_{item.item_id}',
        description=item.description,
        category=item.category,
        quantity=item.quantity,
        loss_type=item.loss_type,
        ownership=item.ownership,
        estimated_value=item.estimated_value,
        source_refs=list(item.source_refs),
        status=item.status,
        created_at=item.updated_at,
    )


def resolve_contents_item_change(
    *,
    existing: ContentsItem | None,
    proposal: ProposedContentsItem,
    item_id: str,
    source_ref: str,
    message_text: str | None,
    timestamp: datetime,
    accepted_status: FormStatus,
    updated_by: ActorReference,
) -> ContentsItem:
    """Resolve a whole contents-item assertion without losing the earlier version."""

    if existing is None:
        relation = AssertionRelation.INITIAL
    elif _contents_values(existing) == _contents_values(proposal):
        relation = AssertionRelation.EQUIVALENT
    elif existing.status is not FormStatus.CONFIRMED:
        relation = AssertionRelation.REFINEMENT
    elif message_text and _CORRECTION_PATTERN.search(message_text):
        relation = AssertionRelation.CORRECTION
    elif (
        existing.estimated_value is None
        and proposal.estimated_value is not None
        and _contents_values(existing)[:-1] == _contents_values(proposal)[:-1]
    ):
        relation = AssertionRelation.REFINEMENT
    else:
        relation = AssertionRelation.MATERIAL_CONFLICT

    assertion = ContentsItemAssertion(
        assertion_id=new_id('ast'),
        description=proposal.description,
        category=proposal.category,
        quantity=proposal.quantity,
        loss_type=proposal.loss_type,
        ownership=proposal.ownership,
        estimated_value=proposal.estimated_value,
        reported_text=proposal.reported_text or message_text,
        source_refs=[source_ref],
        relation=relation,
        status=accepted_status,
        created_at=timestamp,
    )
    if existing is None:
        return ContentsItem(
            item_id=item_id,
            description=proposal.description,
            category=proposal.category,
            quantity=proposal.quantity,
            loss_type=proposal.loss_type,
            ownership=proposal.ownership,
            estimated_value=proposal.estimated_value,
            source=FormSource.CLAIMANT,
            source_refs=[source_ref],
            status=accepted_status,
            needed_for=NeededFor.CURRENT_ACTION,
            confidence=proposal.confidence,
            resolution_state=FactResolutionState.NEEDS_CONFIRMATION,
            current_assertion_id=assertion.assertion_id,
            assertions=[assertion],
            updated_at=timestamp,
            updated_by=updated_by,
        )

    history = list(existing.assertions) or [_legacy_contents_assertion(existing)]
    if relation is AssertionRelation.EQUIVALENT:
        return existing.model_copy(
            update={
                'source_refs': list(dict.fromkeys([*existing.source_refs, source_ref])),
                'assertions': [*history, assertion],
                'current_assertion_id': existing.current_assertion_id or history[-1].assertion_id,
                'updated_at': timestamp,
                'updated_by': updated_by,
            }
        )
    if relation is AssertionRelation.MATERIAL_CONFLICT:
        return existing.model_copy(
            update={
                'source_refs': list(dict.fromkeys([*existing.source_refs, source_ref])),
                'status': FormStatus.DISPUTED,
                'resolution_state': FactResolutionState.CLARIFICATION_REQUIRED,
                'assertions': [
                    *history,
                    assertion.model_copy(update={'status': FormStatus.DISPUTED}),
                ],
                'current_assertion_id': existing.current_assertion_id or history[-1].assertion_id,
                'updated_at': timestamp,
                'updated_by': updated_by,
            }
        )

    current_id = existing.current_assertion_id or history[-1].assertion_id
    history = [
        item.model_copy(update={'status': FormStatus.SUPERSEDED})
        if item.assertion_id == current_id or item.status is FormStatus.DISPUTED
        else item
        for item in history
    ]
    return existing.model_copy(
        update={
            'description': proposal.description,
            'category': proposal.category,
            'quantity': proposal.quantity,
            'loss_type': proposal.loss_type,
            'ownership': proposal.ownership,
            'estimated_value': proposal.estimated_value,
            'source': FormSource.CLAIMANT,
            'source_refs': [source_ref],
            'status': accepted_status,
            'needed_for': NeededFor.CURRENT_ACTION,
            'confidence': proposal.confidence,
            'resolution_state': FactResolutionState.NEEDS_CONFIRMATION,
            'current_assertion_id': assertion.assertion_id,
            'assertions': [*history, assertion],
            'updated_at': timestamp,
            'updated_by': updated_by,
        }
    )


def confirm_contents_item(
    item: ContentsItem,
    *,
    timestamp: datetime,
    updated_by: ActorReference,
) -> ContentsItem:
    """Confirm the current contents assertion and retain superseded history."""

    assertions = [
        assertion.model_copy(update={'status': FormStatus.CONFIRMED})
        if assertion.assertion_id == item.current_assertion_id
        else assertion
        for assertion in item.assertions
    ]
    return item.model_copy(
        update={
            'status': FormStatus.CONFIRMED,
            'resolution_state': FactResolutionState.RESOLVED,
            'confidence': 1.0,
            'assertions': assertions,
            'updated_at': timestamp,
            'updated_by': updated_by,
        }
    )


def provenance_messages_for_fields(
    repository: PersistenceRepository,
    *,
    claim_id: str,
    customer_id: str,
    fields: Iterable[StructuredFormField],
) -> list[MessageRecord]:
    """Load full messages only when unresolved fact semantics require them."""

    wanted = list(
        dict.fromkeys(
            ref
            for field in fields
            if field.resolution_state is FactResolutionState.CLARIFICATION_REQUIRED
            for ref in field.source_refs
            if ref.startswith('msg_')
        )
    )
    if not wanted:
        return []
    messages: dict[str, MessageRecord] = {}
    for session in repository.list_sessions_for_claim(claim_id, customer_id):
        for message in repository.list_messages(claim_id, session.session_id, customer_id):
            if message.message_id in wanted:
                messages[message.message_id] = message
    return [messages[message_id] for message_id in wanted if message_id in messages]
