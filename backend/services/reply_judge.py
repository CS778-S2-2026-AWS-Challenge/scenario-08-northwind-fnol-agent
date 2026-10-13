"""A second model reads each reply against what the turn actually did.

Whether a reply says something the turn does not back is a judgement about
meaning, so a model makes it. The judge gets the reply and a ledger of the
turn's structured parts (services offered or refused, escalation, questions
passed to the claims team, declared ending) and names the problems it finds.
Runtime still never edits the reply: problems send the turn back to the turn
model once (``reply_consistency``). When the judge is not configured or its call
fails, no rule stands in: the reply is shown and the turn is logged as not
reviewed.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any

from backend.domain.model_gateway import (
    CLAIMANT_AGENT_PRIVACY_CLASS,
    ModelCompletionStatus,
    ModelGateway,
    ModelGatewayError,
    ModelMessage,
    ModelRequest,
    ModelRole,
)

logger = logging.getLogger(__name__)

REPLY_REVIEW_PURPOSE = 'reply_review'
REPLY_REVIEW_PROMPT_VERSION = 'northwind-reply-review-v4'
# Longest a review call may take; it runs after the turn's own model calls.
REPLY_JUDGE_TIMEOUT_SECONDS = 20.0

PROBLEM_KINDS = (
    'names_rejected_service',
    'claims_arrangement_without_service',
    'offers_service_in_words',
    'refers_to_insurer',
    'claims_escalation_without_one',
    'promises_answer_without_question',
    'claims_documents_block_lodging',
    'claims_report_already_sent',
    'unsupported_policy_conclusion',
)

JUDGE_INSTRUCTION = """You check one reply from Northwind's claims assistant against the ledger of \
what the system actually did this turn. Northwind is the claimant's insurer. Report a problem only \
when the reply clearly says something the ledger does not back; wording style is not a problem.

- names_rejected_service: the reply names or promises a service listed in refused_services.
- claims_arrangement_without_service: the reply says something was arranged, booked, approved, \
sent or contacted. Saying the report will be sent to the claims team is fine.
- offers_service_in_words: offered_services is empty and the reply asks whether the claimant wants \
a service such as towing, repairs, an assessor or a rental car. Services are offered as cards.
- refers_to_insurer: the reply tells the claimant to contact or check with their insurer or \
insurance company.
- claims_escalation_without_one: escalation is null and the reply says it escalated, referred or \
passed the claim to a person.
- promises_answer_without_question: the reply says the claims team will confirm, answer or check \
something for the claimant, and that thing is not one of questions_passed_on.
- claims_documents_block_lodging: the reply says a photo, quote or other document is needed \
before the claim can be lodged or submitted. Documents never block lodging; asking for one, or \
saying it helps, is fine.
- claims_report_already_sent: the reply says the report or claim has already been submitted, \
sent, logged or lodged, or that the claims team already has it or is reviewing it. Nothing \
reaches the claims team until the claimant submits the report themselves. Saying the claims \
team will handle something after the claimant submits is fine.
- unsupported_policy_conclusion: the reply says a particular cost, loss, benefit, or event is \
covered, not covered, payable, or excluded, but policy_sources is empty or the returned text does \
not directly support that conclusion about the same subject. Conditional wording is supported only \
when the returned text states that condition. Saying the wording could not be checked, or that no \
matching clause was found, is fine and is not a coverage conclusion.

Return {"problems": []} when the reply is fine. Each detail quotes the words at fault."""

JUDGE_SCHEMA: dict[str, object] = {
    'type': 'object',
    'additionalProperties': False,
    'required': ['problems'],
    'properties': {
        'problems': {
            'type': 'array',
            'maxItems': 4,
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['kind', 'detail'],
                'properties': {
                    'kind': {'type': 'string', 'enum': list(PROBLEM_KINDS)},
                    'detail': {'type': 'string', 'minLength': 1, 'maxLength': 200},
                },
            },
        }
    },
}


def turn_ledger(validated: Any) -> dict[str, object]:
    """The structured facts of one turn the reply may speak about."""

    return {
        'action': validated.action,
        'declared_ending': validated.turn_ending,
        'offered_services': list(validated.service_identities),
        'refused_services': list(validated.rejected_services),
        'escalation': validated.escalation.kind if validated.escalation is not None else None,
        'documents_asked': [
            {'kind': item.document_kind, 'stance': item.stance}
            for item in validated.document_requests
        ],
        'questions_passed_on': [
            *(item.question for item in validated.northwind_questions),
            *getattr(validated, 'earlier_open_questions', ()),
        ],
        'summary_fields': list(validated.summary_fields),
        'policy_sources': [
            {
                'section_path': str(source.get('section_path', ''))[:300],
                'text': str(source.get('text', ''))[:3000],
            }
            for source in validated.policy_judgment_sources
        ],
        'next_question': (
            validated.next_question.wording if validated.next_question is not None else None
        ),
    }


class ReplyJudge:
    """Ask the review model for problems; None means the words were not reviewed."""

    def __init__(self, gateway_factory: Callable[[], ModelGateway]) -> None:
        self._gateway_factory = gateway_factory

    def problems(self, validated: Any) -> list[tuple[str, str]] | None:
        request = ModelRequest(
            messages=[
                ModelMessage(role=ModelRole.SYSTEM, content=JUDGE_INSTRUCTION),
                ModelMessage(
                    role=ModelRole.USER,
                    content=json.dumps(
                        {'reply': validated.reply, 'ledger': turn_ledger(validated)},
                        separators=(',', ':'),
                        sort_keys=True,
                    ),
                ),
            ],
            response_schema=JUDGE_SCHEMA,
            max_output_tokens=400,
            purpose=REPLY_REVIEW_PURPOSE,
            prompt_version=REPLY_REVIEW_PROMPT_VERSION,
            privacy_class=CLAIMANT_AGENT_PRIVACY_CLASS,
        )
        try:
            response = self._gateway_factory().complete(request)
        except ModelGatewayError as error:
            logger.warning('reply_judge_unavailable', extra={'error_code': error.code.value})
            return None
        output = response.structured_output
        if response.completion_status is not ModelCompletionStatus.COMPLETE or not isinstance(
            output, dict
        ):
            logger.warning('reply_judge_incomplete')
            return None
        listed = output.get('problems')
        found: list[tuple[str, str]] = []
        for item in listed if isinstance(listed, list) else ():
            if isinstance(item, dict) and item.get('kind') in PROBLEM_KINDS:
                found.append((str(item['kind']), str(item.get('detail') or '')[:200]))
        return found
