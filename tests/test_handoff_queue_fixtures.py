import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario
from backend.services.demo_seed import SCENARIO_DIRECTORY


def _load(scenario_id: str) -> tuple[FixtureRepository, str]:
    loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
    repository = FixtureRepository()
    seed_scenario(repository, loaded)
    return repository, loaded.claim.claim_id


def _staff_client(repository: FixtureRepository) -> TestClient:
    return TestClient(create_app(Settings(), repository))


def _handoff_card(repository: FixtureRepository, claim_id: str) -> dict[str, object]:
    with _staff_client(repository) as client:
        detail = client.get(
            f'/api/v1/workbench/claims/{claim_id}',
            headers={'Authorization': 'Bearer synthetic-staff'},
        )
    assert detail.status_code == 200
    handoffs = detail.json()['handoffs']
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
        assert item['priority'] == expected_priority
        assert item['open_handoff_count'] == 1
