from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.core.config import Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.scenario_loader import load_scenario, seed_scenario

SCENARIO_PATH = (
    Path(__file__).parents[1]
    / 'backend'
    / 'demo_data'
    / 'scenarios'
    / 'AT-06-pending-evidence.json'
)


def test_claimant_evidence_projection_excludes_internal_records_and_aggregate_counts() -> None:
    scenario = load_scenario(SCENARIO_PATH)
    repository = FixtureRepository()
    seed_scenario(repository, scenario)
    client = TestClient(create_app(Settings(), repository))
    claimant_auth = {'Authorization': 'Bearer synthetic-claimant'}

    claimant_evidence = client.get(
        f'/api/v1/claims/{scenario.claim.claim_id}/evidence',
        headers=claimant_auth,
    )
    claimant_claim = client.get(
        f'/api/v1/claims/{scenario.claim.claim_id}',
        headers=claimant_auth,
    )
    staff = client.get(
        f'/api/v1/workbench/claims/{scenario.claim.claim_id}',
        headers={'Authorization': 'Bearer synthetic-staff'},
    )

    assert claimant_evidence.status_code == 200
    claimant_items = claimant_evidence.json()['items']
    assert {item['evidence_id'] for item in claimant_items} == {'evd_fixture_at06_police'}
    assert {item['source'] for item in claimant_items} == {'claimant'}
    assert all('provenance' not in item for item in claimant_items)
    assert all('wait_type' not in item for item in claimant_items)
    assert all('responsible_party' not in item for item in claimant_items)

    assert claimant_claim.status_code == 200
    assert claimant_claim.json()['evidence_summary']['pending'] == 1

    assert staff.status_code == 200
    staff_items = staff.json()['evidence']
    assert {item['evidence_id'] for item in staff_items} == {
        'evd_fixture_at06_police',
        'evd_fixture_at06_agency',
        'evd_fixture_at06_internal',
    }
    assert {item['source'] for item in staff_items} == {'claimant', 'external_system', 'staff'}
    assert staff.json()['evidence_summary']['pending'] == 3
