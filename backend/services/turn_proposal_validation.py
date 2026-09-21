"""Validate the v8 turn envelope before the claimant reducer applies it."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from backend.domain.agent_v8 import (
    V8Escalation,
    V8FieldChange,
    V8NextQuestion,
    V8ServiceSuggestion,
    V8StateProposal,
    V8TurnProposal,
)
from backend.domain.branch_registry import build_default_registry
from backend.domain.external_service_registry import SERVICE_REGISTRY
from backend.domain.model_gateway import ModelGatewayError, ModelGatewayErrorCode
from backend.domain.models import (
    BranchEvaluationResult,
    FieldSelectionState,
    FormSource,
    FormStatus,
    MoneyAmount,
    NeededFor,
    ProposedContentsItem,
    ProposedFormChange,
    StateChange,
)
from backend.domain.safety_vocabulary import WEAK_SAFETY_PATTERN
from backend.domain.turn_field_contract import TurnFieldContract, TurnFieldViolation
from backend.services.turn_field_contract import validate_field_changes

if TYPE_CHECKING:
    from backend.services.agent import AgentEvidenceReference

logger = logging.getLogger(__name__)

_NON_ANSWER_PATTERN = re.compile(
    r"\b(?:i\s+(?:do\s+not|don't)\s+know|not\s+sure|unknown|no\s+idea|"
    r"can't\s+remember|cannot\s+remember)\b|不知道|不清楚|不确定",
    re.IGNORECASE,
)


def _is_temporal_non_answer(
    field_code: str,
    value: object,
    reported_text: str | None,
) -> bool:
    if field_code not in {'incident.occurred_at', 'incident.discovered_at'}:
        return False
    quote = ' '.join((reported_text or '').split())
    return bool(
        _NON_ANSWER_PATTERN.search(quote)
        or (isinstance(value, str) and value.strip().casefold() in {'unknown', 'not known'})
    )


_STATE_WHITELIST = {
    'claim_state.urgency': frozenset({'urgent'}),
    'claim_state.customer_support': frozenset(
        {'guided', 'human_requested', 'accessibility_required'}
    ),
}
_EXECUTION_CLAIM = re.compile(
    r"\b(?:I|we|Northwind)(?:'ve|'ll|\u2019ve|\u2019ll)?\s+(?:(?:have|will)\s+)?"
    r'(?:arrange(?:d)?|book(?:ed)?|submit(?:ted)?|sent|send|contact(?:ed)?|'
    r'approve(?:d)?|complete(?:d)?|schedule(?:d)?)\b',
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ValidatedTurn:
    reply: str
    form_changes: list[ProposedFormChange]
    contents_item_changes: list[ProposedContentsItem]
    next_question: V8NextQuestion | None
    service_identities: tuple[str, ...]
    state_changes: list[StateChange]
    escalation: V8Escalation | None
    ready_to_create: bool
    confirms_batch: bool
    rejected: list[dict[str, str]]


def claimant_report_supports_value(
    field_code: str,
    value: object,
    reported_text: str | None,
    message_text: str | None,
) -> bool:
    """Check a direct quotation while preserving boolean polarity checks.

    Args:
        field_code: Registered fact identity.
        value: Contract-validated normalized value.
        reported_text: The supporting claimant quotation.
        message_text: The current claimant utterance.
    Returns:
        Whether this kind of value is supported by the direct quotation.
    """
    quote = ' '.join((reported_text or '').split()).casefold()
    message = ' '.join((message_text or '').split()).casefold()
    if not quote or quote not in message:
        return False
    if _is_temporal_non_answer(field_code, value, reported_text):
        return False
    if isinstance(value, str):
        return True
    if isinstance(value, list):
        return all(
            isinstance(item, str) and ' '.join(item.split()).casefold() in quote for item in value
        )
    if not isinstance(value, bool):
        return False
    negative = bool(
        re.search(r"\b(?:no|none|nobody|not|never|cannot|can't|isn't|wasn't|without)\b", quote)
    )
    markers = {
        'incident.injury_or_danger': WEAK_SAFETY_PATTERN,
        'parties.other_parties': r'\b(?:another|other|second|person|people|vehicle|party)\b',
        'vehicle.drivable': r'\b(?:driv(?:e|en|able)|roadworthy|safe|unsafe)\b',
        'property.ongoing_risk': r'\b(?:risk|leak|fire|flood|exposed|unsafe|danger)\b',
        'property.habitable': r'\b(?:habitable|live|lived|safe|unsafe|uninhabitable)\b',
    }
    marker = markers.get(field_code)
    return marker is not None and re.search(marker, quote) is not None and value is not negative


def _accepted_family(
    branch_evaluation: BranchEvaluationResult,
    changes: Sequence[ProposedFormChange],
) -> str | None:
    """Return the family accepted for this turn's semantic field checks."""
    if branch_evaluation.selected_family in {'motor', 'home', 'contents'}:
        return branch_evaluation.selected_family
    family_change = next(
        (
            change
            for change in changes
            if change.field_code == 'claim.product_family'
            and change.source is FormSource.CLAIMANT
            and isinstance(change.value, str)
            and change.value in {'motor', 'home', 'contents'}
        ),
        None,
    )
    return family_change.value if family_change is not None else None


def _apply_family_semantic_boundary(
    changes: list[ProposedFormChange],
    *,
    branch_evaluation: BranchEvaluationResult,
    reject: Callable[[str, str, str], None],
) -> list[ProposedFormChange]:
    """Keep direct quotes from confirming a field belonging to another family."""
    accepted_family = _accepted_family(branch_evaluation, changes)
    field_registry = build_default_registry().field_by_code
    bounded: list[ProposedFormChange] = []
    for change in changes:
        definition = field_registry.get(change.field_code)
        families = definition.families if definition is not None else frozenset()
        if not families:
            bounded.append(change)
            continue
        if accepted_family is not None and accepted_family not in families:
            reject('field_change', change.field_code, 'family_field_mismatch')
            continue
        if accepted_family is None and change.source is FormSource.CLAIMANT:
            bounded.append(
                change.model_copy(
                    update={
                        'source': FormSource.INFERENCE,
                        'status': FormStatus.PROPOSED,
                        'confidence': None,
                    }
                )
            )
            continue
        bounded.append(change)
    return bounded


def parse_turn_proposal(raw: dict[str, object]) -> tuple[V8TurnProposal, list[dict[str, str]]]:
    """Parse required fields strictly while discarding malformed optional proposals.

    Args:
        raw: Provider JSON, never trusted as Runtime authority.
    Returns:
        The core-valid envelope and structured optional-part rejections.
    Raises:
        ValidationError: The required envelope or core field changes are invalid.
    """

    prepared = dict(raw)
    rejected: list[dict[str, str]] = []
    # Validate original prose before removing an optional question. Otherwise an
    # empty or overlong core reply could become valid through fallback wording.
    original_reply = V8TurnProposal.model_validate(
        {
            'reply': raw.get('reply'),
            'reason_codes': ['REPLY_VALIDATION'],
        }
    ).reply
    if not original_reply.strip():
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    raw_question = prepared.get('next_question')
    if raw_question is not None:
        try:
            prepared['next_question'] = V8NextQuestion.model_validate(raw_question).model_dump()
        except ValidationError:
            prepared['next_question'] = None
            rejected.append(
                {
                    'part': 'next_question',
                    'value': 'invalid_structure',
                    'reason': 'optional_part_invalid',
                }
            )
            wording = raw_question.get('wording') if isinstance(raw_question, dict) else None
            if isinstance(wording, str) and wording:
                remaining = original_reply.replace(wording, '').strip()
                prepared['reply'] = remaining or 'I have recorded your message.'
    raw_fields = prepared.get('field_changes', [])
    if isinstance(raw_fields, list):
        accepted_fields = []
        for index, value in enumerate(raw_fields):
            if index >= 8:
                rejected.append(
                    {'part': 'field_change', 'value': str(index), 'reason': 'length_limit_exceeded'}
                )
                continue
            try:
                accepted_fields.append(V8FieldChange.model_validate(value).model_dump())
            except ValidationError as error:
                if not all(
                    item['type'] in {'string_too_long', 'too_long'} for item in error.errors()
                ):
                    raise
                rejected.append(
                    {'part': 'field_change', 'value': str(index), 'reason': 'length_limit_exceeded'}
                )
        prepared['field_changes'] = accepted_fields
    for part, model in (
        ('service_suggestions', V8ServiceSuggestion),
        ('state_proposals', V8StateProposal),
    ):
        accepted = []
        values = prepared.get(part, [])
        if not isinstance(values, list):
            values = [values]
        for value in values:
            try:
                accepted.append(model.model_validate(value).model_dump())
            except ValidationError:
                rejected.append(
                    {'part': part, 'value': 'invalid_structure', 'reason': 'optional_part_invalid'}
                )
        limit = 3 if part == 'service_suggestions' else 2
        if len(accepted) > limit:
            rejected.append(
                {
                    'part': part,
                    'value': str(len(accepted) - limit),
                    'reason': 'optional_part_limit_exceeded',
                }
            )
        prepared[part] = accepted[:limit]
    if prepared.get('escalation') is not None:
        try:
            prepared['escalation'] = V8Escalation.model_validate(
                prepared['escalation']
            ).model_dump()
        except ValidationError:
            prepared['escalation'] = None
            rejected.append(
                {
                    'part': 'escalation',
                    'value': 'invalid_structure',
                    'reason': 'optional_part_invalid',
                }
            )
    if not isinstance(prepared.get('ready_to_create', False), bool):
        prepared['ready_to_create'] = False
        rejected.append(
            {
                'part': 'ready_to_create',
                'value': 'invalid_structure',
                'reason': 'optional_part_invalid',
            }
        )
    for rejection in rejected:
        logger.info('agent_turn_part_rejected', extra={'rejection': rejection})
    return V8TurnProposal.model_validate(prepared), rejected


def truthful_reply(
    reply: str,
    rejected_services: Collection[str] = (),
    *,
    batch_confirmed: bool | None = None,
    ready_to_create: bool | None = None,
) -> str:
    """Remove unsupported execution claims and rejected-service sentences.

    Args:
        reply: Model-authored reply, before Runtime's service option wording.
        rejected_services: Service identities refused by the current authority set.
        batch_confirmed: Actual post-reduction batch outcome, when available.
        ready_to_create: Actual post-reduction creation readiness, when available.
    Returns:
        The remaining natural reply, with a truthful non-promissory fallback.
    """

    names: set[str] = set()
    for identity in rejected_services:
        entry = SERVICE_REGISTRY.get(identity)
        if entry is None:
            continue
        names.add(entry.service_name.casefold())
        names.update(
            word
            for word in re.findall(r'[a-z]+', entry.service_name.casefold())
            if word
            not in {
                'vehicle',
                'home',
                'contents',
                'information',
                'guidance',
                'reporting',
                'specialist',
            }
        )
    kept = []
    for sentence in re.split(r'(?<=[.!?])\s+', reply.strip()):
        if _EXECUTION_CLAIM.search(sentence):
            continue
        if any(name in sentence.casefold() for name in names):
            continue
        if not sentence.rstrip().endswith('?'):
            confirmation_claim = batch_confirmed is False and re.search(
                r'\b(?:(?:all|everything)\b[^?!.]{0,80}\b(?:confirmed|correct|verified)'
                r'|confirm(?:ed)?\b[^?!.]{0,40}\b(?:all|everything)'
                r'|(?:recorded|marked|treated)\b[^?!.]{0,70}\bas confirmed'
                r'|(?:the information|these details)\b[^?!.]{0,45}\bconfirmed)\b',
                sentence,
                re.IGNORECASE,
            )
            # A negated status is truthful and must not be mistaken for a
            # positive readiness claim merely because it contains "ready".
            readiness_claim = False
            if ready_to_create is False:
                for match in re.finditer(
                    r'\bready to (?:create|submit|be (?:created|submitted))\b',
                    sentence,
                    re.IGNORECASE,
                ):
                    prefix = sentence[: match.start()]
                    if not re.search(
                        r"\b(?:not|never|isn't|aren't)(?:\s+yet)?\s*$", prefix, re.IGNORECASE
                    ):
                        readiness_claim = True
            negated_confirmation = bool(
                re.search(
                    r"\b(?:not|never|haven't|hasn't)\b[^.!?]{0,50}\b(?:confirmed|verified)\b",
                    sentence,
                    re.IGNORECASE,
                )
            )
            if (confirmation_claim and not negated_confirmation) or readiness_claim:
                continue
        kept.append(sentence)
    return ' '.join(kept).strip() or 'I have recorded your message. We can continue your report.'


def validate_turn_proposal(
    proposal: V8TurnProposal,
    *,
    branch_evaluation: BranchEvaluationResult,
    eligible_service_ids: Collection[str],
    safety_interrupt: object | None,
    field_contract: TurnFieldContract,
    open_handoffs: Collection[object],
    message_text: str | None,
    evidence: Sequence[AgentEvidenceReference] = (),
    service_eligibility_resolver: Callable[[list[ProposedFormChange]], Collection[str]]
    | None = None,
) -> ValidatedTurn:
    """Validate one model envelope without applying claim mutations.

    Args:
        proposal: Parsed v8 envelope; core structural failures are rejected upstream.
        branch_evaluation: Authoritative requirements before reduction.
        eligible_service_ids: Runtime-computed eligible service identities.
        safety_interrupt: Runtime marker which the model cannot cancel.
        field_contract: Current registered field authority and scalar contracts.
        open_handoffs: Active handoffs; any entry suppresses every service suggestion.
        message_text: Latest claimant message used solely as fact provenance.
        evidence: Evidence authorised for this model request.
        service_eligibility_resolver: Existing eligibility query using validated turn facts.
    Returns:
        A typed, immutable boundary consumed by the sole claimant reducer.
    Raises:
        ModelGatewayError: A required reply or evidence reference is malformed.
        TurnFieldContractViolation: Any core field change breaks the field contract.
    """

    if not proposal.reply.strip():
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    rejected: list[dict[str, str]] = []

    def reject(part: str, value: str, reason: str) -> None:
        record = {'part': part, 'value': value, 'reason': reason}
        rejected.append(record)
        logger.info('agent_turn_part_rejected', extra={'rejection': record})

    requirements = branch_evaluation.requirements
    question = proposal.next_question
    proposed_reply = proposal.reply
    if question is not None and not set(question.field_codes).issubset(
        requirements.missing_required_now
    ):
        reject('next_question', ','.join(question.field_codes), 'field_not_missing')
        # Remove this rejected proposal's exact wording only. Other questions
        # remain model-authored content; never delete every question sentence.
        proposed_reply = proposed_reply.replace(question.wording, '').strip()
        question = None

    state_changes: list[StateChange] = []
    for state in proposal.state_proposals:
        if state.to not in _STATE_WHITELIST.get(state.path, frozenset()):
            reject('state_proposal', f'{state.path}={state.to}', 'state_not_whitelisted')
        else:
            state_changes.append(StateChange(path=state.path, to=state.to))

    escalation = proposal.escalation
    if safety_interrupt is not None:
        kind = getattr(safety_interrupt, 'kind', 'urgent_safety')
        if kind not in {
            'urgent_safety',
            'human_requested',
            'accessibility',
            'distress',
            'professional_review',
        }:
            kind = 'urgent_safety'
        escalation = V8Escalation(
            kind=kind, reason=str(getattr(safety_interrupt, 'reason', 'Runtime safety rule'))[:150]
        )

    evidence_by_id = {item.evidence_id: item for item in evidence}
    changes: list[ProposedFormChange] = []
    field_bound_rejections: list[TurnFieldViolation] = []
    validated_changes = validate_field_changes(
        field_contract, proposal.field_changes, rejected_bounds=field_bound_rejections
    )
    for rejection in field_bound_rejections:
        reject('field_change', rejection.field_code, rejection.reason_code)
    for change in validated_changes:
        if _is_temporal_non_answer(change.field_code, change.value, change.reported_text):
            reject('field_change', change.field_code, 'temporal_non_answer')
            continue
        source = FormSource.INFERENCE
        if change.source_evidence_id is not None:
            attached = evidence_by_id.get(change.source_evidence_id)
            if attached is None:
                raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
            source = (
                FormSource.IMAGE
                if attached.media_type.startswith('image/')
                else FormSource.DOCUMENT
            )
        elif claimant_report_supports_value(
            change.field_code, change.value, change.reported_text, message_text
        ):
            source = FormSource.CLAIMANT
        selected = field_contract.by_code[change.field_code]
        changes.append(
            ProposedFormChange(
                field_code=change.field_code,
                value=change.value,
                source=source,
                status=FormStatus.CONFIRMED
                if source is FormSource.CLAIMANT
                else FormStatus.PROPOSED,
                needed_for=NeededFor.LATER_ACTION
                if selected.selection_state is FieldSelectionState.PENDING_LATER
                else NeededFor.CURRENT_ACTION,
                confidence=1.0 if source is FormSource.CLAIMANT else None,
                precision=change.precision,
                reported_text=change.reported_text,
                source_evidence_id=change.source_evidence_id,
            )
        )
    changes = _apply_family_semantic_boundary(
        changes,
        branch_evaluation=branch_evaluation,
        reject=reject,
    )
    services_suppressed = bool(
        open_handoffs or safety_interrupt is not None or escalation is not None
    )
    if service_eligibility_resolver is not None and not services_suppressed:
        eligible_service_ids = service_eligibility_resolver(changes)
    service_ids: list[str] = []
    rejected_services: list[str] = []
    for suggestion in proposal.service_suggestions:
        identity = suggestion.service_identity
        reason = (
            'suppressed_during_handoff'
            if services_suppressed
            else ('service_not_eligible' if identity not in eligible_service_ids else None)
        )
        if reason is not None:
            reject('service_suggestion', identity, reason)
            rejected_services.append(identity)
        elif identity not in service_ids:
            service_ids.append(identity)
    contents = []
    for item in proposal.contents_item_changes:
        values = item.model_dump()
        if values.get('estimated_value') is not None:
            values['estimated_value'] = MoneyAmount.model_validate(values['estimated_value'])
        contents.append(ProposedContentsItem(**values))
    reply = truthful_reply(proposed_reply, rejected_services)
    for identity in service_ids:
        name = SERVICE_REGISTRY[identity].service_name if identity in SERVICE_REGISTRY else identity
        reply += f' I can also help arrange {name} — see the option below.'
    if proposal.ready_to_create and not requirements.ready:
        reject('ready_to_create', 'true', 'requirements_not_ready')
    return ValidatedTurn(
        reply=reply,
        form_changes=changes,
        contents_item_changes=contents,
        next_question=question,
        service_identities=tuple(service_ids),
        state_changes=state_changes,
        escalation=escalation,
        ready_to_create=proposal.ready_to_create and requirements.ready,
        confirms_batch=proposal.confirms_batch,
        rejected=rejected,
    )
