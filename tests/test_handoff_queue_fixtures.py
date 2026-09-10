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


@pytest.mark.parametrize(
    ('view', 'scenario_id'),
    [
        ('incomplete_claims', 'AT-08-resume'),
        ('ready_to_progress', 'AT-01-clear-motor'),
        ('awaiting_evidence', 'AT-06-pending-evidence'),
        ('professional_review', 'AT-02-coverage-ambiguity'),
        ('created_routed', 'AT-10-controlled-assessor'),
    ],
)
def test_staff_queue_views_use_authoritative_projected_work(
    view: str,
    scenario_id: str,
) -> None:
    repository, claim_id = _load(scenario_id)

    with _staff_client(repository) as client:
        response = client.get(
            '/api/v1/workbench/claims',
            params={'view': view},
            headers={'Authorization': 'Bearer synthetic-staff'},
        )

    assert response.status_code == 200
    assert [item['claim_id'] for item in response.json()['items']] == [claim_id]


def test_incomplete_claims_view_and_metadata_describe_collecting_work() -> None:
    repository, claim_id = _load('AT-08-resume')
    headers = {'Authorization': 'Bearer synthetic-staff'}

    with _staff_client(repository) as client:
        metadata = client.get('/api/v1/workbench/claims/filter-metadata', headers=headers)
        response = client.get(
            '/api/v1/workbench/claims',
            params={'view': 'incomplete_claims'},
            headers=headers,
        )

    assert {
        'value': 'incomplete_claims',
        'label': 'Incomplete claims',
        'group': 'operational',
    } in metadata.json()['views']
    assert [item['claim_id'] for item in response.json()['items']] == [claim_id]
    assert response.json()['items'][0]['workflow_state'] == 'collecting'
    assert response.json()['items'][0]['work_summary']['queue_key'] == 'processing'


def test_staff_queue_filters_by_status_priority_and_combined_state() -> None:
    repository = FixtureRepository()
    claim_ids: dict[str, str] = {}
    for scenario_id in ('AT-01-clear-motor', 'AT-02-coverage-ambiguity', 'AT-04-urgent'):
        loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, loaded)
        claim_ids[scenario_id] = loaded.claim.claim_id

    headers = {'Authorization': 'Bearer synthetic-staff'}
    with _staff_client(repository) as client:
        by_status = client.get(
            '/api/v1/workbench/claims?workflow_state=ready_for_next',
            headers=headers,
        )
        by_priority = client.get(
            '/api/v1/workbench/claims?priority=high',
            headers=headers,
        )
        combined = client.get(
            '/api/v1/workbench/claims?workflow_state=professional_review&priority=urgent',
            headers=headers,
        )
        no_match = client.get(
            '/api/v1/workbench/claims?workflow_state=created&priority=urgent',
            headers=headers,
        )

    assert by_status.status_code == 200
    assert [item['claim_id'] for item in by_status.json()['items']] == [
        claim_ids['AT-01-clear-motor']
    ]
    assert by_priority.status_code == 200
    assert [item['claim_id'] for item in by_priority.json()['items']] == [
        claim_ids['AT-02-coverage-ambiguity']
    ]
    assert combined.status_code == 200
    assert [item['claim_id'] for item in combined.json()['items']] == [claim_ids['AT-04-urgent']]
    assert no_match.status_code == 200
    assert no_match.json()['items'] == []


def test_staff_queue_searches_all_projected_claims_before_pagination() -> None:
    repository = FixtureRepository()
    claim_ids: dict[str, str] = {}
    for scenario_id in ('AT-01-clear-motor', 'AT-02-coverage-ambiguity', 'AT-04-urgent'):
        loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, loaded)
        claim_ids[scenario_id] = loaded.claim.claim_id

    headers = {'Authorization': 'Bearer synthetic-staff'}
    with _staff_client(repository) as client:
        first_page = client.get(
            '/api/v1/workbench/claims',
            params={'limit': 1},
            headers=headers,
        ).json()
        later_claim_id = next(
            claim_id
            for claim_id in claim_ids.values()
            if claim_id != first_page['items'][0]['claim_id']
        )
        result = client.get(
            '/api/v1/workbench/claims',
            params={'search': later_claim_id.upper(), 'limit': 1},
            headers=headers,
        )
        combined = client.get(
            '/api/v1/workbench/claims',
            params={'search': claim_ids['AT-04-urgent'], 'priority': 'urgent', 'limit': 1},
            headers=headers,
        )

    assert result.status_code == 200
    assert [item['claim_id'] for item in result.json()['items']] == [later_claim_id]
    assert result.json()['page'] == {'next_cursor': None}
    assert [item['claim_id'] for item in combined.json()['items']] == [claim_ids['AT-04-urgent']]


def test_staff_queue_searches_each_documented_projection_field() -> None:
    headers = {'Authorization': 'Bearer synthetic-staff'}

    repository, claim_id = _load('AT-01-clear-motor')
    with _staff_client(repository) as client:
        item = client.get('/api/v1/workbench/claims', headers=headers).json()['items'][0]
        queries = [
            claim_id.upper(),
            item['incident']['summary'].upper(),
            item['tags'][0]['code'].upper(),
            item['tags'][0]['label'].upper(),
        ]
        for query in queries:
            response = client.get(
                '/api/v1/workbench/claims',
                params={'search': query},
                headers=headers,
            )
            assert [value['claim_id'] for value in response.json()['items']] == [claim_id]
        unprojected_name = client.get(
            '/api/v1/workbench/claims',
            params={'search': 'Demo Claimant One'},
            headers=headers,
        )
        assert item['claimant']['display_name'] is None
        assert unprojected_name.json()['items'] == []

    repository, claim_id = _load('AT-02-coverage-ambiguity')
    with _staff_client(repository) as client:
        item = client.get('/api/v1/workbench/claims', headers=headers).json()['items'][0]
        queries = [
            item['incident']['family'].upper(),
            item['work_summary']['current_work_item']['requested_outcome'].upper(),
        ]
        for query in queries:
            response = client.get(
                '/api/v1/workbench/claims',
                params={'search': query},
                headers=headers,
            )
            assert [value['claim_id'] for value in response.json()['items']] == [claim_id]

    repository, claim_id = _load('AT-10-controlled-assessor')
    with _staff_client(repository) as client:
        item = client.get('/api/v1/workbench/claims', headers=headers).json()['items'][0]
        response = client.get(
            '/api/v1/workbench/claims',
            params={'search': item['display_reference'].lower()},
            headers=headers,
        )
    assert item['display_reference'] != claim_id
    assert [value['claim_id'] for value in response.json()['items']] == [claim_id]


def test_combined_filters_apply_before_rank_ordering_and_cursor_pagination() -> None:
    repository = FixtureRepository()
    claim_ids: dict[str, str] = {}
    for scenario_id in ('AT-02-coverage-ambiguity', 'AT-04-urgent', 'AT-05-human-request'):
        loaded = load_scenario(SCENARIO_DIRECTORY / f'{scenario_id}.json')
        seed_scenario(repository, loaded)
        claim_ids[scenario_id] = loaded.claim.claim_id

    headers = {'Authorization': 'Bearer synthetic-staff'}
    filters: dict[str, str | int] = {
        'workflow_state': 'professional_review',
        'tag': 'claim_type.motor',
        'search': 'motor',
        'limit': 1,
    }
    with _staff_client(repository) as client:
        first = client.get('/api/v1/workbench/claims', params=filters, headers=headers)
        cursor = first.json()['page']['next_cursor']
        assert isinstance(cursor, str)
        second_filters = dict(filters)
        second_filters['cursor'] = cursor
        second = client.get(
            '/api/v1/workbench/claims',
            params=second_filters,
            headers=headers,
        )

    assert first.status_code == 200
    assert [item['claim_id'] for item in first.json()['items']] == [claim_ids['AT-04-urgent']]
    assert first.json()['items'][0]['priority_projection']['level'] == 'urgent'
    assert second.status_code == 200
    assert second.json()['items'][0]['claim_id'] == claim_ids['AT-05-human-request']
    assert claim_ids['AT-02-coverage-ambiguity'] not in {
        first.json()['items'][0]['claim_id'],
        second.json()['items'][0]['claim_id'],
    }


def test_staff_queue_filter_metadata_is_canonical_without_claim_pages() -> None:
    headers = {'Authorization': 'Bearer synthetic-staff'}
    with _staff_client(FixtureRepository()) as client:
        response = client.get('/api/v1/workbench/claims/filter-metadata', headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert {
        'value': 'human_requests',
        'label': 'Staff assistance',
        'group': 'operational',
    } in payload['views']
    assert {'value': 'professional_review', 'label': 'Professional review'} in payload[
        'workflow_states'
    ]
    assert any(option['value'] == 'impact.vehicle_not_drivable' for option in payload['tags'])
    assert payload['tag_registry_version']
