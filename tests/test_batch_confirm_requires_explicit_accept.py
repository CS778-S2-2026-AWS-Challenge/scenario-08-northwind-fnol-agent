"""Q63: Runtime accepts the displayed batch only from an unqualified claimant reply."""

from collections.abc import Callable
from inspect import unwrap
from typing import Any, cast

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from backend.services.turn_reducer import is_explicit_batch_accept
from tests.journey_v8_support import CLAIMANT, Journey, V8JourneyProvider, envelope, fact
from tests.test_journey_v8_home import agent_turn_provider


def waiting_home(app: FastAPI, client: TestClient, final_proposal: dict[str, Any]) -> Journey:
    provider = cast(Callable[[], V8JourneyProvider], unwrap(agent_turn_provider))()
    provider.gateway.responses[-1] = ModelResponse(
        completion_status=ModelCompletionStatus.COMPLETE, structured_output=final_proposal
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'batch-authority')
    journey.send('A pipe burst in my bathroom last night in Wellington and flooded the lounge.')
    journey.send('No one was hurt but water is still dripping from the ceiling.')
    turn = journey.send(
        '12 Example Street, Wellington. The lounge ceiling and wall are affected; '
        'we can still live here.'
    )
    assert turn['dynamic_form']['requirements']['ready_pending_confirmation'] is True
    assert 'loss.description' in turn['dynamic_form']['requirements']['recorded']
    return journey


@pytest.mark.parametrize(
    'unsupported_prose',
    [
        'All details are now confirmed. Your claim is ready to create.',
        'I have recorded the information as confirmed: - property.habitable: true '
        '- property.ongoing_risk: active_leak Your claim is now ready to be created.',
    ],
)
def test_scoped_yes_cannot_confirm_unmentioned_fields_or_claim_batch_success(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    unsupported_prose: str,
) -> None:
    raw = envelope(
        fields=[fact('property.habitable', True, 'we can still live here')], confirms=True
    )
    raw['reply'] = (
        f'I noted that you can still live here. {unsupported_prose} '
        'Is there anything else you want to add?'
    )
    journey = waiting_home(app, client, raw)
    turn = journey.send('Yes we can still live here')
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None
    assert claim.form['property.habitable'].status.value == 'confirmed'
    assert claim.form['loss.description'].status.value == 'proposed'
    assert turn['dynamic_form']['requirements']['ready'] is False
    reply = turn['agent_message']['content']['text']
    assert 'All details are now confirmed.' not in reply
    assert 'Your claim is ready to create.' not in reply
    assert 'as confirmed' not in reply
    assert 'ready to be created' not in reply
    assert 'I noted that you can still live here.' in reply
    assert 'Is there anything else you want to add?' in reply
    blocked = client.post(
        f'/api/v1/claims/{journey.claim_id}/creation',
        headers={
            **CLAIMANT,
            'Idempotency-Key': 'scoped-premature-create',
            'If-Match': str(journey.revision),
        },
    )
    assert blocked.status_code == 409
    assert blocked.json()['error']['code'] == 'CONFIRMATION_REQUIRED'


def test_truthfulness_preserves_negated_readiness_and_legitimate_questions() -> None:
    from backend.services.turn_proposal_validation import truthful_reply

    reply = (
        'The claim is not ready to be created. All details are not confirmed. '
        'Is the claim ready to be created? Can you confirm these details?'
    )
    assert truthful_reply(reply, batch_confirmed=False, ready_to_create=False) == reply


@pytest.mark.parametrize('message', ['Yes', '是', '对', '没问题', 'Yes all correct.'])
def test_plain_accept_confirms_displayed_batch_even_when_model_boolean_is_false(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
    message: str,
) -> None:
    journey = waiting_home(app, client, envelope(confirms=False))
    turn = journey.send(message)
    assert turn['dynamic_form']['requirements']['ready'] is True
    claim = repository.get_claim(journey.claim_id, 'cus_demo')
    assert claim is not None and claim.form['loss.description'].status.value == 'confirmed'


@pytest.mark.parametrize(
    'message',
    [
        'Yes, and the wall is damaged too',
        'Yes we can still live here',
        'Correct the address',
        '是\uff0c但是地址不同',
        '对\uff0c房子可以住',
    ],
)
def test_acceptance_is_a_complete_phrase_not_a_yes_prefix(message: str) -> None:
    assert not is_explicit_batch_accept(message)
