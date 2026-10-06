"""D12: a reply that contradicts the ledger goes back to the model, never gets edited."""

import json
from dataclasses import replace
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.adapters.model_gateway import ModelGatewayConfig, OpenAICompatibleModelGateway
from backend.domain.agent_v8 import V8Escalation
from backend.domain.model_gateway import (
    ModelCapabilities,
    ModelCompletionStatus,
    ModelGatewayError,
    ModelGatewayErrorCode,
    ModelProfile,
    ModelProfileStatus,
    ModelRequest,
    ModelResponse,
    ModelToolCall,
)
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import AgentProposal, AgentTurnContext, InvariantGuardedAgent
from backend.services.model_agent import GatewayAgent
from backend.services.model_request_planner import plan_model_turn
from backend.services.reply_judge import ReplyJudge, turn_ledger
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


class _Verdicts(ReplyJudge):
    """Stands in for the review model: returns the given verdicts in order."""

    def __init__(self, *verdicts: list[tuple[str, str]]) -> None:
        super().__init__(lambda: _RecordingGateway([]))
        self.verdicts = list(verdicts)

    def problems(self, validated: Any) -> list[tuple[str, str]] | None:
        return self.verdicts.pop(0) if self.verdicts else []


NAMES_TOW = [('names_rejected_service', 'vehicle recovery')]


def _provider(*proposals: dict[str, Any], review: ReplyJudge | None = None) -> V8JourneyProvider:
    provider = V8JourneyProvider([])
    provider.gateway.responses.extend(
        ModelResponse(completion_status=ModelCompletionStatus.COMPLETE, structured_output=item)
        for item in proposals
    )
    provider.agent = GatewayAgent(provider.gateway, reply_judge=review)
    return provider


def test_inconsistent_reply_is_sent_back_once_and_the_rewrite_is_shown(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = _provider(NAMES_REFUSED_SERVICE, HONEST_REWRITE, review=_Verdicts(NAMES_TOW))
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
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None and claim.form['property.ongoing_risk'].value == 'active_leak'


def test_twice_inconsistent_reply_enters_recovery_with_the_message_saved(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = _provider(
        NAMES_REFUSED_SERVICE, NAMES_REFUSED_SERVICE, review=_Verdicts(NAMES_TOW, NAMES_TOW)
    )
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
    assert (
        len(repository.list_messages(journey.claim_id, journey.session_id, 'cus_8f41a2c90d7e463b'))
        == 1
    )
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, body['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
    )
    assert trace is not None and trace.failure_diagnostic is not None
    assert trace.failure_diagnostic.code == 'consistency_recall_truthfulness'
    assert trace.failure_diagnostic.path is None


@pytest.mark.parametrize(
    ('rewrite', 'status', 'diagnostic_code', 'diagnostic_path'),
    [
        (None, ModelCompletionStatus.COMPLETE, 'consistency_recall_output_missing', None),
        (
            {**HONEST_REWRITE, 'reply': []},
            ModelCompletionStatus.COMPLETE,
            'consistency_recall_output_schema_validation',
            'reply',
        ),
        (
            {**HONEST_REWRITE, 'model_chosen_secret_key': 'secret-value'},
            ModelCompletionStatus.COMPLETE,
            'consistency_recall_output_schema_validation',
            None,
        ),
        (
            HONEST_REWRITE,
            ModelCompletionStatus.INCOMPLETE,
            'consistency_recall_completion_status',
            None,
        ),
        (
            {**HONEST_REWRITE, 'reply': '   '},
            ModelCompletionStatus.COMPLETE,
            'consistency_recall_proposal_validation',
            None,
        ),
    ],
)
def test_rejected_rewrite_records_its_check_without_model_content(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    rewrite: dict[str, Any] | None,
    status: ModelCompletionStatus,
    diagnostic_code: str,
    diagnostic_path: str | None,
) -> None:
    provider = _provider(NAMES_REFUSED_SERVICE, review=_Verdicts(NAMES_TOW))
    provider.gateway.responses.append(
        ModelResponse(completion_status=status, structured_output=rewrite)
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', f'recall-{diagnostic_code}')
    turn = journey.send(
        'Synthetic claimant incident detail for diagnostic isolation.', expect_agent_message=False
    )

    assert turn['agent_message'] is None
    assert turn['recovery']['rule_id'] == 'claimant_turn.model_invalid_response'
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
    )
    assert trace is not None and trace.failure_diagnostic is not None
    assert trace.failure_diagnostic.code == diagnostic_code
    assert trace.failure_diagnostic.path == diagnostic_path
    assert 'Synthetic claimant incident detail' not in trace.model_dump_json()
    assert 'Water still dripping' not in trace.model_dump_json()
    assert 'model_chosen_secret_key' not in trace.model_dump_json()
    assert 'secret-value' not in trace.model_dump_json()


@pytest.mark.parametrize(
    ('error_code', 'recovery_rule'),
    [
        (ModelGatewayErrorCode.TIMEOUT, 'claimant_turn.model_timeout'),
        (ModelGatewayErrorCode.PROVIDER, 'claimant_turn.model_provider_terminal'),
    ],
)
def test_recall_gateway_rejection_keeps_its_error_and_records_stage(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    monkeypatch: pytest.MonkeyPatch,
    error_code: ModelGatewayErrorCode,
    recovery_rule: str,
) -> None:
    provider = _provider(NAMES_REFUSED_SERVICE, review=_Verdicts(NAMES_TOW))
    original_complete = provider.gateway.complete

    def fail_on_recall(request: ModelRequest) -> ModelResponse:
        if provider.gateway.requests:
            provider.gateway.requests.append(request)
            raise ModelGatewayError(error_code)
        return original_complete(request)

    monkeypatch.setattr(provider.gateway, 'complete', fail_on_recall)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', f'recall-gateway-{error_code.value}')
    turn = journey.send('The water is still dripping.', expect_agent_message=False)

    assert turn['recovery']['rule_id'] == recovery_rule
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
    )
    assert trace is not None and trace.failure_diagnostic is not None
    assert trace.reason_codes == [error_code.value]
    assert trace.failure_diagnostic.code == 'consistency_recall_gateway_failure'
    assert trace.failure_diagnostic.path is None


def test_real_gateway_malformed_recall_output_has_distinct_diagnostic(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = json.dumps(NAMES_REFUSED_SERVICE) if calls == 1 else 'not valid JSON'
        return httpx.Response(
            200,
            json={'choices': [{'finish_reason': 'stop', 'message': {'content': content}}]},
        )

    capabilities = ModelCapabilities(structured_output=True, tools=True)
    gateway = OpenAICompatibleModelGateway(
        ModelGatewayConfig(
            base_url='https://model.example.test/v1',
            model='synthetic-model',
            credential_environment_variable=None,
            timeout_seconds=5.0,
            capabilities=capabilities,
            profile=ModelProfile(
                profile_id='synthetic-recall',
                protocol='openai_compatible',
                provider='synthetic',
                model_identifier='synthetic-model',
                credential_reference=None,
                purpose='agent_turn',
                privacy_class='synthetic_fnol',
                capabilities=capabilities,
                structured_output_method='json_object',
                timeout_seconds=5.0,
                prompt_version='northwind-fnol-claimant-v8',
                evaluation_status=ModelProfileStatus.CONFIGURED,
            ),
            structured_output_method='json_object',
        ),
        transport=httpx.MockTransport(handler),
    )
    provider = V8JourneyProvider([])
    provider.agent = GatewayAgent(gateway, reply_judge=_Verdicts(NAMES_TOW))
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'real-gateway-malformed-recall')
    turn = journey.send('The water is still dripping.', expect_agent_message=False)

    assert calls == 2, turn['recovery']
    assert turn['recovery']['rule_id'] == 'claimant_turn.model_invalid_response'
    trace = repository.find_runtime_trace_for_trigger(
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
    )
    assert trace is not None and trace.failure_diagnostic is not None
    assert trace.reason_codes == ['malformed_response']
    assert trace.failure_diagnostic.code == 'consistency_recall_provider_output_invalid'
    assert trace.failure_diagnostic.path is None
    assert 'not valid JSON' not in trace.model_dump_json()


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
    'reply',
    [
        'Glad nobody is hurt. Would you need any repair services or guidance at this point?',
        'Rental cover is not in the wording I have. Please check with your insurer.',
        "I've escalated this for a review.",
        'That clause is not in the wording I have; our claims team will confirm.',
        'I will arrange a tow for you.',
    ],
)
def test_without_the_review_model_no_rule_judges_the_words(reply: str) -> None:
    from backend.services.reply_consistency import review_reply

    # Only the review model reads the words. When it is not there, the reply is
    # shown and the turn is marked as not reviewed; no pattern stands in for it.
    review = review_reply(_validated(reply))
    assert review.consistent
    assert not review.words_reviewed


def test_the_review_models_verdict_sends_the_reply_back() -> None:
    from backend.services.reply_consistency import review_reply

    review = review_reply(
        _validated('I will arrange a tow for you.'),
        _Verdicts([('claims_arrangement_without_service', 'I will arrange')]),
    )
    assert review.words_reviewed
    assert [item.kind for item in review.inconsistencies] == ['claims_arrangement_without_service']


def test_a_rewrite_that_drops_the_recorded_facts_keeps_them(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # The rewrite is about the words; facts the first answer recorded stay.
    words_only = {**HONEST_REWRITE, 'field_changes': []}
    provider = _provider(NAMES_REFUSED_SERVICE, words_only, review=_Verdicts(NAMES_TOW))
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-keeps-facts')

    turn = journey.send('The water is still dripping through the ceiling.')

    assert turn['agent_message']['content']['text'] == HONEST_REWRITE['reply']
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None and claim.form['property.ongoing_risk'].value == 'active_leak'


class _ReviewModel(ReplyJudge):
    """Stands in for the review model: a promise needs a question passed on."""

    def __init__(self) -> None:
        super().__init__(lambda: _RecordingGateway([]))
        self.ledgers: list[dict[str, object]] = []

    def problems(self, validated: Any) -> list[tuple[str, str]] | None:
        ledger = turn_ledger(validated)
        self.ledgers.append(ledger)
        if 'claims team will' in validated.reply and not ledger['questions_passed_on']:
            return [('promises_answer_without_question', 'the claims team will')]
        return []


class _LookupThenRecall(GatewayAgent):
    """A coverage question: context.resolve, its continuation, then one recall."""

    def __init__(self, first_reply: dict[str, Any], rewrite: dict[str, Any]) -> None:
        self.gateway = _RecordingGateway([])
        super().__init__(self.gateway, reply_judge=_ReviewModel())
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
                'basis': 'Depends on the optional benefits on the schedule.',
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
        journey.claim_id, turn['claimant_message']['message_id'], 'cus_8f41a2c90d7e463b'
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
                'basis': 'Not in the excerpts.',
            }
        ],
    }
    reminds = envelope(reply='The claims team will confirm the hire car question. Is anyone hurt?')
    provider = _provider(passes_on, reminds)
    review = _ReviewModel()
    provider.agent = GatewayAgent(provider.gateway, reply_judge=review)
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'recall-earlier-question')

    journey.send('Water is coming through the ceiling. Can someone tell me about a hire car?')
    turn = journey.send('Nobody is hurt.')

    assert len(provider.gateway.requests) == 2
    assert turn['agent_message']['content']['text'] == reminds['reply']
    assert review.ledgers[-1]['questions_passed_on'] == [
        'Is my hire car covered while my car is repaired?'
    ]


def test_an_earlier_question_reaches_the_review_model_without_excusing_other_promises() -> None:
    from backend.services.reply_consistency import review_reply
    from backend.services.reply_judge import JUDGE_INSTRUCTION

    unrelated = replace(
        _validated(
            'The claims team will confirm whether Northwind accepts liability. '
            'What is the registration?'
        ),
        earlier_open_questions=('Is my hire car covered?',),
    )
    # The model is asked whether the promise is about a question passed on,
    # and is given the earlier one to compare.
    assert 'is not one of questions_passed_on' in JUDGE_INSTRUCTION
    assert turn_ledger(unrelated)['questions_passed_on'] == ['Is my hire car covered?']

    class _Flags(ReplyJudge):
        def __init__(self) -> None:
            super().__init__(lambda: _RecordingGateway([]))

        def problems(self, validated: Any) -> list[tuple[str, str]] | None:
            return [('promises_answer_without_question', 'accepts liability')]

    # When the model reports the promise, an open question elsewhere on the
    # Claim does not excuse it.
    assert [item.kind for item in review_reply(unrelated, _Flags()).inconsistencies] == [
        'promises_answer_without_question'
    ]
