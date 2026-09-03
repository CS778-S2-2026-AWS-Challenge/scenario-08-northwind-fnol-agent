import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario
from backend.services.demo_seed import SCENARIO_DIRECTORY

DEVELOPER_SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def _load(scenario_id: str) -> tuple[FixtureRepository, str]:
    loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)
    return repository, loaded.claim.claim_id


def _staff_client(repository: FixtureRepository) -> TestClient:
    return TestClient(create_app(DEVELOPER_SETTINGS, repository))


def _handoff_card(repository: FixtureRepository, claim_id: str) -> dict[str, object]:
    with _staff_client(repository) as client:
        response = client.get(
            f'/api/v1/workbench/claims/{claim_id}/handoffs',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
    assert response.status_code == 200
    handoffs = response.json()['items']
    assert len(handoffs) == 1
    return handoffs[0]  # type: ignore[no-any-return]


@pytest.mark.parametrize(
    ('scenario_id', 'expected_priority', 'expected_gaps'),
    [
        ('AT-04-urgent', 'urgent', ['vehicle.drivable', 'authorities.emergency_services_notified']),
        ('AT-05-human-request', 'standard', ['incident.location']),
        ('AT-02-coverage-ambiguity', 'high', []),
    ],
)
def test_handoff_card_exposes_priority_facts_gaps_reason_and_requested_action(
    scenario_id: str,
    expected_priority: str,
    expected_gaps: list[str],
) -> None:
    repository, claim_id = _load(scenario_id)
    card = _handoff_card(repository, claim_id)

    assert card['priority'] == expected_priority
    assert card['reason']
    assert card['requested_action']
    packet = card['packet']
    assert isinstance(packet, dict)
    assert packet['missing_items'] == expected_gaps
    confirmed_fields = [
        code for code, field in packet['form_snapshot'].items() if field['status'] == 'confirmed'
    ]
    assert confirmed_fields
    assert packet['incident_summary']


@pytest.mark.parametrize(
    'scenario_id',
    ['AT-04-urgent', 'AT-05-human-request', 'AT-02-coverage-ambiguity'],
)
def test_handoff_card_is_self_contained_without_reading_full_conversation(scenario_id: str) -> None:
    repository, claim_id = _load(scenario_id)
    card = _handoff_card(repository, claim_id)

    # The card alone must carry confirmed facts, gaps, reason, and requested action;
    # staff should not need the messages list to act on it.
    assert set(card) >= {
        'handoff_id',
        'priority',
        'queue',
        'reason',
        'requested_action',
        'packet',
    }
    packet = card['packet']
    assert isinstance(packet, dict)
    assert 'form_snapshot' in packet
    assert 'missing_items' in packet
    assert 'promised_next_step' in packet


def test_coverage_ambiguity_handoff_uses_a_staff_review_trigger_not_claimant_intent() -> None:
    repository, claim_id = _load('AT-02-coverage-ambiguity')

    card = _handoff_card(repository, claim_id)

    assert card['queue'] == 'professional_review'
    assert card['trigger'] == 'professional_review_required'
    assert card['support_need'] is None


def test_queue_list_surfaces_open_handoff_priority_per_claim() -> None:
    for scenario_id, expected_priority in (
        ('AT-04-urgent', 'urgent'),
        ('AT-05-human-request', 'standard'),
        ('AT-02-coverage-ambiguity', 'high'),
    ):
        repository, claim_id = _load(scenario_id)
        with _staff_client(repository) as client:
            listing = client.get(
                '/api/v1/workbench/claims',
                headers={'Authorization': 'Bearer synthetic-staff'},
            )
        assert listing.status_code == 200
        item = next(item for item in listing.json()['items'] if item['claim_id'] == claim_id)
        assert item['priority_projection']['level'] == expected_priority
        assert item['work_summary']['current_work_item'] is not None


def test_staff_handoff_views_filter_and_order_open_requests_by_priority() -> None:
    repository = FixtureRepository()
    claim_ids: dict[str, str] = {}
    for scenario_id in ('AT-05-human-request', 'AT-02-coverage-ambiguity', 'AT-04-urgent'):
        loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, loaded)
        claim_ids[scenario_id] = loaded.claim.claim_id

    with _staff_client(repository) as client:
        all_items = client.get(
            '/api/v1/workbench/claims',
            headers={'Authorization': 'Bearer synthetic-staff'},
        ).json()['items']
        urgent_items = client.get(
            '/api/v1/workbench/claims?view=urgent',
            headers={'Authorization': 'Bearer synthetic-staff'},
        ).json()['items']
        human_items = client.get(
            '/api/v1/workbench/claims?view=human_requests',
            headers={'Authorization': 'Bearer synthetic-staff'},
        ).json()['items']

    relevant = [item for item in all_items if item['claim_id'] in claim_ids.values()]
    assert [item['priority_projection']['level'] for item in relevant] == [
        'urgent',
        'high',
        'standard',
    ]
    assert [item['claim_id'] for item in urgent_items] == [claim_ids['AT-04-urgent']]
    assert [item['claim_id'] for item in human_items] == [claim_ids['AT-05-human-request']]
