"""INV-19: after the report is created, the conversation keeps adding, never overwriting.

A photo or a correction that arrives days later lands as a new assertion on the
field's history (or as new Evidence) with a new revision. The created claim's
snapshot, the original assertions, and the workflow state stay as they were.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.domain.model_gateway import ModelCompletionStatus, ModelResponse
from backend.repositories.fixture import FixtureRepository
from backend.services.agent import InvariantGuardedAgent
from tests.journey_v8_support import CLAIMANT, Journey, envelope, fact
from tests.test_journey_v8_home import HOME_SUMMARY_FIELDS
from tests.test_journey_v8_home import agent_turn_provider as home_provider


def test_supplement_after_creation_appends_without_overwriting(
    app: FastAPI, client: TestClient, repository: FixtureRepository
) -> None:
    provider = __import__('inspect').unwrap(home_provider)()
    provider.gateway.responses.append(
        ModelResponse(
            completion_status=ModelCompletionStatus.COMPLETE,
            structured_output=envelope(
                fields=[
                    fact(
                        'property.affected_areas',
                        ['lounge ceiling', 'wall', 'hallway carpet'],
                        'the hallway carpet is soaked too',
                    )
                ],
                reply='Thanks, I have added the hallway carpet to your report for the claims team.',
                action='answer_only',
            ),
        )
    )
    app.state.agent_turn_provider = InvariantGuardedAgent(provider)
    journey = Journey(client, 'home', 'post-submission')
    journey.send('A pipe burst in my bathroom last night in Wellington and flooded the lounge.')
    journey.send('No one was hurt but water is still dripping from the ceiling.')
    journey.send(
        '12 Example Street, Wellington. The lounge ceiling and wall are affected; '
        'we can still live here.'
    )
    journey.send('Yes all correct.')
    journey.create()
    created = journey.view()
    assert created['workflow_state'] == 'created'
    original_areas = created['form']['property.affected_areas']
    original_assertions = [item['assertion_id'] for item in original_areas['assertions']]
    created_revision = created['revision']
    external_claim = created['external_claim']

    turn = journey.send('Just noticed the hallway carpet is soaked too.')

    after = journey.view()
    # Same report, one revision later, still created.
    assert after['workflow_state'] == 'created'
    assert after['external_claim'] == external_claim
    # Persist-first: one revision for the saved message, one for the applied turn.
    assert after['revision'] == created_revision + 2
    # The new fact is appended as a further assertion; the earlier ones remain.
    areas = after['form']['property.affected_areas']
    assert 'hallway carpet' in areas['value']
    kept = [item['assertion_id'] for item in areas['assertions']]
    assert kept[: len(original_assertions)] == original_assertions
    assert len(kept) == len(original_assertions) + 1
    for code in HOME_SUMMARY_FIELDS:
        if code != 'property.affected_areas':
            assert after['form'][code] == created['form'][code]
    # The claimant hears the model, not a Runtime template.
    assert turn['agent_message']['content']['text'].startswith('Thanks, I have added')
    assert turn['recovery'] is None
    assert repository.get_claim(journey.claim_id, 'cus_8f41a2c90d7e463b') is not None


def test_view_after_creation_lists_the_original_messages(client: TestClient) -> None:
    journey = Journey(client, 'home', 'post-submission-view')
    assert journey.view()['form'] == {}
    listed = client.get(
        f'/api/v1/claims/{journey.claim_id}/sessions/{journey.session_id}/messages',
        headers=CLAIMANT,
    )
    assert listed.status_code == 200
