from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def test_seed_scenarios_populates_the_urgent_human_request_and_review_queues() -> None:
    with TestClient(create_app(Settings(), FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200
        body = seeded.json()
        assert body['status'] == 'seeded'
        assert set(body['scenario_ids']) == {
            'AT-02-coverage-ambiguity',
            'AT-04-urgent',
            'AT-05-human-request',
        }
        assert len(body['claim_ids']) == 3

        listing = client.get('/api/v1/workbench/claims', headers=STAFF_AUTH)
        assert listing.status_code == 200
        items = {item['claim_id']: item for item in listing.json()['items']}
        assert set(body['claim_ids']) <= set(items)
        priorities = {items[claim_id]['priority'] for claim_id in body['claim_ids']}
        assert priorities == {'urgent', 'high', 'standard'}


def test_seed_scenarios_rejects_non_staff_credentials() -> None:
    with TestClient(create_app(Settings(), FixtureRepository())) as client:
        response = client.post('/api/v1/workbench/demo/seed-scenarios', headers=CLAIMANT_AUTH)

    assert response.status_code == 403


def test_seed_scenarios_does_not_change_a_nonempty_queue() -> None:
    with TestClient(create_app(Settings(), FixtureRepository())) as client:
        assert (
            client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH).status_code
            == 200
        )
        response = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)

    assert response.status_code == 409
    assert response.json()['error']['code'] == 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'
