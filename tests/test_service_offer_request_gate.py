"""#1134 on the model path: only a verified explicit request opens offers before the story."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import CLAIMANT, V8JourneyProvider, envelope, fact
from tests.test_claim_api import submit_message
from tests.test_service_suggestion_uses_accepted_turn_family import _new_claim

RECOVERY = 'vehicle_recovery_request'
ASSESSMENT = 'vehicle_damage_assessment_routing'


def _first_turn_actions(
    app: FastAPI, client: TestClient, message: str, proposal: dict[str, object]
) -> list[dict[str, object]]:
    app.state.agent_turn_provider = InvariantGuardedAgent(V8JourneyProvider([proposal]))
    claim_id, session_id, revision = _new_claim(client)
    response = submit_message(
        client, CLAIMANT, claim_id, session_id, revision=revision, key='gate-turn', text=message
    )
    assert response.status_code == 200, response.text
    return list(response.json()['agent_message']['message_actions'])


@pytest.mark.parametrize(
    ('message', 'quote'),
    [
        # A refusal: the model suggests the service but the claimant did not ask.
        ('My car was rear-ended on Queen St and I do not want a tow.', None),
        # A quote the claimant never wrote cannot stand in for a request.
        ('My car was rear-ended on Queen St and I do not want a tow.', 'Please arrange a tow'),
        # An incidental mention of the service is not a request.
        ('My car was rear-ended on Queen St by a tow truck.', None),
    ],
)
def test_no_offer_before_the_story_without_a_verified_request(
    app: FastAPI, client: TestClient, message: str, quote: str | None
) -> None:
    proposal = envelope(
        fields=[fact('claim.product_family', 'motor', 'My car was rear-ended')],
        services=[RECOVERY],
        requested={RECOVERY: quote} if quote else None,
    )

    assert _first_turn_actions(app, client, message, proposal) == []


def test_a_description_confirmed_this_turn_opens_offers_this_turn(
    app: FastAPI, client: TestClient
) -> None:
    message = 'My car was rear-ended on Queen St this morning and the rear bumper is damaged.'
    proposal = envelope(
        fields=[
            fact('claim.product_family', 'motor', 'My car was rear-ended'),
            fact(
                'incident.description',
                'Rear-ended on Queen St; rear bumper damaged.',
                'My car was rear-ended on Queen St this morning',
            ),
        ],
        services=[ASSESSMENT],
    )

    actions = _first_turn_actions(app, client, message, proposal)

    assert [action['service_identity'] for action in actions] == [ASSESSMENT]


def test_a_misread_request_only_asks_for_consent_and_dispatches_nothing(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    # The model owns intent: if it lifts "want a tow" out of a refusal, the verbatim check
    # passes and a card appears. The card is itself the consent request, so nothing is
    # requested from any provider until the claimant grants it.
    proposal = envelope(
        fields=[fact('claim.product_family', 'motor', 'My car was rear-ended')],
        services=[RECOVERY],
        requested={RECOVERY: 'want a tow'},
    )
    message = 'My car was rear-ended on Queen St and I do not want a tow.'

    actions = _first_turn_actions(app, client, message, proposal)

    assert [action['service_identity'] for action in actions] == [RECOVERY]
    assert actions[0]['lifecycle_status'] == 'consent_required'
    claim = next(iter(repository.list_claims_internal()))
    assert repository.list_external_tasks_internal(claim.claim_id) == []
