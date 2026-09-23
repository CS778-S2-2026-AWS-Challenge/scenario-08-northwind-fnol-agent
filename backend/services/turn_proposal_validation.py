"""Validate the v8 turn envelope before the claimant reducer applies it."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import ValidationError

from backend.domain.agent_v8 import (
    V8DocumentRequest,
    V8Escalation,
    V8EvidenceInterpretation,
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
    FactPrecision,
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

# The claimant saying they cannot supply a fact yet. Runtime records the fact
# as unavailable-for-now instead of asking again or storing the words as a value.
_NON_ANSWER_PATTERN = re.compile(
    r"\b(?:i\s+(?:do\s+not|don't)\s+know|not\s+sure|unsure|unknown|no\s+idea|"
    r"can't\s+(?:remember|say|tell|see)|cannot\s+(?:remember|say|tell|see)|"
    r"(?:don't|do\s+not|didn't|did\s+not)\s+(?:have|see|notice|check)|"
    r"haven't\s+(?:got|checked|looked)|later|will\s+(?:send|check|find\s+out)|"
    r'too\s+dark|hard\s+to\s+(?:say|tell))\b|不知道|不清楚|不确定|稍后|以后',
    re.IGNORECASE,
)


def _is_non_answer(value: object, reported_text: str | None) -> bool:
    quote = ' '.join((reported_text or '').split())
    return bool(
        _NON_ANSWER_PATTERN.search(quote)
        or (isinstance(value, str) and value.strip().casefold() in {'unknown', 'not known'})
    )


def _is_temporal_non_answer(
    field_code: str,
    value: object,
    reported_text: str | None,
) -> bool:
    if field_code not in {'incident.occurred_at', 'incident.discovered_at'}:
        return False
    return _is_non_answer(value, reported_text)


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
    action: str = 'record_and_ask'
    # Fields the model read back to the claimant this turn (action == summarize).
    summary_fields: tuple[str, ...] = ()
    document_requests: tuple[V8DocumentRequest, ...] = ()
    evidence_interpretations: tuple[V8EvidenceInterpretation, ...] = ()
    # Service identities the model proposed but Runtime refused this turn.
    rejected_services: tuple[str, ...] = ()


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
    # Some models wrap their quotation in literal quote marks as a formatting
    # habit ("rear-ended" instead of rear-ended). That wrapper is not part of
    # the claimant's words; strip one symmetric layer before matching, not a
    # relaxation of the verbatim-substring requirement itself.
    quote_wrapping_chars = '"\'‘’“”'  # noqa: RUF001 -- typographic quotes some models emit
    quote = ' '.join((reported_text or '').split()).casefold().strip(quote_wrapping_chars)
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
        if (
            accepted_family is None
            and change.source is FormSource.CLAIMANT
            and change.status is FormStatus.CONFIRMED
        ):
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
        logger.warning(
            'agent_turn_envelope_blank_reply',
            extra={'envelope_keys': sorted(raw.keys())},
        )
        raise ModelGatewayError(ModelGatewayErrorCode.MALFORMED_RESPONSE)
    raw_question = prepared.get('next_question')
    if raw_question is not None:
        try:
            prepared['next_question'] = V8NextQuestion.model_validate(raw_question).model_dump()
        except ValidationError:
            # Only the structured part is dropped. The reply keeps the model's
            # words: the claimant still hears the question, Runtime just does
            # not record it as a bounded question against the form.
            prepared['next_question'] = None
            rejected.append(
                {
                    'part': 'next_question',
                    'value': 'invalid_structure',
                    'reason': 'optional_part_invalid',
                }
            )
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
                # One malformed field (too long, or a disposition/value shape
                # that does not match) drops only that field. The core
                # envelope must not fail because one field is malformed.
                reason = (
                    'length_limit_exceeded'
                    if all(
                        item['type'] in {'string_too_long', 'too_long'} for item in error.errors()
                    )
                    else 'invalid_structure'
                )
                rejected.append({'part': 'field_change', 'value': str(index), 'reason': reason})
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
    # Legacy v7 path only; the v8 reducer never calls this. A fully struck v7
    # answer falls back to its neutral runtime-owned copy.
    return ' '.join(kept).strip() or 'Your message has been recorded. We can continue your report.'


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
    authorised_service_ids: Collection[str] = (),
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
        authorised_service_ids: Services with a durable, claimant-granted consent
            record on this Claim. A field the model marks third_party_pending
            must name one of these -- being merely eligible to offer is not the
            same as a real party having been authorised to do the work.
    Returns:
        A typed, immutable boundary consumed by the sole claimant reducer.
    Raises:
        ModelGatewayError: A required reply or evidence reference is malformed.
        TurnFieldContractViolation: Any core field change breaks the field contract.
    """

    if not proposal.reply.strip():
        logger.warning('validate_turn_proposal_blank_reply')
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
        # The model chose to ask about something Runtime already holds. That is
        # the model's call to make; Runtime observes it for prompt tuning and
        # leaves the reply exactly as written.
        logger.info(
            'agent_turn_observation',
            extra={
                'observation': {
                    'part': 'next_question',
                    'value': ','.join(question.field_codes),
                    'note': 'field_not_missing',
                }
            },
        )

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
    pending_changes: list[tuple[V8FieldChange, NeededFor]] = []
    field_bound_rejections: list[TurnFieldViolation] = []
    validated_changes = validate_field_changes(
        field_contract, proposal.field_changes, rejected_bounds=field_bound_rejections
    )
    for rejection in field_bound_rejections:
        reject('field_change', rejection.field_code, rejection.reason_code)
    for change in validated_changes:
        selected = field_contract.by_code[change.field_code]
        needed_for = (
            NeededFor.LATER_ACTION
            if selected.selection_state is FieldSelectionState.PENDING_LATER
            else NeededFor.CURRENT_ACTION
        )
        disposition = getattr(change, 'disposition', 'value')
        if disposition == 'value' and _is_temporal_non_answer(
            change.field_code, change.value, change.reported_text
        ):
            # "I don't know when" is a disposition, not a time. Record it as such
            # so the report carries the gap instead of a fabricated value.
            disposition = 'claimant_will_supply'
        if (
            disposition == 'claimant_will_supply'
            and change.value is not None
            and not _is_non_answer(change.value, change.reported_text)
        ):
            # The model labelled this a non-answer but also supplied a real
            # value with a quote. The label is the model's guess; whether the
            # quote actually supports a value is Runtime's call, not the
            # model's. If it looks like a genuine answer, keep it as one
            # instead of discarding what the claimant actually said.
            disposition = 'value'
        if disposition == 'claimant_will_supply':
            # The claimant's own non-answer authorises UNAVAILABLE; the model
            # cannot invent one. A quote that is not actually in this
            # message, or that does not read as a genuine "I don't know /
            # will send later", is not authority to mark the field settled --
            # it stays missing so the report still asks for it.
            quote = ' '.join((change.reported_text or '').split())
            current_message = (message_text or '').casefold()
            if (
                not quote
                or quote.casefold() not in current_message
                or not _is_non_answer(change.value, change.reported_text)
            ):
                reject('field_change', change.field_code, 'unavailable_without_claimant_quote')
                continue
            changes.append(
                ProposedFormChange(
                    field_code=change.field_code,
                    value=None,
                    source=FormSource.CLAIMANT,
                    status=FormStatus.UNAVAILABLE,
                    needed_for=needed_for,
                    precision=FactPrecision.UNKNOWN,
                    reported_text=change.reported_text,
                )
            )
            continue
        if disposition == 'third_party_pending':
            pending_changes.append((change, needed_for))
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
        changes.append(
            ProposedFormChange(
                field_code=change.field_code,
                value=change.value,
                source=source,
                status=FormStatus.CONFIRMED
                if source is FormSource.CLAIMANT
                else FormStatus.PROPOSED,
                needed_for=needed_for,
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
    # A fact the model hands to a third party needs a real, durable
    # responsibility record for that service on this Claim -- being merely
    # eligible to offer the service is not evidence anyone has actually taken
    # it on. Without that authorised record, the field stays open rather than
    # settling on an unaccountable "someone else has this" claim.
    for change, needed_for in pending_changes:
        identity = str(change.service_identity)
        if (
            services_suppressed
            or identity not in eligible_service_ids
            or identity not in authorised_service_ids
        ):
            reject('field_change', change.field_code, 'service_not_authorised_for_field')
            continue
        changes.append(
            ProposedFormChange(
                field_code=change.field_code,
                value=None,
                source=FormSource.INFERENCE,
                status=FormStatus.PENDING_GENERATION,
                needed_for=needed_for,
                precision=FactPrecision.UNKNOWN,
                reported_text=change.reported_text,
            )
        )
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
    document_requests: list[V8DocumentRequest] = []
    for request in proposal.document_requests:
        if request.from_party == 'third_party' and (
            services_suppressed or request.service_identity not in eligible_service_ids
        ):
            reject('document_request', request.document_kind, 'service_not_eligible')
            continue
        document_requests.append(request)
    interpretations: list[V8EvidenceInterpretation] = []
    for interpretation in proposal.evidence_interpretations:
        if interpretation.evidence_id not in evidence_by_id:
            reject('evidence_interpretation', interpretation.evidence_id, 'evidence_not_in_turn')
            continue
        interpretations.append(interpretation)
    contents = []
    for item in proposal.contents_item_changes:
        values = item.model_dump()
        if values.get('estimated_value') is not None:
            values['estimated_value'] = MoneyAmount.model_validate(values['estimated_value'])
        contents.append(ProposedContentsItem(**values))
    action = proposal.action
    summary_fields: tuple[str, ...] = ()
    if action == 'summarize':
        known = set(field_contract.by_code) | {'contents.items'}
        listed = [code for code in (proposal.summary_fields or []) if code in known]
        if not listed:
            reject(
                'summary_fields', ','.join(proposal.summary_fields or []), 'summary_fields_required'
            )
            action = 'record_and_ask'
        else:
            summary_fields = tuple(dict.fromkeys(listed))
    if proposal.ready_to_create and not requirements.ready:
        reject('ready_to_create', 'true', 'requirements_not_ready')
    # The reply is the model's words to the claimant. Runtime neither appends
    # to it nor deletes from it; a reply that contradicts the ledger is sent
    # back to the model (reply_consistency) rather than edited here.
    return ValidatedTurn(
        reply=proposed_reply,
        form_changes=changes,
        contents_item_changes=contents,
        next_question=question,
        service_identities=tuple(service_ids),
        state_changes=state_changes,
        escalation=escalation,
        ready_to_create=proposal.ready_to_create and requirements.ready,
        confirms_batch=proposal.confirms_batch,
        rejected=rejected,
        action=action,
        summary_fields=summary_fields,
        document_requests=tuple(document_requests),
        evidence_interpretations=tuple(interpretations),
        rejected_services=tuple(rejected_services),
    )
