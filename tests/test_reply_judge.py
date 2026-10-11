"""The review model reads each reply against its turn; no rule stands in for it."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any, cast

import pytest

from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelRequest,
    ModelResponse,
)
from backend.services.agent import AgentTurnContext
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


def test_a_clean_judgement_is_final() -> None:
    judge = ReplyJudge(lambda: _Gateway({'problems': []}))
    assert review_reply(_turn("I've escalated this for a review. Anything else?"), judge).consistent


def test_no_rule_stands_in_when_the_judge_cannot_answer() -> None:
    judge = ReplyJudge(lambda: _Gateway(error=True))
    review = review_reply(_turn('Please check with your insurer. Anything else?'), judge)
    # The reply is shown and the turn is recorded as not reviewed.
    assert review.consistent
    assert not review.words_reviewed


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


@pytest.mark.parametrize(
    ('reply', 'changes', 'mismatch'),
    [
        # A card was offered, but "question" was declared and none was asked.
        ('Here is a tow option.', {'service_identities': ('vehicle_recovery_request',)}, True),
        ('Nothing else needed. Can you send a photo?', {'turn_ending': 'nothing_needed'}, True),
        ('Which road were you on?', {}, False),
        (
            'Nothing else is needed; the team will review it.',
            {'turn_ending': 'nothing_needed'},
            False,
        ),
    ],
)
def test_the_declared_ending_matches_the_reply(
    reply: str, changes: dict[str, Any], mismatch: bool
) -> None:
    review = review_reply(_turn(reply, **changes))
    assert ('ending_mismatch' in [item.kind for item in review.inconsistencies]) is mismatch
    # Sent back once, but not a false statement about what Northwind did.
    assert review.truthful


def test_the_review_runs_however_long_the_turn_took() -> None:
    # The turn limit caps the turn's own model calls; the review has its own
    # timeout and is never replaced by rules because the turn was slow.
    gateway = _Gateway({'problems': []})
    agent = GatewayAgent(
        _Gateway(), reply_judge=ReplyJudge(lambda: gateway), turn_time_limit_seconds=40
    )
    context = cast(
        AgentTurnContext,
        SimpleNamespace(claim=SimpleNamespace(claim_id='clm_slow'), trigger_message_id='msg_slow'),
    )
    review = agent._review(_turn('Which road were you on?'), context)
    assert review.words_reviewed
    assert len(gateway.requests) == 1


def test_saying_the_report_already_reached_the_claims_team_is_sent_back() -> None:
    gateway = _Gateway(
        {
            'problems': [
                {
                    'kind': 'claims_report_already_sent',
                    'detail': 'Your claim details are complete and have been sent for review.',
                }
            ]
        }
    )
    review = review_reply(
        _turn(
            'Your claim details are complete and have been sent for review.',
            action='summarize',
            summary_fields=('incident.description',),
            turn_ending='summary',
        ),
        ReplyJudge(lambda: gateway),
    )

    assert [item.kind for item in review.inconsistencies] == ['claims_report_already_sent']
    # Sent back once; a rewrite that still has it does not fail the claimant's turn.
    assert review.truthful
    instruction = gateway.requests[0].messages[0].content or ''
    assert 'claims_report_already_sent' in instruction
