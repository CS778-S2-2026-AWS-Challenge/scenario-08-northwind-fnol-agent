import json
import re
from collections.abc import Iterable
from datetime import datetime
from typing import Any

from backend.domain.ids import new_id
from backend.domain.models import (
    ActorReference,
    AssertionRelation,
    FactAssertion,
    FactPrecision,
    FactResolutionState,
    FormStatus,
    MessageRecord,
    ProposedFormChange,
    StructuredFormField,
)
from backend.repositories.protocols import PersistenceRepository

_CORRECTION_PATTERN = re.compile(
    r'\b(?:actually|correction|correct that|i mean|sorry[, ]+it|rather than|'
    r'not .+[,;] (?:it|the))\b',
    re.IGNORECASE,
)
_APPROXIMATE_PATTERN = re.compile(
    r'\b(?:about|around|approximately|roughly|maybe|perhaps|i think|ish)\b',
    re.IGNORECASE,
)
_RANGE_PATTERN = re.compile(r'\b(?:between|from)\b.+\b(?:and|to)\b', re.IGNORECASE)


def infer_precision(field_code: str, value: Any, reported_text: str | None) -> FactPrecision:
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


def _legacy_assertion(
    field_code: str,
    field: StructuredFormField,
) -> FactAssertion:
    source = field.source_refs[0] if field.source_refs else f'field:{field_code}:legacy'
    return FactAssertion(
        assertion_id=f'ast_legacy_{field_code.replace(".", "_")}',
        normalized_value=field.value,
        source_refs=list(field.source_refs) or [source],
        status=field.status,
        precision=(
            infer_precision(field_code, field.value, None)
            if field_code == 'incident.occurred_at'
            else field.precision
        ),
        created_at=field.updated_at,
    )


def _relation(
    field_code: str,
    existing: StructuredFormField,
    proposal: ProposedFormChange,
    message_text: str | None,
) -> AssertionRelation:
    if _normalise(existing.value) == _normalise(proposal.value):
        return AssertionRelation.EQUIVALENT
    if existing.status is not FormStatus.CONFIRMED:
        return AssertionRelation.REFINEMENT
    if message_text and _CORRECTION_PATTERN.search(message_text):
        return AssertionRelation.CORRECTION
    if (
        infer_precision(field_code, existing.value, None)
        if field_code == 'incident.occurred_at' and not existing.assertions
        else existing.precision
    ) in {
        FactPrecision.APPROXIMATE,
        FactPrecision.RANGE,
        FactPrecision.PARTIAL,
    } and proposal.precision is FactPrecision.EXACT:
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
) -> StructuredFormField:
    """Resolve one proposal without deleting an earlier claimant assertion."""

    precision = (
        proposal.precision
        if proposal.precision is not FactPrecision.EXACT
        else infer_precision(field_code, proposal.value, message_text)
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
        )
    )
    assertion_status = accepted_status
    assertion = FactAssertion(
        assertion_id=new_id('ast'),
        normalized_value=proposal.value,
        source_refs=[source_ref],
        relation=relation,
        status=assertion_status,
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

    if existing is not None and relation in {
        AssertionRelation.CORRECTION,
        AssertionRelation.REFINEMENT,
    }:
        history = [
            item.model_copy(update={'status': FormStatus.SUPERSEDED})
            if item.assertion_id == (existing.current_assertion_id or history[-1].assertion_id)
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
    assertions = list(field.assertions)
    if assertions:
        current_id = field.current_assertion_id or assertions[-1].assertion_id
        assertions = [
            item.model_copy(update={'status': FormStatus.CONFIRMED})
            if item.assertion_id == current_id
            else item
            for item in assertions
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


def provenance_messages_for_fields(
    repository: PersistenceRepository,
    *,
    claim_id: str,
    customer_id: str,
    fields: Iterable[StructuredFormField],
) -> list[MessageRecord]:
    """Retrieve full messages only for fields whose meaning still needs resolution."""

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
