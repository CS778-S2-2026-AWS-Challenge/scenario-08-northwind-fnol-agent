"""D12: a reply that contradicts the ledger goes back to the model, never gets edited."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact

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


def _provider(*proposals: dict) -> V8JourneyProvider:
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
    assert body['recovery']['rule_id'] == 'claimant_turn.model_dependency_failure'
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
    # An arrangement claim is only a problem when nothing was actually accepted.
    assert review_reply(accepted_service).consistent
