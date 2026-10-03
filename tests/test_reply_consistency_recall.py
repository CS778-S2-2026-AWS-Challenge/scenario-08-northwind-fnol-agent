"""D12: a reply that contradicts the ledger goes back to the model, never gets edited."""

import json
from dataclasses import replace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.agent_v8 import V8Escalation, V8NorthwindQuestion
from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse, ModelToolCall
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext, InvariantGuardedAgent
from backend.services.model_agent import GatewayAgent
from backend.services.model_request_planner import plan_model_turn
from backend.services.turn_proposal_validation import ValidatedTurn
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact
from tests.test_agent_context_runtime_v7 import _RecordingGateway

# A Home claim asking for a Motor-only service: Runtime refuses the suggestion.
NAMES_REFUSED_SERVICE = envelope(
    fields=[fact('property.ongoing_risk', 'active_leak', 'water is still dripping')],
    services=['vehicle_recovery_request'],
    reply=(
        'Water still dripping, noted. I can also arrange vehicle recovery for you — '
        'see the option below. Is anyone hurt?'
    ),
)
HONEST_REWRITE = envelope(
    fields=[fact('property.ongoing_risk', 'active_leak', 'water is still dripping')],
    reply='Water still dripping, noted. Is anyone hurt?',
)


def _provider(*proposals: dict[str, Any]) -> V8JourneyProvider:
    provider = V8JourneyProvider([])
    provider.gateway.responses.extend(
        ModelResponse(completion_status=ModelCompletionStatus.COMPLETE, structured_output=item)
        for item in proposals
    )
    return provider


def test_inconsistent_reply_is_sent_back_once_and_the_rewrite_is_shown(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = _provider(NAMES_REFUSED_SERVICE, HONEST_REWRITE)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-once')
    turn = journey.send('The water is still dripping through the ceiling.')

    # Two model calls: the original and the recall carrying Runtime's ruling.
    assert len(provider.gateway.requests) == 2
    recall_messages = provider.gateway.requests[1].messages
    review = json.loads(recall_messages[-1].content or '{}')['runtime_review']
    assert review['reason'] == 'reply_contradicts_ledger'
    assert any(item['kind'] == 'names_rejected_service' for item in review['problems'])
    assert any(
        part['part'] == 'service_suggestion' and part['reason'] == 'service_not_eligible'
        for part in review['rejected_parts']
    )
    # The claimant sees the model's rewrite, untouched; the accepted fact stands.
    assert (
        turn['agent_message']['content']['text'] == 'Water still dripping, noted. Is anyone hurt?'
    )
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None and claim.form['property.ongoing_risk'].value == 'active_leak'


def test_twice_inconsistent_reply_enters_recovery_with_the_message_saved(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = _provider(NAMES_REFUSED_SERVICE, NAMES_REFUSED_SERVICE)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-twice')
    response = client.post(
        f'/api/v1/claims/{journey.claim_id}/sessions/{journey.session_id}/messages',
        headers={
            'Authorization': 'Bearer synthetic-claimant',
            'Idempotency-Key': 'recall-twice-1',
            'If-Match': str(journey.revision),
        },
        json={
            'client_message_id': 'recall-twice-1',
            'content': {'type': 'text', 'text': 'The water is still dripping through the ceiling.'},
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert len(provider.gateway.requests) == 2
    assert body['agent_message'] is None
    assert body['recovery']['rule_id'] == 'claimant_turn.model_invalid_response'
    # No spliced or stripped reply reached the claimant; the message is kept.
    assert len(repository.list_messages(journey.claim_id, journey.session_id, 'cus_demo')) == 1


def test_consistent_reply_costs_one_call() -> None:
    from backend.services.reply_consistency import review_reply
    from backend.services.turn_proposal_validation import ValidatedTurn

    validated = ValidatedTurn(
        reply='Noted. Is anyone hurt?',
        form_changes=[],
        contents_item_changes=[],
        next_question=None,
        service_identities=(),
        state_changes=[],
        escalation=None,
        ready_to_create=False,
        confirms_batch=False,
        rejected=[],
    )
    assert review_reply(validated).consistent
    accepted_service = ValidatedTurn(
        reply='I will arrange a tow for you.',
        form_changes=[],
        contents_item_changes=[],
        next_question=None,
        service_identities=('vehicle_recovery_request',),
        state_changes=[],
        escalation=None,
        ready_to_create=False,
        confirms_batch=False,
        rejected=[],
    )
    # offer_service only creates a pending card this turn; arranging still requires the
    # claimant's own consent on that card in a later turn. An arrangement claim is a lie
    # regardless of whether a service was accepted this turn.
    review = review_reply(accepted_service)
    assert not review.consistent
    assert review.inconsistencies[0].kind == 'claims_arrangement_without_service'

    offered_without_promise = ValidatedTurn(
        reply="I've noted your request for a tow. Is anyone hurt?",
        form_changes=[],
        contents_item_changes=[],
        next_question=None,
        service_identities=('vehicle_recovery_request',),
        state_changes=[],
        escalation=None,
        ready_to_create=False,
        confirms_batch=False,
        rejected=[],
    )
    # Describing the offer itself, without claiming it is already arranged, remains fine.
    assert review_reply(offered_without_promise).consistent


def _validated(
    reply: str, *, services: tuple[str, ...] = (), escalated: bool = False
) -> ValidatedTurn:
    return ValidatedTurn(
        reply=reply,
        form_changes=[],
        contents_item_changes=[],
        next_question=None,
        service_identities=services,
        state_changes=[],
        escalation=(
            V8Escalation(kind='professional_review', reason='Coverage needs a person.')
            if escalated
            else None
        ),
        ready_to_create=False,
        confirms_batch=False,
        rejected=[],
    )


@pytest.mark.parametrize(
    ('reply', 'kind'),
    [
        (
            'Glad nobody is hurt. Would you need any repair services or guidance at this point?',
            'offers_service_in_words',
        ),
        ('Do you need any specific assistance at this time?', 'offers_service_in_words'),
        (
            'Rental cover is not in the wording I have. Please check with your insurer.',
            'refers_to_insurer',
        ),
        ("I've escalated this for a review.", 'claims_escalation_without_one'),
        ('Do you need guidance for traffic crash reporting?', 'offers_service_in_words'),
    ],
)
def test_review_catches_words_the_turn_does_not_back(reply: str, kind: str) -> None:
    from backend.services.reply_consistency import review_reply

    review = review_reply(_validated(reply))

    assert [item.kind for item in review.inconsistencies] == [kind]


def test_review_allows_fact_questions_offers_by_card_and_real_escalation() -> None:
    from backend.services.reply_consistency import review_reply

    assert review_reply(_validated('Does the car need towing?')).consistent
    assert review_reply(
        _validated('Can I help with a tow?', services=('vehicle_recovery_request',))
    ).consistent
    assert review_reply(
        _validated("I've passed this to a claims specialist.", escalated=True)
    ).consistent
    # Promising an answer is only true once the question was passed on.
    promise = 'That clause is not in the wording I have; our claims team will confirm.'
    assert [item.kind for item in review_reply(_validated(promise)).inconsistencies] == [
        'promises_answer_without_question'
    ]
    passed_on = replace(
        _validated(promise),
        northwind_questions=(
            V8NorthwindQuestion(
                question='Is my hire car covered?',
                claimant_wording='is a hire car covered',
                model_view='Not in the excerpts.',
            ),
        ),
    )
    assert review_reply(passed_on).consistent


def test_a_rewrite_that_drops_the_recorded_facts_keeps_them(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # The rewrite is about the words; facts the first answer recorded stay.
    words_only = {**HONEST_REWRITE, 'field_changes': []}
    provider = _provider(NAMES_REFUSED_SERVICE, words_only)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-keeps-facts')

    turn = journey.send('The water is still dripping through the ceiling.')

    assert turn['agent_message']['content']['text'] == HONEST_REWRITE['reply']
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None and claim.form['property.ongoing_risk'].value == 'active_leak'


class _LookupThenRecall(GatewayAgent):
    """A coverage question: context.resolve, its continuation, then one recall."""

    def __init__(self, first_reply: dict[str, Any], rewrite: dict[str, Any]) -> None:
        self.gateway = _RecordingGateway([])
        super().__init__(self.gateway)
        self.first_reply = first_reply
        self.rewrite = rewrite

    def propose_turn(self, context: AgentTurnContext) -> AgentProposal:
        context = replace(
            context,
            knowledge_context_loader=lambda _limit: {
                'status': 'evidence_found',
                'chunks': [POLICY_CHUNK],
            },
        )
        plan = plan_model_turn(context)
        assert plan is not None
        reference = next(
            ref for ref in plan.context_plan.references if ref.resource_type == 'policy_version'
        )
        self.gateway.responses.extend(
            [
                ModelResponse(
                    tool_calls=[
                        ModelToolCall(
                            call_id='call_hire_car',
                            name='context.resolve',
                            arguments={
                                'ref': reference.ref,
                                'selector': 'matching_facts_and_guidance',
                                'max_tokens': 600,
                            },
                        )
                    ],
                    completion_status=ModelCompletionStatus.COMPLETE,
                ),
                ModelResponse(
                    structured_output=self.first_reply,
                    completion_status=ModelCompletionStatus.COMPLETE,
                ),
                ModelResponse(
                    structured_output=self.rewrite,
                    completion_status=ModelCompletionStatus.COMPLETE,
                ),
            ]
        )
        return super().propose_turn(context)


POLICY_CHUNK = {
    'document_id': 'doc_hire_car',
    'chunk_id': 'chk_hire_car',
    'title': 'Synthetic motor policy wording',
    'section_path': 'MTR-BEN-04',
    'source_uri': 'fixture://hire-car',
    'version': 'MVP-2026.1',
    'checksum': 'synthetic-hire-car-checksum',
    'text': 'Hire car cover depends on the optional benefits shown on the schedule.',
}


def test_a_recall_after_a_tool_continuation_is_saved_with_three_calls(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # The real-model failure: proposal, context.resolve continuation and a
    # consistency recall in one turn returned HTTP 500 when the trace was saved.
    promise = envelope(reply='The claims team will check hire car cover. Is anyone hurt?')
    passed_on = {
        **promise,
        'northwind_questions': [
            {
                'question': 'Is a hire car covered while my car is repaired?',
                'claimant_wording': 'will my policy pay for a hire car',
                'model_view': 'Depends on the optional benefits on the schedule.',
            }
        ],
    }
    agent = _LookupThenRecall(promise, passed_on)
    provider = V8JourneyProvider([])
    provider.agent = agent
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'motor', 'recall-after-lookup')

    turn = journey.send('Will my policy pay for a hire car while my car is repaired?')

    assert len(agent.gateway.requests) == 3
    assert turn['agent_message']['content']['text'] == passed_on['reply']
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_demo'
    )
    assert trace is not None
    assert [call.ordinal for call in trace.invocations] == [1, 2, 3]
    assert trace.model_invocations == 3


def test_mentioning_a_question_passed_on_earlier_is_not_sent_back(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # Turn 1 passes the hire-car question on; turn 2 reminds the claimant the
    # team will confirm it. The review sees the open question and keeps the reply.
    passes_on = {
        **envelope(reply='The claims team will confirm hire car cover. Is anyone hurt?'),
        'northwind_questions': [
            {
                'question': 'Is my hire car covered while my car is repaired?',
                'claimant_wording': 'will my policy pay for a hire car',
                'model_view': 'Not in the excerpts.',
            }
        ],
    }
    reminds = envelope(reply='The claims team will confirm the hire car question. Is anyone hurt?')
    provider = _provider(passes_on, reminds)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-earlier-question')

    journey.send('Water is coming through the ceiling. Can someone tell me about a hire car?')
    turn = journey.send('Nobody is hurt.')

    assert len(provider.gateway.requests) == 2
    assert turn['agent_message']['content']['text'] == reminds['reply']


def test_review_allows_a_promise_about_a_question_passed_on_earlier() -> None:
    from backend.services.reply_consistency import review_reply
    from backend.services.reply_judge import turn_ledger

    promise = 'Our claims team will confirm the hire car question. What is the registration?'
    earlier = replace(_validated(promise), earlier_open_questions=('Is my hire car covered?',))
    assert review_reply(earlier).consistent
    assert turn_ledger(earlier)['questions_passed_on'] == ['Is my hire car covered?']
    # An open question about something else does not back a new promise.
    unrelated = replace(
        _validated(
            'The claims team will confirm whether Northwind accepts liability. '
            'What is the registration?'
        ),
        earlier_open_questions=('Is my hire car covered?',),
    )
    assert [item.kind for item in review_reply(unrelated).inconsistencies] == [
        'promises_answer_without_question'
    ]
