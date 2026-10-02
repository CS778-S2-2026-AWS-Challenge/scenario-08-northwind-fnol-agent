"""A second model reads each reply against what the turn actually did.

Regex rules match English wording and miss a rephrased promise. The judge gets
the reply and a ledger of the turn's structured parts (services offered or
refused, escalation, questions passed to the claims team, declared ending) and
names the problems it finds. Runtime still never edits the reply: problems send
the turn back to the turn model once (``reply_consistency``). When the judge is
not configured or its call fails, the existing rules are used instead.
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
REPLY_REVIEW_PROMPT_VERSION = 'northwind-reply-review-v1'

PROBLEM_KINDS = (
    'names_rejected_service',
    'claims_arrangement_without_service',
    'offers_service_in_words',
    'refers_to_insurer',
    'claims_escalation_without_one',
    'promises_answer_without_question',
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
- promises_answer_without_question: questions_passed_on is empty and the reply says the claims \
team will confirm, answer or check something for the claimant.

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
        'questions_passed_on': [item.question for item in validated.northwind_questions],
        'summary_fields': list(validated.summary_fields),
        'next_question': (
            validated.next_question.wording if validated.next_question is not None else None
        ),
    }


class ReplyJudge:
    """Ask the review model for problems; None means "use the rules instead"."""

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
