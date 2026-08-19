from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}


def test_seed_scenarios_populates_handoff_review_and_created_routed_queues() -> None:
    with TestClient(create_app(Settings(), FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200
        body = seeded.json()
        assert body['status'] == 'seeded'
        assert set(body['scenario_ids']) == {
            'AT-02-coverage-ambiguity',
            'AT-04-urgent',
            'AT-05-human-request',
            'AT-06-pending-evidence',
            'AT-10-controlled-assessor',
        }
        assert len(body['claim_ids']) == 5

        pending = client.get('/api/v1/workbench/claims?view=awaiting_evidence', headers=STAFF_AUTH)
        assert pending.status_code == 200
        pending_items = pending.json()['items']
        assert [item['claim_id'] for item in pending_items] == ['clm_fixture_at06']
        assert pending_items[0]['pending_wait_types'] == [
            'claimant',
            'external_agency',
            'internal',
        ]

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


def test_claimant_reads_seeded_coverage_review_without_an_internal_handoff() -> None:
    with TestClient(create_app(Settings(), FixtureRepository())) as client:
        seeded = client.post('/api/v1/workbench/demo/seed-scenarios', headers=STAFF_AUTH)
        assert seeded.status_code == 200

        response = client.get('/api/v1/claims/clm_fixture_at02', headers=CLAIMANT_AUTH)

    assert response.status_code == 200
    body = response.json()
    assert body['handoff'] is None
    next_step = body['customer_next_step']
    assert next_step['status'] == 'coverage_under_review'
    assert next_step['summary'] == (
        'Northwind is reviewing your policy coverage for this incident and will contact you '
        'with a coverage decision.'
    )
    assert next_step['responsible_party'] == 'northwind'
    assert next_step['can_resume'] is True
    assert next_step['required_items'] == []
