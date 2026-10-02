"""The review model reads each reply against its turn; rules are the fallback."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelResponse,
)
from backend.services.model_agent import GatewayAgent
from backend.services.reply_consistency import review_reply
from backend.services.reply_judge import REPLY_REVIEW_PURPOSE, ReplyJudge, turn_ledger
from backend.services.turn_proposal_validation import ValidatedTurn


class _Gateway:
    def __init__(self, output: dict[str, Any] | None = None, error: bool = False) -> None:
        self.output = output
        self.error = error
        self.requests: list[ModelRequest] = []

    @property
    def capabilities(self) -> ModelCapabilities:
        return ModelCapabilities(structured_output=True)

    def complete(self, request: ModelRequest) -> ModelResponse:
        self.requests.append(request)
        if self.error:
            raise ModelGatewayError(ModelGatewayErrorCode.TIMEOUT)
        return ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE, structured_output=self.output
        )


def _turn(reply: str, **changes: Any) -> ValidatedTurn:
    base = ValidatedTurn(
        reply=reply,
        form_changes=[],
        contents_item_changes=[],
        next_question=None,
        service_identities=(),
        state_changes=[],
        escalation=None,
        ready_to_create=False,
        confirms_batch=False,
        rejected=[],
        turn_ending='question',
    )
    return replace(base, **changes)


def test_the_judge_reads_the_reply_with_the_turn_ledger() -> None:
    gateway = _Gateway(
        {'problems': [{'kind': 'refers_to_insurer', 'detail': 'run it past your provider'}]}
    )
    judge = ReplyJudge(lambda: gateway)
    turn = _turn('Hire cars vary, so run it past your provider. Anything else?')

    review = review_reply(turn, judge)

    assert [item.kind for item in review.inconsistencies] == ['refers_to_insurer']
    request = gateway.requests[0]
    assert request.purpose == REPLY_REVIEW_PURPOSE
    assert 'run it past your provider' in (request.messages[-1].content or '')
    assert turn_ledger(turn)['declared_ending'] == 'question'


def test_a_clean_judgement_overrides_the_english_rules() -> None:
    judge = ReplyJudge(lambda: _Gateway({'problems': []}))
    # The rules would flag this wording; the judge, reading the turn, does not.
    assert review_reply(_turn("I've escalated this for a review. Anything else?"), judge).consistent


def test_the_rules_take_over_when_the_judge_cannot_answer() -> None:
    judge = ReplyJudge(lambda: _Gateway(error=True))
    review = review_reply(_turn('Please check with your insurer. Anything else?'), judge)
    assert [item.kind for item in review.inconsistencies] == ['refers_to_insurer']


def test_a_reply_that_leaves_the_claimant_stuck_is_soft() -> None:
    clean = ReplyJudge(lambda: _Gateway({'problems': []}))
    review = review_reply(_turn('Thanks, noted.'), clean)
    # Sent back once, but a rewrite that is still only stuck is not a false statement.
    assert not review.consistent and review.truthful

    untrue = ReplyJudge(
        lambda: _Gateway({'problems': [{'kind': 'refers_to_insurer', 'detail': 'your insurer'}]})
    )
    assert not review_reply(_turn('Ask your insurer.'), untrue).truthful


def test_no_further_model_call_starts_after_the_turn_limit() -> None:
    agent = GatewayAgent(_Gateway(), turn_time_limit_seconds=40)
    agent._require_turn_time(datetime.now(UTC))
    with pytest.raises(ModelGatewayError) as raised:
        agent._require_turn_time(datetime.now(UTC) - timedelta(seconds=41))
    assert raised.value.code is ModelGatewayErrorCode.TIMEOUT


@pytest.mark.parametrize(
    ('reply', 'changes', 'stuck'),
    [
        ('Thanks, noted.', {}, True),
        ('Thanks, noted. Which road were you on?', {}, False),
        ('Thanks, noted.', {'turn_ending': 'nothing_needed'}, False),
        ('Thanks, noted.', {'service_identities': ('vehicle_recovery_request',)}, False),
        ('Thanks, noted.', {'action': 'answer_only'}, False),
    ],
)
def test_a_reply_with_nothing_to_answer_or_do_is_caught_without_a_model(
    reply: str, changes: dict[str, Any], stuck: bool
) -> None:
    kinds = [item.kind for item in review_reply(_turn(reply, **changes)).inconsistencies]
    assert ('leaves_claimant_stuck' in kinds) is stuck
