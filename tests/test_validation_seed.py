import gc
from pathlib import Path
from tempfile import TemporaryDirectory

import mongomock
from fastapi.testclient import TestClient

from backend.adapters.identity import SQLiteIdentityRepository
from backend.adapters.staff_identity import FixtureStaffIdentityRepository
from backend.app import create_app
from backend.core.config import IdentityMode, Settings
from backend.repositories.fixture import FixtureRepository
from backend.repositories.mongodb import MongoDBRepository
from backend.repositories.scenario_loader import load_scenario

STAFF_AUTH = {'Authorization': 'Bearer synthetic-staff'}
CLAIMANT_AUTH = {'Authorization': 'Bearer synthetic-claimant'}
SEED_PATH = '/api/v1/workbench/demo/seed-validation'
SETTINGS = Settings(environment='test', identity_mode=IdentityMode.DEVELOPER)


def test_validation_seed_creates_three_cross_role_graphs() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'seed-1'})

        assert response.status_code == 200
        body = response.json()
        assert body['scenario_ids'] == [
            'AT-14-field-states-motor',
            'AT-15-field-states-home',
            'AT-16-field-states-contents',
        ]
        assert len(body['claim_ids']) == 3
        assert client.get('/api/v1/staff/me', headers=STAFF_AUTH).status_code == 200

        for claim_id in body['claim_ids']:
            staff_claim = client.get(f'/api/v1/workbench/claims/{claim_id}', headers=STAFF_AUTH)
            claimant_claim = client.get(f'/api/v1/claims/{claim_id}', headers=CLAIMANT_AUTH)
            claimant_evidence = client.get(
                f'/api/v1/claims/{claim_id}/evidence', headers=CLAIMANT_AUTH
            )
            assert staff_claim.status_code == 200
            assert claimant_claim.status_code == 200
            assert claimant_evidence.status_code == 200
            stored_claim = repository.get_claim_internal(claim_id)
            assert stored_claim is not None
            assert stored_claim.assignee_id == 'stf_demo'
            assert claimant_claim.json()['claim_id'] == claim_id

            staff_sessions = client.get(
                f'/api/v1/workbench/claims/{claim_id}/sessions', headers=STAFF_AUTH
            )
            assert staff_sessions.status_code == 200
            assert len(staff_sessions.json()['items']) == 1
            session_id = staff_sessions.json()['items'][0]['session_id']
            messages = client.get(
                f'/api/v1/workbench/claims/{claim_id}/sessions/{session_id}/messages',
                headers=STAFF_AUTH,
            )
            evidence = client.get(
                f'/api/v1/workbench/claims/{claim_id}/evidence', headers=STAFF_AUTH
            )
            assert len(messages.json()['items']) == 4
            assert len(evidence.json()['items']) == 1
            assert {item['evidence_id'] for item in claimant_evidence.json()['items']} == {
                evidence.json()['items'][0]['evidence_id']
            }
            assert messages.json()['items'][-1]['evidence_refs'] == [
                evidence.json()['items'][0]['evidence_id']
            ]
            assert staff_claim.json()['claim_state']['evidence'] == 'unofficial'
            assert staff_claim.json()['section_summaries']['evidence']['needs_attention'] == 1

        contents_id = body['claim_ids'][2]
        contents = client.get(f'/api/v1/claims/{contents_id}', headers=CLAIMANT_AUTH).json()
        assert len(contents['contents_items']) == 2
        assert all('item_id' in item for item in contents['contents_items'])


def test_validation_seed_is_idempotent_and_requires_empty_queue() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        headers = {**STAFF_AUTH, 'Idempotency-Key': 'seed-replay'}
        first = client.post(SEED_PATH, headers=headers)
        replay = client.post(SEED_PATH, headers=headers)
        changed_key = client.post(
            SEED_PATH,
            headers={**STAFF_AUTH, 'Idempotency-Key': 'seed-other'},
        )

    assert first.status_code == 200
    assert replay.status_code == 200
    assert replay.json() == first.json()
    assert changed_key.status_code == 409
    assert changed_key.json()['error']['code'] == 'DEMO_SEED_REQUIRES_EMPTY_QUEUE'
    assert len(repository.list_claims_internal()) == 3


def test_validation_seed_enforces_staff_and_idempotency_boundaries() -> None:
    repository = FixtureRepository()
    with TestClient(create_app(SETTINGS, repository)) as client:
        missing_key = client.post(SEED_PATH, headers=STAFF_AUTH)
        claimant = client.post(
            SEED_PATH,
            headers={**CLAIMANT_AUTH, 'Idempotency-Key': 'claimant-seed'},
        )

    assert missing_key.status_code == 400
    assert missing_key.json()['error']['code'] == 'VALIDATION_ERROR'
    assert claimant.status_code == 403
    assert repository.list_claims_internal() == []


def test_validation_seed_rejects_inactive_staff_before_any_write() -> None:
    repository = FixtureRepository()
    app = create_app(SETTINGS, repository)
    app.state.staff_identity_repository._accounts['stf_demo'].active = False

    with TestClient(app) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'inactive'})

    assert response.status_code == 403
    assert response.json()['error']['code'] == 'ACCESS_DENIED'
    assert repository.list_claims_internal() == []


class _FailingMessageRepository(FixtureRepository):
    def save_message(self, message, customer_id):  # type: ignore[no-untyped-def]
        raise RuntimeError('injected persistence failure')


def test_validation_seed_rolls_back_when_a_child_write_fails() -> None:
    repository = _FailingMessageRepository()
    with TestClient(create_app(SETTINGS, repository), raise_server_exceptions=False) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'failure'})

    assert response.status_code == 500
    assert repository.list_claims_internal() == []
    presence = repository.get_staff_presence('stf_demo')
    assert presence is not None
    assert presence.revision == 1
    assert (
        repository.find_idempotency(
            'stf_demo',
            'POST /api/v1/workbench/demo/seed-validation',
            'failure',
        )
        is None
    )


def test_validation_seed_provisions_claimant_for_normal_sqlite_identity() -> None:
    with TemporaryDirectory(dir=Path.cwd()) as directory:
        identity_path = Path(directory) / 'claimant.sqlite'
        identity = SQLiteIdentityRepository(str(identity_path))
        settings = Settings(
            environment='test',
            identity_mode=IdentityMode.NORMAL,
            identity_db_path=str(identity_path),
        )
        repository = FixtureRepository()

        with TestClient(
            create_app(
                settings,
                repository,
                identity_repository=identity,
                staff_identity_repository=FixtureStaffIdentityRepository(),
            ),
        ) as client:
            staff_response = client.post(
                '/api/v1/staff/auth/sessions',
                json={'email': 'staff.one@example.invalid', 'password': 'northwind-demo-staff'},
            )
            assert staff_response.status_code == 201
            seed_response = client.post(
                SEED_PATH,
                headers={
                    'Authorization': f'Bearer {staff_response.json()["access_token"]}',
                    'Idempotency-Key': 'sqlite-seed',
                },
            )
            assert seed_response.status_code == 200
            claimant_response = client.post(
                '/api/v1/auth/sessions',
                json={
                    'email': 'claimant.one@example.invalid',
                    'password': 'northwind-demo-one',
                },
            )
            assert claimant_response.status_code == 201
            claimant_headers = {
                'Authorization': f'Bearer {claimant_response.json()["access_token"]}'
            }
            claims = client.get('/api/v1/claims', headers=claimant_headers)

        assert claims.status_code == 200
        assert len(claims.json()['items']) == 3
        del client
        del identity
        del repository
        gc.collect()


def test_validation_seed_uses_the_same_graph_boundary_for_mongodb() -> None:
    repository = MongoDBRepository(mongomock.MongoClient(), 'validation_seed_test')
    repository._atomic = lambda operation: operation(None)  # type: ignore[method-assign]

    with TestClient(create_app(SETTINGS, repository)) as client:
        response = client.post(SEED_PATH, headers={**STAFF_AUTH, 'Idempotency-Key': 'mongo-seed'})

    assert response.status_code == 200
    assert len(repository.list_claims_internal()) == 3
    assert all(
        len(repository.list_evidence(claim.claim_id, claim.customer_id)) == 1
        for claim in repository.list_claims_internal()
    )


def test_validation_source_scenarios_remain_unchanged() -> None:
    scenario_ids = (
        'AT-14-field-states-motor',
        'AT-15-field-states-home',
        'AT-16-field-states-contents',
    )
    for scenario_id in scenario_ids:
        scenario = load_scenario(Path('backend/demo_data/scenarios') / f'{scenario_id}.json')
        assert scenario.claim.customer_id == 'cus_demo'
        assert scenario.claim.assignee_id is None
        assert scenario.evidence == []
