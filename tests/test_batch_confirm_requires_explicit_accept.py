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
from tests.journey_v8_support import Journey, V8JourneyProvider, envelope, fact
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
    # The model summarised; Runtime bound a confirmation request to exactly the
    # fields the summary declared. loss.description is recorded, not confirmed.
    assert 'loss.description' in turn['dynamic_form']['requirements']['recorded']
    assert turn['dynamic_form']['requirements']['ready'] is True
    return journey


def test_scoped_yes_confirms_only_the_field_it_answers(
    app: FastAPI,
    client: TestClient,
    repository: FixtureRepository,
) -> None:
    raw = envelope(
        fields=[fact('property.habitable', True, 'we can still live here')],
        confirms=True,
        reply='I noted that you can still live here. Is there anything else you want to add?',
    )
    journey = waiting_home(app, client, raw)
    turn = journey.send('Yes we can still live here')
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
    assert claim is not None
    # The answer settles the one fact it speaks to; the model's confirms_batch
    # flag does not turn a field-specific answer into acceptance of the summary.
    assert claim.form['property.habitable'].status.value == 'confirmed'
    assert claim.form['loss.description'].status.value == 'proposed'
    reply = turn['agent_message']['content']['text']
    assert reply == 'I noted that you can still live here. Is there anything else you want to add?'
    # Recorded facts travel with the report; they no longer block creation.
    assert turn['dynamic_form']['requirements']['ready'] is True


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
    claim = repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b')
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
